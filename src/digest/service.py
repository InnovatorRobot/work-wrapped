"""Digest composition, SMTP sending, due-digest runner, and background scheduler."""

import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    APP_BASE_URL,
    DEFAULT_MONTHS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USER,
    smtp_configured,
)
from storage import _load_json, _save_json
from settings.service import get_user_settings
from auth.service import list_users

_STATE_FILE = "digest_state.json"


def compose_digest(summary, name, period_label):
    """Return (subject, html, text) for a digest built from a personal summary dict."""
    totals = summary.get("totals") or {}
    tr = summary.get("time_range_label", "")
    highlights = summary.get("highlights") or []
    nudges = summary.get("nudges") or []
    subject = "Work Wrapped — your {} recap".format(period_label)

    rows = [
        ("Jira tickets", totals.get("jira", 0)),
        ("Gerrit changes", totals.get("gerrit", 0)),
        ("Confluence pages", totals.get("confluence", 0)),
        ("Slack messages", totals.get("slack", 0)),
    ]

    text_lines = [
        "Hi {},".format(name or "there"),
        "",
        "Here's your {} recap ({}):".format(period_label, tr),
        "",
    ]
    text_lines += ["  {}: {}".format(label, val) for label, val in rows]
    text_lines.append("")
    if highlights:
        text_lines.append("Highlights:")
        text_lines += ["  - " + str(h) for h in highlights]
        text_lines.append("")
    if nudges:
        text_lines.append("Reminders:")
        text_lines += [
            "  - " + (n.get("message", "") if isinstance(n, dict) else str(n)) for n in nudges
        ]
        text_lines.append("")
    text_lines.append("Open your dashboard: {}".format(APP_BASE_URL))
    text = "\n".join(text_lines)

    row_html = "".join(
        "<tr><td style='padding:6px 12px;border:1px solid #dde;'>{}</td>"
        "<td style='padding:6px 12px;border:1px solid #dde;font-weight:700;'>{}</td></tr>".format(
            label, val
        )
        for label, val in rows
    )
    hl_html = (
        "<h3 style='font-size:15px;'>Highlights</h3><ul>"
        + "".join("<li>{}</li>".format(h) for h in highlights)
        + "</ul>"
        if highlights
        else ""
    )
    nudge_html = (
        "<h3 style='font-size:15px;'>Reminders</h3><ul>"
        + "".join(
            "<li>{}</li>".format(n.get("message", "") if isinstance(n, dict) else n) for n in nudges
        )
        + "</ul>"
        if nudges
        else ""
    )
    html = """<div style="font-family:Arial,sans-serif;color:#1a2232;max-width:560px;">
      <h2 style="margin:0 0 4px;">Your {period} recap</h2>
      <p style="color:#667;margin:0 0 16px;">{tr}</p>
      <table style="border-collapse:collapse;margin-bottom:16px;">{rows}</table>
      {hl}{nudge}
      <p style="margin-top:20px;"><a href="{url}" style="background:#4d8bff;color:#fff;
         padding:9px 16px;border-radius:6px;text-decoration:none;">Open dashboard</a></p>
      <p style="color:#99a;font-size:12px;margin-top:18px;">Hi {name} — for reflection, not ranking.
         Change or stop these in Settings.</p>
    </div>""".format(
        period=period_label,
        tr=tr,
        rows=row_html,
        hl=hl_html,
        nudge=nudge_html,
        url=APP_BASE_URL,
        name=name or "there",
    )
    return subject, html, text


def send_email(to, subject, html, text):
    """Send a multipart email via SMTP. Returns (ok, error)."""
    if not smtp_configured():
        return False, "SMTP not configured (set SMTP_HOST in .env)."
    if not to:
        return False, "No recipient address."
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        try:
            if SMTP_STARTTLS:
                server.starttls()
            if SMTP_USER:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to], msg.as_string())
        finally:
            server.quit()
        return True, None
    except Exception as e:  # noqa: BLE001 - report any SMTP failure to the caller
        return False, str(e)


def _build_summary(user_id, months, session_data=None):
    # Imported here to avoid import-time cycles at app startup.
    from summary.service import get_personal_summary

    sd = dict(session_data) if session_data else {}
    sd.setdefault("user_id", user_id)
    sd["months"] = months
    return get_personal_summary(sd)


def send_digest_for_user(user, period_label, session_data=None):
    """Compose and send a digest to one user. Returns (ok, error)."""
    user_id = user.get("id")
    email = user.get("email")
    name = user.get("name") or email
    st = get_user_settings(user_id)
    months = st.get("default_months", DEFAULT_MONTHS)
    summary = _build_summary(user_id, months, session_data=session_data)
    subject, html, text = compose_digest(summary, name, period_label)
    return send_email(email, subject, html, text)


def _period_key(frequency, now=None):
    now = now or datetime.now()
    if frequency == "weekly":
        iso = now.isocalendar()
        return "{}-W{:02d}".format(iso[0], iso[1])
    return "{}-{:02d}".format(now.year, now.month)


def run_due_digests(frequency, period_label=None):
    """Send digests to all users on `frequency`, once per period. Returns list of emails sent."""
    period_label = period_label or frequency
    if not smtp_configured():
        return []
    state = _load_json(_STATE_FILE)
    period = _period_key(frequency)
    sent = []
    for u in list_users():
        st = get_user_settings(u["id"])
        if st.get("digest_frequency") != frequency or not u.get("email"):
            continue
        key = "{}:{}".format(u["id"], frequency)
        if state.get(key) == period:
            continue  # already sent this period
        ok, _err = send_digest_for_user(u, period_label)  # uses cached data, no creds
        if ok:
            state[key] = period
            sent.append(u["email"])
    _save_json(_STATE_FILE, state)
    return sent


def _scheduler_loop():
    while True:
        try:
            now = datetime.now()
            if now.weekday() == 0:  # Monday
                run_due_digests("weekly", "weekly")
            if now.day == 1:  # first of month
                run_due_digests("monthly", "monthly")
        except Exception:
            pass
        time.sleep(3600)  # check hourly; the state file prevents duplicate sends


def start_scheduler():
    """Start the background digest scheduler (no-op if SMTP isn't configured)."""
    if not smtp_configured():
        return
    threading.Thread(target=_scheduler_loop, daemon=True).start()
