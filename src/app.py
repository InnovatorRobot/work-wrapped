"""
Personal & Team Work Wrapped Dashboard
A simple dashboard to gather work activity across Jira, Slack, Confluence, Gerrit.
NOT for ranking or comparing - for reflection and having info in one place.
"""

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import calendar
import csv
import io
import json
import os
import re
import secrets
from urllib.parse import quote

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

# Project root (parent of src/) for .env and frontend templates
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app_version():
    """Read version from VERSION file in project root (set at Docker build)."""
    try:
        p = os.path.join(_ROOT, "VERSION")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip() or "dev"
    except Exception:
        pass
    return "dev"


# Load .env from project root
try:
    from dotenv import load_dotenv

    _env_path = os.path.join(_ROOT, ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

from gerrit_client import GerritClient, GerritError
from jira_client import JiraClient, JiraError
from confluence_client import ConfluenceClient, ConfluenceError
from slack_client import SlackClient, SlackError

try:
    from llm_insights import categorize_confluence_titles
except Exception:
    categorize_confluence_titles = None

app = FastAPI(title="Work Wrapped")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production"),
)
templates = Jinja2Templates(directory=os.path.join(_ROOT, "frontend"))
app.mount(
    "/static", StaticFiles(directory=os.path.join(_ROOT, "frontend", "static")), name="static"
)

# Gerrit config
GERRIT_URL = os.environ.get("GERRIT_URL", "").rstrip("/")
GERRIT_VERIFY_SSL = os.environ.get("GERRIT_VERIFY_SSL", "true").lower() == "true"

# Jira config (optional)
JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_VERIFY_SSL = os.environ.get("JIRA_VERIFY_SSL", "true").lower() == "true"

# Confluence config (optional)
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "").rstrip("/")
CONFLUENCE_VERIFY_SSL = os.environ.get("CONFLUENCE_VERIFY_SSL", "true").lower() == "true"

# Gerrit: exclude these reviewers/CC from counts (e.g. bot accounts like svc00140)
GERRIT_EXCLUDE_REVIEWERS = frozenset(
    n.strip().lower()
    for n in os.environ.get("GERRIT_EXCLUDE_REVIEWERS", "svc00140").split(",")
    if n.strip()
)

# Data directory for goals and team-comparison (opt-in) storage
_DATA_DIR = os.path.join(_ROOT, "data")


def _ensure_data_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load_json(filename, default=None):
    path = os.path.join(_DATA_DIR, filename)
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save_json(filename, data):
    _ensure_data_dir()
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_goals(user_id):
    """Return goals dict for user: e.g. tickets_done, reviews, messages (optional targets)."""
    if not user_id:
        return {}
    data = _load_json("goals.json")
    return data.get(str(user_id)) or {}


def set_goals(user_id, goals):
    """Save goals for user. goals: dict with optional tickets_done, reviews, messages, etc."""
    if not user_id:
        return
    data = _load_json("goals.json")
    out = {}
    for k, v in (goals or {}).items():
        if v is None:
            continue
        try:
            out[k] = int(v)
        except (TypeError, ValueError):
            if str(v).strip():
                try:
                    out[k] = int(str(v).strip())
                except ValueError:
                    pass
    data[str(user_id)] = out
    _save_json("goals.json", data)


def get_team_optin(user_id):
    """Whether user has opted in to include their metrics in team average."""
    if not user_id:
        return False
    data = _load_json("team_optin.json")
    return data.get(str(user_id), False)


def set_team_optin(user_id, include):
    """Set opt-in for team comparison."""
    if not user_id:
        return
    data = _load_json("team_optin.json")
    data[str(user_id)] = bool(include)
    _save_json("team_optin.json", data)


def update_team_metrics(user_id, totals):
    """Store current user totals for team average (only meaningful when opted in)."""
    if not user_id or not get_team_optin(user_id):
        return
    data = _load_json("team_metrics.json")
    data[str(user_id)] = dict(totals)
    _save_json("team_metrics.json", data)


def get_team_average():
    """Return average totals across all opted-in users who have metrics stored."""
    data = _load_json("team_metrics.json")
    if not data:
        return None
    n = len(data)
    avg = {"jira": 0, "gerrit": 0, "confluence": 0, "slack": 0}
    for v in data.values():
        for k in avg:
            avg[k] += v.get(k, 0)
    for k in avg:
        avg[k] = round(avg[k] / n, 1) if n else 0
    return {"average": avg, "participant_count": n}


# --- Snapshots (named checkpoints to compare progress later) ---
def get_snapshots(user_id):
    """Return list of { id, label, date, totals } for user."""
    if not user_id:
        return []
    data = _load_json("snapshots.json")
    return data.get(str(user_id)) or []


def save_snapshot(user_id, label, totals):
    """Append a snapshot for user. Returns the new snapshot (with id and date)."""
    if not user_id or not (label or "").strip():
        return None
    data = _load_json("snapshots.json")
    key = str(user_id)
    if key not in data:
        data[key] = []
    import time

    snap = {
        "id": str(int(time.time() * 1000)),
        "label": (label or "").strip()[:80],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "totals": dict(totals) if totals else {},
    }
    data[key].append(snap)
    _save_json("snapshots.json", data)
    return snap


# Shareable link: token -> snapshot of summary (viewable without login)
SHARE_LINK_EXPIRY_DAYS = int(os.environ.get("SHARE_LINK_EXPIRY_DAYS", "30"))


def save_share_link(user_id, summary):
    """Store a snapshot of summary under a new token. Returns token or None."""
    if not user_id or not summary:
        return None
    data = _load_json("shared_links.json")
    token = secrets.token_urlsafe(32)
    created = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data[token] = {
        "user_id": str(user_id),
        "created_at": created,
        "user": summary.get("user") or {},
        "totals": summary.get("totals") or {},
        "time_range_label": summary.get("time_range_label", "Last 12 months"),
        "themes": summary.get("themes") or [],
        "highlights": summary.get("highlights") or [],
        "monthly": summary.get("monthly") or [],
    }
    _save_json("shared_links.json", data)
    return token


def get_share_link(token):
    """Return { user_id, created_at, summary } or None if not found or expired."""
    if not token or not token.strip():
        return None
    data = _load_json("shared_links.json")
    record = data.get(token.strip())
    if not record:
        return None
    created = record.get("created_at") or ""
    try:
        dt = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S")
        if (datetime.utcnow() - dt).days > SHARE_LINK_EXPIRY_DAYS:
            return None
    except (ValueError, TypeError):
        pass
    return record


# Time range options for filters: (months, label). Default 12.
TIME_RANGE_OPTIONS = [
    (3, "Last 3 months"),
    (6, "Last 6 months"),
    (12, "Last 12 months"),
    (24, "Last 2 years"),
    (36, "Last 3 years"),
]
VALID_MONTHS = frozenset(m for m, _ in TIME_RANGE_OPTIONS)
DEFAULT_MONTHS = 12


class LoginRequired(Exception):
    """Raised when a route requires login; next_url is used for redirect after login."""
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def require_session(request: Request):
    """Dependency: return request.session if logged in, else raise LoginRequired."""
    if "user_id" not in request.session:
        raise LoginRequired(next_url=str(request.url))
    return request.session


@app.exception_handler(LoginRequired)
def _login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url="/login?next=" + quote(exc.next_url, safe="/"))


def _template_context(request: Request, current_route=None, **kwargs):
    """Build context for Jinja2 with request, session, url_for, app_version."""
    def url_for(name: str, **path_params):
        if name == "static":
            return "/static/" + (path_params.get("filename") or "")
        return request.app.url_path_for(name, **path_params)

    ctx = {"request": request, "session": request.session, "url_for": url_for, "app_version": _app_version(), **kwargs}
    if current_route is not None:
        ctx["current_route"] = current_route
    return ctx


def get_gerrit_client():
    if not GERRIT_URL:
        raise GerritError("GERRIT_URL is not configured")
    return GerritClient(GERRIT_URL, verify_ssl=GERRIT_VERIFY_SSL)


def get_jira_client():
    if not JIRA_URL:
        raise JiraError("JIRA_URL is not configured")
    return JiraClient(JIRA_URL, verify_ssl=JIRA_VERIFY_SSL)


def get_confluence_client():
    if not CONFLUENCE_URL:
        raise ConfluenceError("CONFLUENCE_URL is not configured")
    return ConfluenceClient(CONFLUENCE_URL, verify_ssl=CONFLUENCE_VERIFY_SSL)


def get_slack_client():
    return SlackClient()


# --- Data ---


def _parse_jira_date(s):
    """Parse Jira ISO date string to date for day-diff. Returns None if invalid."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()[:19]  # 2025-01-15T10:30:00
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _jira_changelog_times(iss, created_str):
    """From issue changelog compute: first assignee date (time to grab), first activity date (first response proxy), total days in 'In Review'.
    Returns (grabbed_date, days_in_review, first_activity_date). first_activity_date = first changelog entry date.
    """
    grabbed_date = None
    first_activity_date = None
    review_entries = []  # (entry_time, exit_time) for each period in "In Review"

    changelog = iss.get("changelog") or {}
    histories = changelog.get("histories") or []
    for h in sorted(histories, key=lambda x: x.get("created") or ""):
        created_h = h.get("created") or ""
        try:
            if "T" in created_h:
                ts = datetime.fromisoformat(created_h.replace("Z", "+00:00")[:23])
            else:
                ts = datetime.strptime(created_h[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            ts = None
        if ts and first_activity_date is None:
            first_activity_date = ts.date() if hasattr(ts, "date") else ts
        for item in h.get("items") or []:
            field = (item.get("field") or "").lower()
            from_val = (item.get("fromString") or "").strip()
            to_val = (item.get("toString") or "").strip()

            if field == "assignee" and to_val and grabbed_date is None:
                if ts:
                    grabbed_date = ts.date() if hasattr(ts, "date") else ts
                break
            if field == "status":
                from_review = "review" in from_val.lower()
                to_review = "review" in to_val.lower()
                if to_review and not from_review and ts:
                    review_entries.append([ts, None])  # entered review
                elif from_review and not to_review and ts:
                    for e in reversed(review_entries):
                        if e[1] is None:
                            e[1] = ts
                            break

    days_in_review = 0.0
    for entry, exit_ in review_entries:
        if entry and exit_:
            delta = exit_ - entry
            days_in_review += delta.total_seconds() / 86400.0
    return grabbed_date, round(days_in_review, 2), first_activity_date


def _jira_epic_from_value(val):
    """Extract (epic_key, epic_name) from an Epic Link field value (string key or object with key/fields.summary)."""
    if not val:
        return "", ""
    if isinstance(val, str):
        return (val.strip(), val.strip()) if val.strip() else ("", "")
    if isinstance(val, dict):
        key = (val.get("key") or val.get("id") or "").strip()
        name = ""
        inner = val.get("fields") or {}
        if isinstance(inner, dict):
            name = (inner.get("summary") or inner.get("name") or "").strip()
        if not name:
            name = (val.get("name") or val.get("summary") or "").strip()
        return (key, name or key) if key else ("", "")
    return ("", "")


def _jira_issues_to_tickets(issues):
    """Convert Jira API issues to our ticket format (with assignee/reporter, epic, resolution and timing)."""
    # Epic Link custom field IDs we request (see jira_client.EPIC_LINK_FIELDS)
    _epic_link_field_ids = ["customfield_10014", "customfield_10008", "customfield_10009"]
    _epic_field_env = os.environ.get("JIRA_EPIC_FIELD")
    if _epic_field_env and _epic_field_env not in _epic_link_field_ids:
        _epic_link_field_ids = _epic_link_field_ids + [_epic_field_env]
    tickets = []
    for iss in issues:
        key = iss.get("key", "")
        fields = iss.get("fields") or {}
        summary = (fields.get("summary") or "").strip()
        created = fields.get("created") or ""
        updated = fields.get("updated") or created
        resolutiondate = fields.get("resolutiondate") or ""
        month = updated[:7] if len(updated) >= 7 else (created[:7] if len(created) >= 7 else "")
        proj = fields.get("project") or {}
        project_key = proj.get("key") or proj.get("name") or "?"
        status_obj = fields.get("status") or {}
        status = status_obj.get("name") or ""
        issuetype_obj = fields.get("issuetype") or {}
        issuetype = issuetype_obj.get("name") or ""
        # Epic detection: epic issues, parent epics, or optional custom field
        epic_key = ""
        epic_name = ""
        if issuetype.lower() == "epic":
            epic_key = key
            epic_name = summary
        parent = fields.get("parent") or {}
        parent_fields = parent.get("fields") or {}
        parent_issuetype = (parent_fields.get("issuetype") or {}).get("name") or ""
        if not epic_key and parent and parent_issuetype.lower() == "epic":
            epic_key = parent.get("key") or ""
            epic_name = (parent_fields.get("summary") or "").strip() or epic_key
        if not epic_key:
            for fid in _epic_link_field_ids:
                link_val = fields.get(fid)
                ek, en = _jira_epic_from_value(link_val)
                if ek:
                    epic_key = ek
                    epic_name = en
                    break
        # Fallback: any custom field whose value looks like an issue key (e.g. Epic Link with unknown ID)
        if not epic_key and isinstance(fields, dict):
            key_re = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
            for fname, val in fields.items():
                if not fname.startswith("customfield_"):
                    continue
                s = (
                    val
                    if isinstance(val, str)
                    else (val.get("key") or val.get("id") or "") if isinstance(val, dict) else ""
                ).strip()
                if s and key_re.match(s):
                    epic_key = s
                    epic_name = s  # will be resolved later by _enrich_jira_epic_names
                    break
        epic_label = epic_name or epic_key or ""

        assignee = fields.get("assignee")
        reporter = fields.get("reporter")
        assignee_name = (
            (assignee.get("name") or assignee.get("key") or assignee.get("accountId") or "")
            if assignee
            else ""
        )
        assignee_display = (
            (assignee.get("displayName") or assignee.get("name") or "") if assignee else ""
        )
        reporter_name = (
            (reporter.get("name") or reporter.get("key") or reporter.get("accountId") or "")
            if reporter
            else ""
        )
        reporter_display = (
            (reporter.get("displayName") or reporter.get("name") or "") if reporter else ""
        )

        # Time to resolution (created → resolutiondate)
        created_date = _parse_jira_date(created)
        res_date = _parse_jira_date(resolutiondate)
        days_to_resolution = None
        if created_date and res_date and res_date >= created_date:
            days_to_resolution = (res_date - created_date).days

        # Changelog: time to grab (first assignment), time in review, first activity (first response proxy)
        grabbed_date, days_in_review_float, first_activity_date = _jira_changelog_times(
            iss, created
        )
        days_to_grab = None
        if created_date and grabbed_date and grabbed_date >= created_date:
            days_to_grab = (grabbed_date - created_date).days
        # Assigned → resolved (first assignment to resolution)
        days_assigned_to_resolution = None
        if grabbed_date and res_date and res_date >= grabbed_date:
            days_assigned_to_resolution = (res_date - grabbed_date).days
        days_in_review = int(days_in_review_float) if days_in_review_float else None
        if days_in_review is not None and days_in_review_float > 0:
            days_in_review = max(1, int(round(days_in_review_float)))
        days_to_first_response = None
        if created_date and first_activity_date and first_activity_date >= created_date:
            days_to_first_response = (first_activity_date - created_date).days

        # Labels, components, priority, sprint
        labels = fields.get("labels") or []
        if not isinstance(labels, list):
            labels = []
        labels = [str(x).strip() for x in labels if str(x).strip()]
        components = fields.get("components") or []
        if isinstance(components, list):
            component_names = [
                (c.get("name") or "").strip()
                for c in components
                if isinstance(c, dict) and (c.get("name") or "").strip()
            ]
        else:
            component_names = []
        priority_obj = fields.get("priority")
        priority_name = (
            (priority_obj.get("name") or "").strip() if isinstance(priority_obj, dict) else ""
        )
        sprint_val = fields.get("customfield_10020")  # Jira Cloud sprint (can be list or string)
        sprint_name = ""
        if isinstance(sprint_val, list) and sprint_val:
            sprint_name = (
                sprint_val[-1] if isinstance(sprint_val[-1], str) else str(sprint_val[-1])
            )[:80]
        elif isinstance(sprint_val, str) and sprint_val.strip():
            sprint_name = sprint_val.strip()[:80]

        tickets.append(
            {
                "key": key,
                "title": summary,
                "project": project_key,
                "status": status,
                "issuetype": issuetype,
                "month": month,
                "created": created[:10] if created else "",
                "updated": updated[:10] if updated else "",
                "resolutiondate": resolutiondate[:10] if resolutiondate else "",
                "epic_key": epic_key,
                "epic_name": epic_name,
                "epic_label": epic_label,
                "assignee_name": assignee_name,
                "assignee_display": assignee_display,
                "reporter_name": reporter_name,
                "reporter_display": reporter_display,
                "days_to_resolution": days_to_resolution,
                "days_to_grab": days_to_grab,
                "days_assigned_to_resolution": days_assigned_to_resolution,
                "days_in_review": days_in_review,
                "days_to_first_response": days_to_first_response,
                "labels": labels,
                "components": component_names,
                "priority": priority_name,
                "sprint": sprint_name,
            }
        )
    return tickets


def _enrich_jira_epic_names(client, tickets, email, api_token):
    """Resolve epic key to epic name by fetching epic issues when we only have the key (e.g. Epic Link returns key only)."""
    need = set()
    for t in tickets:
        ek = (t.get("epic_key") or "").strip()
        en = (t.get("epic_name") or "").strip()
        if ek and (not en or en == ek):
            need.add(ek)
    if not need:
        return
    try:
        issues = client.get_issues_by_keys(email, api_token, list(need))
    except Exception:
        return
    key_to_summary = {}
    for iss in issues:
        k = iss.get("key") or ""
        summary = ((iss.get("fields") or {}).get("summary") or "").strip()
        if k:
            key_to_summary[k] = summary or k
    for t in tickets:
        ek = (t.get("epic_key") or "").strip()
        if not ek:
            continue
        summary = key_to_summary.get(ek)
        if summary:
            t["epic_name"] = summary
            t["epic_label"] = summary
    return


def _is_me(ticket, field, me):
    """True if ticket's reporter or assignee matches current user (by name, key, or accountId)."""
    if not me:
        return False
    name = (ticket.get(field + "_name") or "").strip()
    display = (ticket.get(field + "_display") or "").strip()
    if not name and not display:
        return False
    return (
        name
        and (name == me.get("name") or name == me.get("key") or name == me.get("accountId"))
        or display
        and display == me.get("displayName")
    )


def _jira_metrics(jira, me=None):
    """Compute Work Wrapped metrics from Jira tickets. me = current user from Jira get_myself()."""
    if not jira:
        return {}
    total = len(jira)
    by_status = {}
    by_issuetype = {}
    by_project = {}
    by_month = {}
    by_epic = {}
    by_labels = {}
    by_components = {}
    by_priority = {}
    by_sprint = {}
    created_by_me = 0
    assigned_to_me = 0
    created_by_me_assigned_to_other = 0
    who_grabbed = {}  # assignee_display -> count (tickets I created but assigned to them)

    for t in jira:
        s = t.get("status") or "Unknown"
        by_status[s] = by_status.get(s, 0) + 1
        it = t.get("issuetype") or "Unknown"
        by_issuetype[it] = by_issuetype.get(it, 0) + 1
        p = t.get("project") or "?"
        by_project[p] = by_project.get(p, 0) + 1
        m = t.get("month") or ""
        if m:
            by_month[m] = by_month.get(m, 0) + 1
        epic_label = t.get("epic_label") or ""
        if epic_label:
            by_epic[epic_label] = by_epic.get(epic_label, 0) + 1
        for lbl in t.get("labels") or []:
            if lbl:
                by_labels[lbl] = by_labels.get(lbl, 0) + 1
        for comp in t.get("components") or []:
            if comp:
                by_components[comp] = by_components.get(comp, 0) + 1
        pri = (t.get("priority") or "").strip()
        if pri:
            by_priority[pri] = by_priority.get(pri, 0) + 1
        sprint = (t.get("sprint") or "").strip()
        if sprint:
            by_sprint[sprint] = by_sprint.get(sprint, 0) + 1
        if me:
            rep_me = _is_me(t, "reporter", me)
            ass_me = _is_me(t, "assignee", me)
            if rep_me:
                created_by_me += 1
            if ass_me:
                assigned_to_me += 1
            if rep_me and not ass_me and (t.get("assignee_display") or t.get("assignee_name")):
                created_by_me_assigned_to_other += 1
                label = t.get("assignee_display") or t.get("assignee_name") or "Unknown"
                who_grabbed[label] = who_grabbed.get(label, 0) + 1

    done_keywords = ("done", "resolved", "closed", "complete")
    done_count = sum(
        c for s, c in by_status.items() if any(k in (s or "").lower() for k in done_keywords)
    )
    open_count = total - done_count
    done_rate = round(100 * done_count / total, 1) if total else 0
    busiest_month = max(by_month.items(), key=lambda x: x[1]) if by_month else None
    top_statuses = sorted(by_status.items(), key=lambda x: -x[1])[:6]
    top_issuetypes = sorted(by_issuetype.items(), key=lambda x: -x[1])[:6]
    top_projects = sorted(by_project.items(), key=lambda x: -x[1])[:5]
    top_epics = sorted(by_epic.items(), key=lambda x: -x[1])[:8]
    top_labels = sorted(by_labels.items(), key=lambda x: -x[1])[:10]
    top_components = sorted(by_components.items(), key=lambda x: -x[1])[:10]
    top_priorities = sorted(by_priority.items(), key=lambda x: -x[1])[:8]
    top_sprints = sorted(by_sprint.items(), key=lambda x: -x[1])[:8]
    who_grabbed_list = sorted(who_grabbed.items(), key=lambda x: -x[1])

    # Timeline: (month_key, human_label, count) like Gerrit
    _month_abbr = {i: calendar.month_abbr[i] for i in range(1, 13)}
    timeline_months = []
    for m in sorted(by_month.keys()):
        parts = m.split("-")
        if len(parts) == 2:
            try:
                label = "{} {}".format(_month_abbr.get(int(parts[1]), parts[1]), parts[0])
            except (ValueError, IndexError):
                label = m
        else:
            label = m
        timeline_months.append((m, label, by_month[m]))
    timeline_max_count = max((t[2] for t in timeline_months), default=1)

    # Time metrics: resolution (created → done), assigned→resolved, grab (created → first assign), review (days in "In Review")
    resolution_days = [
        t["days_to_resolution"] for t in jira if t.get("days_to_resolution") is not None
    ]
    assigned_to_resolution_days = [
        t["days_assigned_to_resolution"]
        for t in jira
        if t.get("days_assigned_to_resolution") is not None
    ]
    grab_days = [t["days_to_grab"] for t in jira if t.get("days_to_grab") is not None]
    review_days = [t["days_in_review"] for t in jira if t.get("days_in_review") is not None]
    first_response_days = [
        t["days_to_first_response"] for t in jira if t.get("days_to_first_response") is not None
    ]
    time_buckets = [
        (0, 1, "0–1 d"),
        (1, 3, "1–3 d"),
        (3, 7, "3–7 d"),
        (7, 14, "7–14 d"),
        (14, 30, "14–30 d"),
        (30, 10**9, "30+ d"),
    ]

    def _bucket_distro(days_list):
        dist = []
        for lo, hi, label in time_buckets:
            n = sum(1 for d in days_list if lo <= d < hi)
            dist.append((label, n))
        return dist, max((c for _, c in dist), default=0)

    time_to_resolution_distribution, time_to_resolution_max = _bucket_distro(resolution_days)
    time_assigned_to_resolution_distribution, time_assigned_to_resolution_max = _bucket_distro(
        assigned_to_resolution_days
    )
    time_to_grab_distribution, time_to_grab_max = _bucket_distro(grab_days)
    time_in_review_distribution, time_in_review_max = _bucket_distro(review_days)
    time_to_first_response_distribution, time_to_first_response_max = _bucket_distro(
        first_response_days
    )

    time_to_resolution_percentiles = (
        _percentiles(resolution_days, [25, 50, 75, 90, 95, 99]) if resolution_days else {}
    )
    time_assigned_to_resolution_percentiles = (
        _percentiles(assigned_to_resolution_days, [25, 50, 75, 90, 95, 99])
        if assigned_to_resolution_days
        else {}
    )
    time_to_grab_percentiles = (
        _percentiles(grab_days, [25, 50, 75, 90, 95, 99]) if grab_days else {}
    )
    time_in_review_percentiles = (
        _percentiles(review_days, [25, 50, 75, 90, 95, 99]) if review_days else {}
    )
    time_to_first_response_percentiles = (
        _percentiles(first_response_days, [25, 50, 75, 90, 95, 99]) if first_response_days else {}
    )

    # Review summary: tickets with time in review, median/p95
    tickets_with_review_count = len(review_days)
    median_days_in_review = (
        time_in_review_percentiles.get(50) if time_in_review_percentiles else None
    )
    p95_days_in_review = time_in_review_percentiles.get(95) if time_in_review_percentiles else None
    longest_in_review = sorted(
        [
            {
                "key": t.get("key"),
                "title": (t.get("title") or "")[:80],
                "days_in_review": t.get("days_in_review"),
            }
            for t in jira
            if t.get("days_in_review") is not None
        ],
        key=lambda x: -x["days_in_review"],
    )[:5]

    # Cycle time (created → done): average and median
    avg_cycle_days = (
        round(sum(resolution_days) / len(resolution_days), 1) if resolution_days else None
    )
    median_cycle_days = (
        time_to_resolution_percentiles.get(50) if time_to_resolution_percentiles else None
    )

    # Median time to done by epic
    epic_to_days = {}
    for t in jira:
        d = t.get("days_to_resolution")
        if d is None:
            continue
        label = (t.get("epic_label") or t.get("epic_key") or "").strip() or "No epic"
        epic_to_days.setdefault(label, []).append(d)
    median_by_epic = []
    for label, days_list in epic_to_days.items():
        if days_list:
            arr = sorted(days_list)
            idx = (len(arr) - 1) * 0.5
            lo, hi = int(idx), min(int(idx) + 1, len(arr) - 1)
            frac = idx - lo
            med = arr[lo] * (1 - frac) + arr[hi] * frac
            median_by_epic.append((label, round(med, 1), len(days_list)))
    median_by_epic = sorted(median_by_epic, key=lambda x: -x[1])[:10]

    out = {
        "total_tickets": total,
        "done_count": done_count,
        "open_count": open_count,
        "done_rate_pct": done_rate,
        "by_status": by_status,
        "top_statuses": top_statuses,
        "top_issuetypes": top_issuetypes,
        "projects_count": len(by_project),
        "top_projects": top_projects,
        "top_epics": top_epics,
        "epics_count": len(by_epic),
        "top_labels": top_labels,
        "top_components": top_components,
        "top_priorities": top_priorities,
        "top_sprints": top_sprints,
        "tickets_with_review_count": tickets_with_review_count,
        "median_days_in_review": median_days_in_review,
        "p95_days_in_review": p95_days_in_review,
        "longest_in_review": longest_in_review,
        "avg_cycle_days": avg_cycle_days,
        "median_cycle_days": median_cycle_days,
        "median_time_to_done_by_epic": median_by_epic,
        "busiest_month": busiest_month[0] if busiest_month else None,
        "busiest_month_count": busiest_month[1] if busiest_month else 0,
        "by_month": by_month,
        "timeline_months": timeline_months,
        "timeline_max_count": timeline_max_count,
        "time_to_resolution_distribution": time_to_resolution_distribution,
        "time_to_resolution_distribution_max": time_to_resolution_max,
        "time_to_resolution_percentiles": time_to_resolution_percentiles,
        "time_assigned_to_resolution_distribution": time_assigned_to_resolution_distribution,
        "time_assigned_to_resolution_distribution_max": time_assigned_to_resolution_max,
        "time_assigned_to_resolution_percentiles": time_assigned_to_resolution_percentiles,
        "time_to_grab_distribution": time_to_grab_distribution,
        "time_to_grab_distribution_max": time_to_grab_max,
        "time_to_grab_percentiles": time_to_grab_percentiles,
        "time_in_review_distribution": time_in_review_distribution,
        "time_in_review_distribution_max": time_in_review_max,
        "time_in_review_percentiles": time_in_review_percentiles,
        "time_to_first_response_distribution": time_to_first_response_distribution,
        "time_to_first_response_distribution_max": time_to_first_response_max,
        "time_to_first_response_percentiles": time_to_first_response_percentiles,
    }
    if me:
        out["created_by_me"] = created_by_me
        out["assigned_to_me"] = assigned_to_me
        out["created_by_me_assigned_to_other"] = created_by_me_assigned_to_other
        out["who_grabbed"] = who_grabbed_list
    return out


def _gerrit_changes_to_commits(changes):
    """Convert Gerrit change list to our commit format (with insertions/deletions/branch/reviewers/timing)."""
    commits = []
    for ch in changes:
        created = ch.get("created", "")
        submitted = ch.get("submitted", "") or ch.get("updated", "")
        month = created[:7] if created else ""  # YYYY-MM
        subject = ch.get("subject", "")
        project = ch.get("project", "")
        status = ch.get("status", "")
        path = project
        revs = ch.get("revisions", {})
        curr_sha = ch.get("current_revision")
        if curr_sha and curr_sha in revs:
            files = revs[curr_sha].get("files", {})
            if files:
                path = list(files.keys())[0]
        path_root = (path or project or "").split("/")[0] or project or ""
        reviewers_info = ch.get("reviewers") or {}
        reviewers = []
        reviewers_cc = []
        for role, accounts in reviewers_info.items():
            if role == "REVIEWER":
                for acc in accounts or []:
                    name = (
                        acc.get("name")
                        or acc.get("username")
                        or acc.get("email")
                        or acc.get("display_name")
                        or ""
                    )
                    display = (
                        acc.get("display_name") or acc.get("name") or acc.get("username") or name
                    )
                    reviewers.append(display or name)
            elif role == "CC":
                for acc in accounts or []:
                    name = (
                        acc.get("name")
                        or acc.get("username")
                        or acc.get("email")
                        or acc.get("display_name")
                        or ""
                    )
                    display = (
                        acc.get("display_name") or acc.get("name") or acc.get("username") or name
                    )
                    reviewers_cc.append(display or name)
        commits.append(
            {
                "path": path,
                "path_root": path_root,
                "message": subject,
                "month": month,
                "project": project,
                "status": status,
                "number": ch.get("_number"),
                "insertions": ch.get("insertions") if ch.get("insertions") is not None else 0,
                "deletions": ch.get("deletions") if ch.get("deletions") is not None else 0,
                "branch": ch.get("branch", ""),
                "created": created[:10] if created else "",
                "created_raw": created,
                "submitted_raw": submitted,
                "reviewers": reviewers,
                "reviewers_cc": reviewers_cc,
            }
        )
    return commits


def _parse_gerrit_date(s):
    """
    Parse Gerrit timestamp (e.g. '2014-05-05 07:15:44.639000000').
    Python's fromisoformat only accepts up to 6 fractional digits; Gerrit uses 9. Truncate to 6.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    # Truncate fractional seconds to 6 digits so fromisoformat accepts it
    if "." in s and " " in s:
        date_part, time_part = s.split(" ", 1)
        if "." in time_part:
            base, frac = time_part.rsplit(".", 1)
            frac = (frac + "000000")[:6]  # pad or truncate to 6
            time_part = base + "." + frac
        s = date_part + "T" + time_part
    else:
        s = s.replace(" ", "T", 1)
    # Strip timezone for naive comparison (Gerrit often returns naive UTC)
    if s.endswith("Z"):
        s = s[:-1]
    for suffix in ("+00:00", "-00:00"):
        if suffix in s:
            s = s.replace(suffix, "")
            break
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _percentiles(sorted_data, percentiles):
    """
    Compute percentiles from a list of numbers (will be sorted).
    Returns dict e.g. {50: 2.5, 90: 8.0}. Uses linear interpolation.
    """
    if not sorted_data or not percentiles:
        return {}
    arr = sorted(sorted_data)
    n = len(arr)
    out = {}
    for p in percentiles:
        if p <= 0:
            out[p] = round(arr[0], 2)
        elif p >= 100:
            out[p] = round(arr[-1], 2)
        else:
            idx = (p / 100.0) * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            val = arr[lo] * (1 - frac) + arr[hi] * frac
            out[p] = round(val, 2)
    return out


def _gerrit_metrics(gerrit, reviewed_stats=None):
    """Compute Work Wrapped metrics from Gerrit changes (no LLM). reviewed_stats: optional {reviewed_count, reviewed_by_month, comments_given}."""
    if not gerrit and not reviewed_stats:
        return {}
    import calendar

    total = len(gerrit) if gerrit else 0
    by_status = {"MERGED": 0, "NEW": 0, "ABANDONED": 0}
    reviewer_counts = {}
    reviewer_cc_counts = {}
    merge_deltas = []
    merge_deltas_info = (
        []
    )  # (delta_days, {number, message, project, delta_days}) for percentile drill-down
    per_root_total = {}
    per_root_count = {}
    from datetime import datetime

    _month_abbr = {i: calendar.month_abbr[i] for i in range(1, 13)}

    for c in gerrit or []:
        s = (c.get("status") or "NEW").upper()
        by_status[s] = by_status.get(s, 0) + 1
        for name in c.get("reviewers") or []:
            if not name or (name.strip().lower() in GERRIT_EXCLUDE_REVIEWERS):
                continue
            reviewer_counts[name] = reviewer_counts.get(name, 0) + 1
        for name in c.get("reviewers_cc") or []:
            if not name or (name.strip().lower() in GERRIT_EXCLUDE_REVIEWERS):
                continue
            reviewer_cc_counts[name] = reviewer_cc_counts.get(name, 0) + 1
        if s == "MERGED":
            created_raw = c.get("created_raw") or ""
            submitted_raw = c.get("submitted_raw") or ""
            if created_raw and submitted_raw:
                t_created = _parse_gerrit_date(created_raw)
                t_sub = _parse_gerrit_date(submitted_raw)
                if t_created is not None and t_sub is not None:
                    delta_days = (t_sub - t_created).total_seconds() / 86400.0
                    if delta_days >= 0:
                        merge_deltas.append(delta_days)
                        merge_deltas_info.append(
                            (
                                delta_days,
                                {
                                    "number": c.get("number"),
                                    "message": (c.get("message") or "")[:120],
                                    "project": c.get("project") or "",
                                    "delta_days": round(delta_days, 2),
                                },
                            )
                        )
                        root = c.get("path_root") or "root"
                        per_root_total[root] = per_root_total.get(root, 0.0) + delta_days
                        per_root_count[root] = per_root_count.get(root, 0) + 1
    insertions = sum(c.get("insertions") or 0 for c in (gerrit or []))
    deletions = sum(c.get("deletions") or 0 for c in (gerrit or []))
    projects = {c.get("project") for c in (gerrit or []) if c.get("project")}
    by_month = {}
    for c in gerrit or []:
        m = c.get("month") or ""
        if m:
            by_month[m] = by_month.get(m, 0) + 1
    busiest_month = max(by_month.items(), key=lambda x: x[1]) if by_month else None
    # Timeline: (month_key, human_label, count) for display, e.g. ("2025-03", "Mar 2025", 17)
    timeline_months = []
    for m in sorted(by_month.keys()):
        parts = m.split("-")
        if len(parts) == 2:
            try:
                label = "{} {}".format(_month_abbr.get(int(parts[1]), parts[1]), parts[0])
            except (ValueError, IndexError):
                label = m
        else:
            label = m
        timeline_months.append((m, label, by_month[m]))
    timeline_max_count = max((t[2] for t in timeline_months), default=1)
    by_branch = {}
    for c in gerrit or []:
        b = c.get("branch") or "unknown"
        by_branch[b] = by_branch.get(b, 0) + 1
    top_branches = sorted(by_branch.items(), key=lambda x: -x[1])[:5]
    avg_merge_days = sum(merge_deltas) / len(merge_deltas) if merge_deltas else None
    # Percentiles of time to merge (creation → submitted), in days
    merge_time_percentiles = (
        _percentiles(merge_deltas, [25, 50, 75, 90, 95, 99]) if merge_deltas else {}
    )
    # Patches at or above p95 / p99 (for dropdown drill-down)
    p95_val = merge_time_percentiles.get(95)
    p99_val = merge_time_percentiles.get(99)
    patches_at_or_above_p95 = (
        sorted(
            [info for d, info in merge_deltas_info if p95_val is not None and d >= p95_val],
            key=lambda x: -x["delta_days"],
        )
        if merge_deltas_info and p95_val is not None
        else []
    )
    patches_at_or_above_p99 = (
        sorted(
            [info for d, info in merge_deltas_info if p99_val is not None and d >= p99_val],
            key=lambda x: -x["delta_days"],
        )
        if merge_deltas_info and p99_val is not None
        else []
    )
    # Distribution of time-to-merge (buckets for line/bar chart)
    merge_time_buckets = [
        (0, 1, "0–1 d"),
        (1, 3, "1–3 d"),
        (3, 7, "3–7 d"),
        (7, 14, "7–14 d"),
        (14, 30, "14–30 d"),
        (30, 10**9, "30+ d"),
    ]
    merge_time_distribution = []
    for lo, hi, label in merge_time_buckets:
        n = sum(1 for d in merge_deltas if lo <= d < hi)
        merge_time_distribution.append((label, n))
    merge_time_distribution_max = max((c for _, c in merge_time_distribution), default=0)
    # Reviewers and CC combined: (name, as_reviewer, as_cc), sorted by total
    all_reviewer_names = set(reviewer_counts) | set(reviewer_cc_counts)
    reviewers_with_cc = []
    for name in all_reviewer_names:
        r = reviewer_counts.get(name, 0)
        cc = reviewer_cc_counts.get(name, 0)
        reviewers_with_cc.append((name, r, cc))
    reviewers_with_cc = sorted(reviewers_with_cc, key=lambda x: -(x[1] + x[2]))
    per_root_merge = []
    for root, tot in per_root_total.items():
        count = per_root_count.get(root, 0) or 1
        per_root_merge.append((root, round(tot / count, 2), count))
    per_root_merge = sorted(per_root_merge, key=lambda x: -x[1])[:5]
    top_reviewers = sorted(reviewer_counts.items(), key=lambda x: -x[1])[:5]
    top_reviewers_cc = sorted(reviewer_cc_counts.items(), key=lambda x: -x[1])[:5]

    # Lines changed distribution (small / medium / large per change)
    lines_buckets = [(0, 51, "0–50"), (51, 201, "51–200"), (201, 10**9, "200+")]
    lines_changed_distribution = []
    for lo, hi, label in lines_buckets:
        n = sum(
            1
            for c in (gerrit or [])
            if lo <= (c.get("insertions") or 0) + (c.get("deletions") or 0) < hi
        )
        lines_changed_distribution.append((label, n))
    lines_changed_distribution_max = max((c for _, c in lines_changed_distribution), default=0)

    return {
        "total_changes": total,
        "by_status": by_status,
        "merged_count": by_status.get("MERGED", 0),
        "open_count": by_status.get("NEW", 0),
        "abandoned_count": by_status.get("ABANDONED", 0),
        "merge_rate_pct": round(100 * by_status.get("MERGED", 0) / total, 1) if total else 0,
        "lines_added": insertions,
        "lines_removed": deletions,
        "projects_count": len(projects),
        "busiest_month": busiest_month[0] if busiest_month else None,
        "busiest_month_count": busiest_month[1] if busiest_month else 0,
        "by_month": by_month,
        "timeline_months": timeline_months,
        "timeline_max_count": timeline_max_count,
        "top_branches": top_branches,
        "avg_merge_days": round(avg_merge_days, 2) if avg_merge_days is not None else None,
        "merge_time_percentiles": merge_time_percentiles,
        "patches_at_or_above_p95": patches_at_or_above_p95,
        "patches_at_or_above_p99": patches_at_or_above_p99,
        "merge_time_distribution": merge_time_distribution,
        "merge_time_distribution_max": merge_time_distribution_max,
        "reviewers_with_cc": reviewers_with_cc,
        "per_root_merge": per_root_merge,
        "top_reviewers": top_reviewers,
        "top_reviewers_cc": top_reviewers_cc,
        "lines_changed_distribution": lines_changed_distribution,
        "lines_changed_distribution_max": lines_changed_distribution_max,
    }
    if reviewed_stats:
        out["reviewed_count"] = reviewed_stats.get("reviewed_count", 0)
        rbm = reviewed_stats.get("reviewed_by_month") or {}
        out["reviewed_by_month"] = rbm
        out["reviewed_by_month_list"] = sorted(rbm.items(), key=lambda x: x[0])
        out["reviewed_by_month_max"] = max(rbm.values(), default=1)
        out["comments_given"] = reviewed_stats.get("comments_given", 0)


def _confluence_pages_to_list(pages, base_url):
    """Convert Confluence API content items to our page list (title, space, updated, month, link)."""
    out = []
    for p in pages:
        title = (p.get("title") or "").strip()
        space_obj = p.get("space") or {}
        space_key = space_obj.get("key") or ""
        space_name = space_obj.get("name") or space_key or "?"
        when = ""
        hist = p.get("history") or {}
        if isinstance(hist, dict):
            lu = hist.get("lastUpdated") or {}
            when = (lu.get("when") or "")[:19]
        if not when:
            ver = p.get("version") or {}
            if isinstance(ver, dict):
                when = (ver.get("when") or "")[:19]
        month = when[:7] if len(when) >= 7 else ""
        ver = p.get("version") or {}
        version_number = ver.get("number") if isinstance(ver, dict) else None
        if version_number is not None and not isinstance(version_number, int):
            try:
                version_number = int(version_number)
            except (TypeError, ValueError):
                version_number = None
        link = base_url or ""
        links = p.get("_links") or {}
        webui = links.get("webui") or links.get("base") or ""
        if webui:
            if webui.startswith("http://") or webui.startswith("https://"):
                link = webui
            elif base_url:
                link = base_url.rstrip("/") + "/" + webui.lstrip("/")
            else:
                link = webui
        out.append(
            {
                "id": p.get("id") or "",
                "title": title,
                "space_key": space_key,
                "space": space_name,
                "updated": when[:10] if len(when) >= 10 else "",
                "month": month,
                "link": link,
                "version_number": version_number,
            }
        )
    return out


def _fetch_gerrit(session_data, months):
    """Fetch Gerrit changes, reviewer comment counts, and (optionally) changes I reviewed + comments I wrote.
    Returns (gerrit_list, reviewer_comment_counts, error_str, reviewed_stats). reviewed_stats: {reviewed_count, reviewed_by_month, comments_given}.
    """
    if not GERRIT_URL:
        return [], {}, "Gerrit is not configured.", {}
    if not session_data.get("gerrit_username") or not session_data.get("gerrit_password"):
        return [], {}, None, {}
    try:
        client = get_gerrit_client()
        changes = client.get_my_changes(
            session_data["gerrit_username"],
            session_data["gerrit_password"],
            months=months,
        )
        gerrit = _gerrit_changes_to_commits(changes)
        reviewer_comment_counts = {}
        # Fetch comment counts on my changes (comments I received) - parallel, 25 changes
        changes_to_fetch = changes[:25]

        def _comments_for_change(ch):
            change_id = ch.get("id") or ch.get("_number")
            if not change_id:
                return []
            try:
                return client.get_change_comments(
                    change_id,
                    session_data["gerrit_username"],
                    session_data["gerrit_password"],
                )
            except GerritError:
                return []

        with ThreadPoolExecutor(max_workers=10) as ex:
            for comments in ex.map(_comments_for_change, changes_to_fetch):
                for c in comments:
                    author = c.get("author") or {}
                    name = (
                        author.get("name") or author.get("username") or author.get("email") or ""
                    ).strip()
                    if not name or name.lower() in GERRIT_EXCLUDE_REVIEWERS:
                        continue
                    reviewer_comment_counts[name] = reviewer_comment_counts.get(name, 0) + 1

        # Changes where I'm reviewer: for review velocity and "comments I wrote"
        reviewed_stats = {"reviewed_count": 0, "reviewed_by_month": {}, "comments_given": 0}
        try:
            reviewed_changes = client.get_changes_reviewed(
                session_data["gerrit_username"],
                session_data["gerrit_password"],
                months=months,
                limit=200,
            )
        except GerritError:
            reviewed_changes = []
        for ch in reviewed_changes:
            reviewed_stats["reviewed_count"] += 1
            created = (ch.get("created") or "")[:7]
            if created:
                reviewed_stats["reviewed_by_month"][created] = (
                    reviewed_stats["reviewed_by_month"].get(created, 0) + 1
                )
        # Comments I wrote: fetch comments on first 20 reviewed changes, count where author is me
        me_identifiers = set()
        for key in ("gerrit_username", "gerrit_email", "user_name"):
            v = (session_data.get(key) or "").strip().lower()
            if v:
                me_identifiers.add(v)
        if me_identifiers and reviewed_changes:

            def _my_comments_on_change(ch):
                change_id = ch.get("id") or ch.get("_number")
                if not change_id:
                    return 0
                try:
                    comments = client.get_change_comments(
                        change_id,
                        session_data["gerrit_username"],
                        session_data["gerrit_password"],
                    )
                except GerritError:
                    return 0
                n = 0
                for c in comments:
                    author = c.get("author") or {}
                    for field in ("username", "name", "email"):
                        val = (author.get(field) or "").strip().lower()
                        if val and val in me_identifiers:
                            n += 1
                            break
                return n

            with ThreadPoolExecutor(max_workers=8) as ex:
                for count in ex.map(_my_comments_on_change, reviewed_changes[:20]):
                    reviewed_stats["comments_given"] += count
        return gerrit, reviewer_comment_counts, None, reviewed_stats
    except GerritError as e:
        return [], {}, str(e), {}


def _fetch_jira(session_data, months):
    """Fetch Jira issues and current user. Returns (jira_list, jira_me, error_str)."""
    if not JIRA_URL or not session_data.get("jira_email") or not session_data.get("jira_api_token"):
        return [], None, None
    try:
        client = get_jira_client()
        issues = client.search_my_issues(
            session_data["jira_email"],
            session_data["jira_api_token"],
            months=months,
            max_results=500,
        )
        jira = _jira_issues_to_tickets(issues)
        _enrich_jira_epic_names(
            client, jira, session_data["jira_email"], session_data["jira_api_token"]
        )
        jira_me = None
        try:
            jira_me = client.get_myself(
                session_data["jira_email"],
                session_data["jira_api_token"],
            )
        except JiraError:
            pass
        return jira, jira_me, None
    except JiraError as e:
        return [], None, str(e)


def _fetch_confluence(session_data, months):
    """Fetch Confluence pages. Returns (confluence_list, error_str)."""
    confluence_connected = bool(
        CONFLUENCE_URL
        and (
            (session_data.get("confluence_email") and session_data.get("confluence_api_token"))
            or (session_data.get("jira_email") and session_data.get("jira_api_token"))
        )
    )
    if not confluence_connected:
        return [], None
    cf_email = session_data.get("confluence_email") or session_data.get("jira_email")
    cf_token = session_data.get("confluence_api_token") or session_data.get("jira_api_token")
    try:
        client = get_confluence_client()
        raw_pages = client.search_my_pages(cf_email, cf_token, months=months, max_results=200)
        return _confluence_pages_to_list(raw_pages, CONFLUENCE_URL), None
    except ConfluenceError as e:
        return [], str(e)


def _fetch_confluence_created(session_data, months):
    """Fetch Confluence page IDs created by me in the last N months. Returns (list of content dicts with id, error_str)."""
    confluence_connected = bool(
        CONFLUENCE_URL
        and (
            (session_data.get("confluence_email") and session_data.get("confluence_api_token"))
            or (session_data.get("jira_email") and session_data.get("jira_api_token"))
        )
    )
    if not confluence_connected:
        return [], None
    cf_email = session_data.get("confluence_email") or session_data.get("jira_email")
    cf_token = session_data.get("confluence_api_token") or session_data.get("jira_api_token")
    try:
        client = get_confluence_client()
        raw = client.search_my_pages_created(cf_email, cf_token, months=months, max_results=500)
        return raw, None
    except ConfluenceError:
        return [], None


def _fetch_slack(session_data, months):
    """Fetch Slack messages. Returns (slack_list, error_str)."""
    if not session_data.get("slack_token"):
        return [], None
    try:
        client = get_slack_client()
        slack = client.get_my_messages(
            session_data["slack_token"],
            months=months,
            max_messages=500,
            max_channels=40,
        )
        return slack, None
    except SlackError as e:
        return [], str(e)


# In-memory cache: (user_id, months) -> personal summary dict. Cleared on logout.
_personal_summary_cache = {}


def get_personal_summary(session_data):
    """
    Get personal view for the logged-in user.
    Uses session_data.get("months", DEFAULT_MONTHS) for the time range.
    Fetches Gerrit, Jira, Confluence, Slack in parallel only on cache miss; otherwise returns cached data.
    """
    months = session_data.get("months", DEFAULT_MONTHS)
    if months not in VALID_MONTHS:
        months = DEFAULT_MONTHS
    cache_key = (session_data.get("user_id"), months)
    if cache_key in _personal_summary_cache:
        return _personal_summary_cache[cache_key]

    time_range_label = next(
        (label for m, label in TIME_RANGE_OPTIONS if m == months), "Last 12 months"
    )

    user = {
        "id": session_data.get("user_id"),
        "name": session_data.get("user_name", "Unknown"),
        "email": session_data.get("user_email", ""),
        "team": "",  # Not from Gerrit; could add later
    }

    gerrit = []
    jira = []
    confluence = []
    slack = []
    gerrit_error = None
    jira_error = None
    confluence_error = None
    slack_error = None
    reviewer_comment_counts = {}
    jira_me = None
    jira_connected = bool(
        JIRA_URL and session_data.get("jira_email") and session_data.get("jira_api_token")
    )
    confluence_connected = bool(
        CONFLUENCE_URL
        and (
            (session_data.get("confluence_email") and session_data.get("confluence_api_token"))
            or (session_data.get("jira_email") and session_data.get("jira_api_token"))
        )
    )
    slack_connected = bool(session_data.get("slack_token"))

    # Fetch all sources in parallel (including Confluence "created" for metrics)
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut_gerrit = ex.submit(_fetch_gerrit, session_data, months)
        fut_jira = ex.submit(_fetch_jira, session_data, months)
        fut_confluence = ex.submit(_fetch_confluence, session_data, months)
        fut_confluence_created = ex.submit(_fetch_confluence_created, session_data, months)
        fut_slack = ex.submit(_fetch_slack, session_data, months)
        gerrit, reviewer_comment_counts, gerrit_error, gerrit_reviewed_stats = fut_gerrit.result()
        jira, jira_me, jira_error = fut_jira.result()
        confluence, confluence_error = fut_confluence.result()
        confluence_created, _ = fut_confluence_created.result()
        slack, slack_error = fut_slack.result()

    # Themes: Gerrit projects + Jira projects + Confluence spaces + Slack channels
    themes = {}
    for c in gerrit:
        proj = c.get("project", "Other")
        themes[proj] = themes.get(proj, 0) + 1
    for t in jira:
        proj = t.get("project", "Other")
        themes[proj] = themes.get(proj, 0) + 1
    for p in confluence:
        space = p.get("space") or p.get("space_key") or "Other"
        themes[space] = themes.get(space, 0) + 1
    for s in slack:
        ch = s.get("channel_name") or s.get("channel_id") or "Other"
        themes[ch] = themes.get(ch, 0) + 1

    all_months = sorted(
        set(c.get("month", "") for c in gerrit if c.get("month"))
        | set(t.get("month", "") for t in jira if t.get("month"))
        | set(p.get("month", "") for p in confluence if p.get("month"))
        | set(s.get("month", "") for s in slack if s.get("month"))
    )
    monthly = []
    for m in all_months:
        monthly.append(
            {
                "month": m,
                "jira_count": len([t for t in jira if t.get("month") == m]),
                "gerrit_count": len([c for c in gerrit if c.get("month") == m]),
                "confluence_count": len([p for p in confluence if p.get("month") == m]),
                "slack_count": len([s for s in slack if s.get("month") == m]),
            }
        )

    gerrit_metrics = (
        _gerrit_metrics(gerrit, reviewed_stats=gerrit_reviewed_stats)
        if gerrit
        else (
            _gerrit_metrics([], reviewed_stats=gerrit_reviewed_stats)
            if gerrit_reviewed_stats
            else {}
        )
    )
    if not gerrit and gerrit_reviewed_stats:
        pass  # metrics already have reviewed_stats
    gerrit_metrics["reviewer_comment_counts"] = reviewer_comment_counts
    if gerrit_reviewed_stats:
        gerrit_metrics["reviewed_count"] = gerrit_reviewed_stats.get("reviewed_count", 0)
        gerrit_metrics["reviewed_by_month"] = gerrit_reviewed_stats.get("reviewed_by_month") or {}
        gerrit_metrics["comments_given"] = gerrit_reviewed_stats.get("comments_given", 0)
    comments_received_total = (
        sum(reviewer_comment_counts.values()) if reviewer_comment_counts else 0
    )
    gerrit_metrics["comments_received_total"] = comments_received_total
    if gerrit_metrics.get("comments_given") is not None or comments_received_total:
        given = gerrit_metrics.get("comments_given") or 0
        gerrit_metrics["review_balance_note"] = (
            "Comments received on your patches: {} · Comments you wrote as reviewer: {}".format(
                comments_received_total, given
            )
        )
    jira_metrics = _jira_metrics(jira, jira_me) if jira else {}

    # Confluence metrics: created vs updated, top spaces, last updated by month, by space over time, most edited
    confluence_metrics = {}
    if confluence is not None:
        by_space = {}
        by_month_cf = {}
        by_space_month = {}  # (space, month) -> count
        for p in confluence:
            space = p.get("space") or p.get("space_key") or "?"
            by_space[space] = by_space.get(space, 0) + 1
            m = p.get("month") or ""
            if m:
                by_month_cf[m] = by_month_cf.get(m, 0) + 1
                key = (space, m)
                by_space_month[key] = by_space_month.get(key, 0) + 1
        confluence_metrics["created_count"] = (
            len([c for c in confluence_created if c.get("id")]) if confluence_created else 0
        )
        confluence_metrics["updated_count"] = len(confluence)
        confluence_metrics["top_spaces"] = sorted(by_space.items(), key=lambda x: -x[1])[:10]
        lum = sorted(by_month_cf.items(), key=lambda x: x[0])
        confluence_metrics["last_updated_by_month"] = lum
        confluence_metrics["last_updated_by_month_max"] = max(by_month_cf.values(), default=1)
        # Pages by space over time: list of (space, month, count) sorted by space then month
        space_month_list = [
            (space, month, count) for (space, month), count in by_space_month.items()
        ]
        confluence_metrics["by_space_month"] = sorted(space_month_list, key=lambda x: (x[0], x[1]))
        confluence_metrics["by_space_month_max"] = max(
            (c for _, _, c in space_month_list), default=1
        )
        # Most edited pages (by version number)
        most_edited = sorted(
            [p for p in confluence if p.get("version_number") is not None],
            key=lambda x: -x["version_number"],
        )[:10]
        confluence_metrics["most_edited_pages"] = [
            {
                "title": p.get("title"),
                "space": p.get("space") or p.get("space_key"),
                "version_number": p.get("version_number"),
                "link": p.get("link"),
            }
            for p in most_edited
        ]
        confluence_metrics["llm_categories"] = []
        confluence_metrics["llm_summary"] = ""
        if categorize_confluence_titles and confluence:
            titles = [p.get("title") for p in confluence if p.get("title")]
            if titles:
                llm_out = categorize_confluence_titles(titles, max_items=200)
                if isinstance(llm_out, dict):
                    confluence_metrics["llm_categories"] = llm_out.get("categories") or []
                    confluence_metrics["llm_summary"] = llm_out.get("summary") or ""

    # Slack metrics: by channel, by hour/weekday (peak), thread vs single, reactions
    slack_metrics = {}
    if slack is not None:
        by_channel = {}
        by_month_slack = {}
        by_hour = {i: 0 for i in range(24)}
        by_weekday = {i: 0 for i in range(7)}  # 0=Mon .. 6=Sun
        thread_reply_count = 0
        top_level_count = 0
        total_reactions = 0
        for s in slack:
            ch = s.get("channel_name") or s.get("channel_id") or "?"
            by_channel[ch] = by_channel.get(ch, 0) + 1
            m = s.get("month") or ""
            if m:
                by_month_slack[m] = by_month_slack.get(m, 0) + 1
            if s.get("is_thread_reply"):
                thread_reply_count += 1
            else:
                top_level_count += 1
            h = s.get("hour")
            if h is not None and 0 <= h < 24:
                by_hour[h] = by_hour.get(h, 0) + 1
            wd = s.get("weekday")
            if wd is not None and 0 <= wd < 7:
                by_weekday[wd] = by_weekday.get(wd, 0) + 1
            total_reactions += s.get("reaction_count") or 0
        slack_metrics["by_channel"] = by_channel
        top_ch = sorted(by_channel.items(), key=lambda x: -x[1])[:10]
        slack_metrics["top_channels"] = top_ch
        slack_metrics["top_channels_max"] = max(by_channel.values(), default=1)
        mbm = sorted(by_month_slack.items(), key=lambda x: x[0])
        slack_metrics["messages_by_month"] = mbm
        slack_metrics["messages_by_month_max"] = max(by_month_slack.values(), default=1)
        slack_metrics["by_hour"] = by_hour
        slack_metrics["by_weekday"] = by_weekday
        slack_metrics["peak_hour"] = (
            max(by_hour.items(), key=lambda x: x[1])[0] if by_hour else None
        )
        slack_metrics["peak_weekday"] = (
            max(by_weekday.items(), key=lambda x: x[1])[0] if by_weekday else None
        )
        slack_metrics["thread_reply_count"] = thread_reply_count
        slack_metrics["top_level_count"] = top_level_count
        slack_metrics["total_reactions"] = total_reactions
        _weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        slack_metrics["weekday_names"] = _weekday_names

    # Period vs period: last 6 months vs previous 6 months (when we have at least 12 months of data)
    period_comparison = None
    sorted_months = sorted(monthly, key=lambda x: x["month"], reverse=True) if monthly else []
    if len(sorted_months) >= 12:
        current_6 = sorted_months[:6]
        previous_6 = sorted_months[6:12]
        period_comparison = {
            "current_6m": {
                "jira": sum(m.get("jira_count") or 0 for m in current_6),
                "gerrit": sum(m.get("gerrit_count") or 0 for m in current_6),
                "confluence": sum(m.get("confluence_count") or 0 for m in current_6),
                "slack": sum(m.get("slack_count") or 0 for m in current_6),
            },
            "previous_6m": {
                "jira": sum(m.get("jira_count") or 0 for m in previous_6),
                "gerrit": sum(m.get("gerrit_count") or 0 for m in previous_6),
                "confluence": sum(m.get("confluence_count") or 0 for m in previous_6),
                "slack": sum(m.get("slack_count") or 0 for m in previous_6),
            },
        }
    # Month-over-month: last month vs second-to-last month
    month_over_month = None
    if len(sorted_months) >= 2:
        m1, m2 = sorted_months[0], sorted_months[1]
        month_over_month = {
            "last_month": m1["month"],
            "previous_month": m2["month"],
            "last": {
                "jira": m1.get("jira_count") or 0,
                "gerrit": m1.get("gerrit_count") or 0,
                "confluence": m1.get("confluence_count") or 0,
                "slack": m1.get("slack_count") or 0,
            },
            "previous": {
                "jira": m2.get("jira_count") or 0,
                "gerrit": m2.get("gerrit_count") or 0,
                "confluence": m2.get("confluence_count") or 0,
                "slack": m2.get("slack_count") or 0,
            },
        }

    totals = {
        "jira": len(jira),
        "gerrit": len(gerrit),
        "confluence": len(confluence),
        "slack": len(slack),
    }
    user_id = session_data.get("user_id")
    goals = get_goals(user_id)
    goals_progress = {}
    if goals:
        goals_progress = {
            "tickets_done": {
                "current": totals["jira"],
                "goal": goals.get("tickets_done"),
                "label": "Tickets done",
            },
            "reviews": {
                "current": totals["gerrit"],
                "goal": goals.get("reviews"),
                "label": "Changes merged",
            },
            "messages": {
                "current": totals["slack"],
                "goal": goals.get("messages"),
                "label": "Slack messages",
            },
        }
    team_optin = get_team_optin(user_id)
    team_comparison = None
    if team_optin:
        update_team_metrics(user_id, totals)
        team_avg = get_team_average()
        if team_avg and team_avg.get("participant_count", 0) > 0:
            team_comparison = {
                "your_totals": totals,
                "team_average": team_avg["average"],
                "participant_count": team_avg["participant_count"],
            }
    snapshots = get_snapshots(user_id)

    # Rule-based highlights (3–5 talking points for 1:1)
    highlights = []
    if period_comparison:
        c6 = period_comparison.get("current_6m") or {}
        p6 = period_comparison.get("previous_6m") or {}
        jc, jp = c6.get("jira", 0), p6.get("jira", 0)
        gc, gp = c6.get("gerrit", 0), p6.get("gerrit", 0)
        if (jc + gc) > 0 and (jp + gp) > 0:
            delta = (jc + gc) - (jp + gp)
            pct = round(100 * delta / (jp + gp)) if (jp + gp) else 0
            if pct > 0:
                highlights.append(
                    "{}% more tickets and changes in the last 6 months than the previous 6.".format(
                        pct
                    )
                )
            elif pct < 0:
                highlights.append(
                    "{}% fewer tickets and changes in the last 6 months than the previous 6.".format(
                        abs(pct)
                    )
                )
    if themes:
        top = sorted(themes.items(), key=lambda x: -x[1])[:1]
        if top:
            name, count = top[0]
            highlights.append("Top area: {} ({} tickets/changes/pages).".format(name, count))
    if jira_metrics and jira_metrics.get("time_to_first_response_percentiles"):
        med = jira_metrics.get("time_to_first_response_percentiles", {}).get(50)
        if med is not None:
            if med == 0 or (isinstance(med, (int, float)) and med < 0.5):
                highlights.append("Median under 1 day to first response on Jira tickets.")
            else:
                highlights.append("Median {} days to first response on Jira tickets.".format(med))
    if (
        gerrit_metrics
        and gerrit_metrics.get("merge_rate_pct") is not None
        and gerrit_metrics.get("merged_count", 0) > 0
    ):
        highlights.append(
            "{} changes merged ({}% merge rate).".format(
                gerrit_metrics.get("merged_count"), gerrit_metrics.get("merge_rate_pct")
            )
        )
    if (
        jira_metrics
        and jira_metrics.get("done_count") is not None
        and jira_metrics.get("done_count", 0) > 0
    ):
        highlights.append(
            "{} Jira tickets done ({}% done rate).".format(
                jira_metrics.get("done_count"), jira_metrics.get("done_rate_pct", 0)
            )
        )
    highlights = highlights[:5]

    # Nudges: stale Gerrit, set goal
    nudges = []
    open_gerrit = [c for c in (gerrit or []) if (c.get("status") or "").upper() == "NEW"]
    open_count = len(open_gerrit)
    stale_count = 0
    if open_gerrit:
        now = datetime.utcnow()
        for c in open_gerrit:
            raw = c.get("created_raw") or c.get("created") or ""
            if not raw:
                continue
            t = _parse_gerrit_date(raw)
            if t is None:
                try:
                    t = datetime.strptime((raw[:10] or ""), "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
            if (now - t).days >= 14:
                stale_count += 1
        if open_count > 0:
            if stale_count > 0:
                nudges.append(
                    {
                        "id": "stale_gerrit",
                        "message": "You have {} open Gerrit change{} — {} older than 14 days.".format(
                            open_count, "s" if open_count != 1 else "", stale_count
                        ),
                    }
                )
            else:
                nudges.append(
                    {
                        "id": "open_gerrit",
                        "message": "You have {} open Gerrit change{}.".format(
                            open_count, "s" if open_count != 1 else ""
                        ),
                    }
                )
    if not goals or not any(goals.get(k) for k in ("tickets_done", "reviews", "messages")):
        nudges.append(
            {
                "id": "set_goal",
                "message": "Set a goal to track progress (e.g. tickets done, reviews).",
            }
        )

    result = {
        "user": user,
        "jira": jira,
        "gerrit": gerrit,
        "confluence": confluence,
        "slack": slack,
        "monthly": monthly,
        "themes": [{"name": k, "count": v} for k, v in sorted(themes.items(), key=lambda x: -x[1])],
        "totals": totals,
        "goals": goals,
        "goals_progress": goals_progress,
        "team_optin": team_optin,
        "team_comparison": team_comparison,
        "snapshots": snapshots,
        "highlights": highlights,
        "nudges": nudges,
        "gerrit_error": gerrit_error,
        "jira_error": jira_error,
        "confluence_error": confluence_error,
        "slack_error": slack_error,
        "jira_connected": jira_connected,
        "confluence_connected": confluence_connected,
        "slack_connected": slack_connected,
        "gerrit_metrics": gerrit_metrics,
        "jira_metrics": jira_metrics,
        "confluence_metrics": confluence_metrics,
        "slack_metrics": slack_metrics,
        "period_comparison": period_comparison,
        "month_over_month": month_over_month,
        "months": months,
        "time_range_label": time_range_label,
        "time_range_options": TIME_RANGE_OPTIONS,
        "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _personal_summary_cache[cache_key] = result
    return result


def get_team_summary(team_name=None):
    """Team-level view. With Gerrit-only, shows placeholder (team aggregation needs more sources)."""
    return {
        "team": team_name or "All",
        "users": [],
        "themes": [],
        "monthly": [],
        "totals": {"jira": 0, "gerrit": 0, "confluence": 0, "slack": 0},
        "highlights": [
            "Team view aggregates data from multiple users.",
            "Connect Jira, Confluence, Slack for full team insights.",
        ],
    }


# --- Routes ---


def _apply_time_range_from_query(request: Request):
    """If request has ?months= in VALID_MONTHS, set session and return True."""
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
        return True
    return False


@app.get("/login", name="login")
async def login_get(request: Request):
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    ctx = _template_context(request, error=None, gerrit_configured=bool(GERRIT_URL),
                            jira_configured=bool(JIRA_URL), confluence_configured=bool(CONFLUENCE_URL))
    return templates.TemplateResponse("login.html", ctx)


@app.post("/login")
async def login_post(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    jira_email: str = Form(""),
    jira_api_token: str = Form(""),
    confluence_email: str = Form(""),
    confluence_api_token: str = Form(""),
    slack_token: str = Form(""),
):
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    error = None
    email = (email or "").strip()
    if not GERRIT_URL:
        error = "Gerrit is not configured. Set GERRIT_URL environment variable."
    elif not email or not password:
        error = "Email/username and password are required."
    else:
        try:
            client = get_gerrit_client()
            account = client.authenticate(email.strip(), password)
            request.session["user_id"] = str(account.get("_account_id", account.get("username", email)))
            request.session["user_name"] = account.get("name") or account.get("username") or email
            request.session["user_email"] = account.get("email") or email
            request.session["gerrit_username"] = email
            request.session["gerrit_password"] = password
            if JIRA_URL and (jira_email or "").strip() and jira_api_token:
                request.session["jira_email"] = (jira_email or "").strip()
                request.session["jira_api_token"] = jira_api_token
            if CONFLUENCE_URL and ((confluence_email or "").strip() and confluence_api_token or (jira_email and jira_api_token)):
                request.session["confluence_email"] = (confluence_email or "").strip() or (jira_email or "").strip()
                request.session["confluence_api_token"] = confluence_api_token or jira_api_token
            if (slack_token or "").strip():
                request.session["slack_token"] = (slack_token or "").strip()
            next_url = request.query_params.get("next") or request.app.url_path_for("index")
            return RedirectResponse(url=next_url, status_code=303)
        except GerritError as e:
            error = str(e)
    ctx = _template_context(request, error=error, gerrit_configured=bool(GERRIT_URL),
                            jira_configured=bool(JIRA_URL), confluence_configured=bool(CONFLUENCE_URL))
    return templates.TemplateResponse("login.html", ctx)


@app.get("/logout", name="logout")
async def logout(request: Request):
    user_id = request.session.get("user_id")
    request.session.clear()
    if user_id is not None:
        to_drop = [k for k in _personal_summary_cache if k[0] == user_id]
        for k in to_drop:
            del _personal_summary_cache[k]
    return RedirectResponse(url=request.app.url_path_for("login"), status_code=303)


@app.get("/", name="index")
async def index(request: Request, session: dict = Depends(require_session)):
    current_user = {
        "id": session.get("user_id"),
        "name": session.get("user_name"),
        "email": session.get("user_email"),
        "team": "",
    }
    ctx = _template_context(request, current_route="index", current_user=current_user)
    return templates.TemplateResponse("index.html", ctx)


@app.get("/gerrit", name="gerrit_full")
async def gerrit_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="gerrit_full",
        gerrit=data["gerrit"], gerrit_error=data.get("gerrit_error"),
        gerrit_metrics=data.get("gerrit_metrics") or {}, totals=data.get("totals") or {},
        monthly=data.get("monthly") or [], months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("gerrit_full.html", ctx)


@app.get("/jira", name="jira_full")
async def jira_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="jira_full",
        jira=data["jira"], jira_error=data.get("jira_error"), jira_connected=data.get("jira_connected"),
        jira_metrics=data.get("jira_metrics") or {}, totals=data.get("totals") or {},
        monthly=data.get("monthly") or [], months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path, jira_url=JIRA_URL or "",
    )
    return templates.TemplateResponse("jira_full.html", ctx)


@app.get("/confluence", name="confluence_full")
async def confluence_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="confluence_full",
        confluence=data["confluence"], confluence_error=data.get("confluence_error"),
        confluence_connected=data.get("confluence_connected"), confluence_metrics=data.get("confluence_metrics") or {},
        totals=data.get("totals") or {}, monthly=data.get("monthly") or [], months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS), time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("confluence_full.html", ctx)


@app.get("/slack", name="slack_full")
async def slack_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="slack_full",
        slack=data["slack"], slack_error=data.get("slack_error"), slack_connected=data.get("slack_connected"),
        slack_metrics=data.get("slack_metrics") or {}, totals=data.get("totals") or {}, monthly=data.get("monthly") or [],
        months=data.get("months", DEFAULT_MONTHS), time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS), time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("slack_full.html", ctx)


@app.get("/outlook", name="outlook_full")
async def outlook_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="outlook_full",
        months=data.get("months", DEFAULT_MONTHS), time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS), time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("outlook_full.html", ctx)


@app.get("/teams", name="teams_full")
async def teams_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request, current_route="teams_full",
        months=data.get("months", DEFAULT_MONTHS), time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS), time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("teams_full.html", ctx)


@app.get("/api/personal")
async def api_personal(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    if request.query_params.get("refresh"):
        uid = session.get("user_id")
        months = session.get("months", DEFAULT_MONTHS)
        _personal_summary_cache.pop((uid, months), None)
    data = get_personal_summary(dict(session))
    return JSONResponse(data)


@app.get("/api/goals")
async def api_goals_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse(get_goals(session.get("user_id")))


@app.post("/api/goals")
async def api_goals_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    set_goals(session.get("user_id"), payload)
    return JSONResponse(get_goals(session.get("user_id")))


@app.get("/api/team-comparison")
async def api_team_comparison_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse({"include": get_team_optin(session.get("user_id"))})


@app.post("/api/team-comparison")
async def api_team_comparison_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    set_team_optin(session.get("user_id"), payload.get("include", False))
    return JSONResponse({"include": get_team_optin(session.get("user_id"))})


@app.get("/api/snapshots")
async def api_snapshots_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse(get_snapshots(session.get("user_id")))


@app.post("/api/snapshots")
async def api_snapshots_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    user_id = session.get("user_id")
    label = (payload.get("label") or "").strip() or "Snapshot"
    data = get_personal_summary(dict(session))
    snap = save_snapshot(user_id, label, data.get("totals") or {})
    if not snap:
        return JSONResponse({"error": "Label required"}, status_code=400)
    return JSONResponse({"snapshot": snap, "snapshots": get_snapshots(user_id)})


@app.get("/share/{token}", name="share_view")
async def share_view(request: Request, token: str):
    record = get_share_link(token)
    if not record:
        return templates.TemplateResponse("share_expired.html", _template_context(request), status_code=404)
    ctx = _template_context(
        request,
        user=record.get("user") or {}, totals=record.get("totals") or {},
        time_range_label=record.get("time_range_label", "Last 12 months"),
        themes=record.get("themes") or [], highlights=record.get("highlights") or [],
        monthly=record.get("monthly") or [], created_at=record.get("created_at", ""),
    )
    return templates.TemplateResponse("share_view.html", ctx)


@app.post("/api/share")
async def api_share(request: Request, session: dict = Depends(require_session)):
    user_id = session.get("user_id")
    data = get_personal_summary(dict(session))
    token = save_share_link(user_id, data)
    if not token:
        return JSONResponse({"error": "Could not create link"}, status_code=500)
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"url": base + "/share/" + token, "token": token})


@app.get("/api/version")
async def api_version():
    return JSONResponse({"version": _app_version()})


@app.get("/api/summary-text")
async def api_summary_text(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    user = data.get("user") or {}
    totals = data.get("totals") or {}
    time_range_label = data.get("time_range_label", "Last 12 months")
    themes = data.get("themes") or []
    top_themes = themes[:5]
    theme_str = (
        ", ".join("%s (%s)" % (t.get("name", ""), t.get("count", 0)) for t in top_themes)
        if top_themes
        else "—"
    )
    jm = data.get("jira_metrics") or {}
    gm = data.get("gerrit_metrics") or {}
    parts = [
        "In %s: %s closed %s tickets and merged %s changes."
        % (time_range_label, user.get("name", "I"), totals.get("jira", 0), totals.get("gerrit", 0))
    ]
    if totals.get("confluence"):
        parts.append("Updated %s Confluence pages." % totals["confluence"])
    if totals.get("slack"):
        parts.append("Sent %s Slack messages." % totals["slack"])
    if jm.get("done_count") is not None:
        parts.append(
            "Jira: %s done (%s%% done rate)."
            % (jm.get("done_count", 0), jm.get("done_rate_pct", 0))
        )
    if gm.get("merged_count") is not None:
        parts.append(
            "Gerrit: %s merged (%s%% merge rate)."
            % (gm.get("merged_count", 0), gm.get("merge_rate_pct", 0))
        )
    if top_themes:
        parts.append("Top areas: %s." % theme_str)
    pc = data.get("period_comparison")
    if pc:
        c, p = pc.get("current_6m") or {}, pc.get("previous_6m") or {}
        if (c.get("jira", 0) + c.get("gerrit", 0)) and (p.get("jira", 0) + p.get("gerrit", 0)):
            delta = (c.get("jira", 0) + c.get("gerrit", 0)) - (
                p.get("jira", 0) + p.get("gerrit", 0)
            )
            trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
            parts.append("Last 6 months vs previous 6: delivery %s." % trend)
    highlights = data.get("highlights") or []
    if highlights:
        parts.append("")
        parts.extend("• " + h for h in highlights)
    return PlainTextResponse("\n".join(parts))


def _render_template_string(template_name: str, **context):
    """Render a template to string (for export/WeasyPrint)."""
    return templates.env.get_template(template_name).render(**context)


@app.get("/export/onepager")
async def export_onepager(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    themes = data.get("themes") or []
    top_projects = themes[:3]
    trend_line = None
    pc = data.get("period_comparison")
    if pc:
        c, p = pc.get("current_6m") or {}, pc.get("previous_6m") or {}
        jc, jp = c.get("jira", 0), p.get("jira", 0)
        gc, gp = c.get("gerrit", 0), p.get("gerrit", 0)
        total_p = jp + gp
        if total_p > 0:
            pct = round(100 * (jc + gc - jp - gp) / total_p)
            trend_line = "Last 6 months: {} tickets, {} changes. Previous 6: {}, {}. {}% {}.".format(
                jc, gc, jp, gp, abs(pct), "up" if pct >= 0 else "down"
            )
        else:
            trend_line = "Last 6 months: {} tickets, {} changes.".format(jc, gc)
    html = _render_template_string(
        "export_onepager.html",
        user=data.get("user") or {},
        totals=data.get("totals") or {},
        time_range_label=data.get("time_range_label", "Last 12 months"),
        top_projects=top_projects,
        trend_line=trend_line,
    )
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration
        font_config = FontConfiguration()
        pdf_bytes = HTML(string=html).write_pdf(font_config=font_config)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=work-wrapped-onepager.pdf"},
        )
    except Exception as e:
        return PlainTextResponse(
            "One-pager PDF failed (WeasyPrint error: {}). Try the full PDF or print from browser.".format(str(e)),
            status_code=503,
        )


@app.get("/export/pdf")
async def export_pdf(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    html = _render_template_string(
        "export_print.html",
        user=data.get("user") or {},
        totals=data.get("totals") or {},
        time_range_label=data.get("time_range_label", "Last 12 months"),
        monthly=data.get("monthly") or [],
        themes=data.get("themes") or [],
        gerrit_metrics=data.get("gerrit_metrics") or {},
        jira_metrics=data.get("jira_metrics") or {},
    )
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration
        font_config = FontConfiguration()
        pdf_bytes = HTML(string=html).write_pdf(font_config=font_config)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=work-wrapped.pdf"},
        )
    except Exception as e:
        return PlainTextResponse(
            "PDF export failed (WeasyPrint error: {}). Try printing the dashboard from your browser (Print → Save as PDF).".format(str(e)),
            status_code=503,
        )


@app.get("/api/export/json")
async def export_json(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    data = get_personal_summary(dict(session))
    return JSONResponse(
        data,
        headers={"Content-Disposition": "attachment; filename=work-wrapped.json"},
    )


@app.get("/api/export/csv")
async def export_csv(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    data = get_personal_summary(dict(session))
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "type",
            "key_or_id",
            "title_or_message",
            "status",
            "project_or_space_or_channel",
            "month",
            "link",
        ]
    )
    for t in data.get("jira") or []:
        w.writerow(
            [
                "jira",
                t.get("key", ""),
                (t.get("title") or "")[:200],
                t.get("status", ""),
                t.get("project", ""),
                t.get("month", ""),
                "",
            ]
        )
    for c in data.get("gerrit") or []:
        w.writerow(
            [
                "gerrit",
                c.get("number", ""),
                (c.get("message") or "")[:200],
                c.get("status", ""),
                c.get("project", ""),
                c.get("month", ""),
                "",
            ]
        )
    for p in data.get("confluence") or []:
        w.writerow(
            [
                "confluence",
                p.get("id", ""),
                (p.get("title") or "")[:200],
                "",
                p.get("space") or p.get("space_key", ""),
                p.get("month", ""),
                p.get("link", ""),
            ]
        )
    for s in data.get("slack") or []:
        w.writerow(
            [
                "slack",
                "",
                (s.get("text") or "")[:200],
                "",
                s.get("channel_name") or s.get("channel_id", ""),
                s.get("month", ""),
                s.get("link", ""),
            ]
        )
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=work-wrapped.csv"},
    )


@app.get("/api/team")
async def api_team(request: Request, session: dict = Depends(require_session)):
    team = request.query_params.get("team")
    return JSONResponse(get_team_summary(team))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
