"""Build the personal dashboard summary payload."""

import calendar
from datetime import datetime
from urllib.parse import quote

from config import (
    DEFAULT_MONTHS,
    VALID_MONTHS,
    TIME_RANGE_OPTIONS,
    JIRA_URL,
    CONFLUENCE_URL,
    GERRIT_URL,
)
from summary.cache import _service_cache_get, _service_cache_set, _fetch_all_services
from connections.credentials import session_with_credentials
from metrics.gerrit import _gerrit_metrics, _parse_gerrit_date
from metrics.jira import _jira_metrics
from goals.service import get_goals, get_objectives, compute_objective_progress
from team.service import get_team_optin, update_team_metrics, get_team_average
from sharing.service import get_snapshots

try:
    from clients.llm import categorize_confluence_titles
except Exception:
    categorize_confluence_titles = None


def get_personal_summary(session_data, force_refresh=False):
    """
    Get personal view for the logged-in user.
    Uses session_data.get("months", DEFAULT_MONTHS) for the time range.
    Raw service content is read from the database cache when fresh; otherwise it is
    fetched from Gerrit/Jira/Confluence/Slack and stored. Goals, objectives, team
    comparison and other derived data are always recomputed so they stay current.
    """
    session_data = session_with_credentials(session_data)
    months = session_data.get("months", DEFAULT_MONTHS)
    if months not in VALID_MONTHS:
        months = DEFAULT_MONTHS

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
    # Raw service content: from DB cache when fresh, else fetch and store.
    user_id_for_cache = session_data.get("user_id")
    raw = None if force_refresh else _service_cache_get(user_id_for_cache, months)
    raw_fetched_at = None
    if raw is not None:
        raw_fetched_at = raw.get("_cached_fetched_at")
    else:
        raw = _fetch_all_services(session_data, months)
        # Only persist a clean fetch (no service errors) so transient failures aren't cached.
        if not any(
            raw.get(k) for k in ("gerrit_error", "jira_error", "confluence_error", "slack_error")
        ):
            _service_cache_set(user_id_for_cache, months, raw)

    gerrit = raw.get("gerrit") or []
    reviewer_comment_counts = raw.get("reviewer_comment_counts") or {}
    gerrit_error = raw.get("gerrit_error")
    gerrit_reviewed_stats = raw.get("gerrit_reviewed_stats")
    jira = raw.get("jira") or []
    jira_me = raw.get("jira_me")
    jira_error = raw.get("jira_error")
    confluence = raw.get("confluence") or []
    confluence_error = raw.get("confluence_error")
    confluence_created = raw.get("confluence_created") or []
    slack = raw.get("slack") or []
    slack_error = raw.get("slack_error")

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
        # Created by month (from raw confluence_created; updated by month = last_updated_by_month)
        by_month_created = {}
        for c in confluence_created or []:
            when = None
            hist = c.get("history") or {}
            if isinstance(hist, dict):
                when = hist.get("createdDate")
            if not when and isinstance(c.get("version"), dict):
                when = c["version"].get("when")
            if when:
                when = str(when)[:10]
                if len(when) >= 7:
                    month = when[:7]
                    by_month_created[month] = by_month_created.get(month, 0) + 1
        confluence_metrics["created_by_month"] = sorted(
            by_month_created.items(), key=lambda x: x[0]
        )
        confluence_metrics["created_by_month_max"] = max(by_month_created.values(), default=1)
        lum = sorted(by_month_cf.items(), key=lambda x: x[0])
        confluence_metrics["last_updated_by_month"] = lum
        confluence_metrics["last_updated_by_month_max"] = max(by_month_cf.values(), default=1)
        all_cf_months = sorted(set(by_month_created.keys()) | set(by_month_cf.keys()))
        confluence_metrics["created_and_updated_by_month"] = [
            (m, by_month_created.get(m, 0), by_month_cf.get(m, 0)) for m in all_cf_months
        ]
        confluence_metrics["top_spaces"] = sorted(by_space.items(), key=lambda x: -x[1])[:10]
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

    # Slack metrics: by channel, by hour/weekday (peak), thread vs single, reactions, longest threads
    slack_metrics = {}
    if slack is not None:
        by_channel = {}
        by_month_slack = {}
        by_hour = {i: 0 for i in range(24)}
        by_weekday = {i: 0 for i in range(7)}  # 0=Mon .. 6=Sun
        by_weekday_hour = {}  # (weekday, hour) -> count for peak cell
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
            if wd is not None and h is not None and 0 <= wd < 7 and 0 <= h < 24:
                key = (wd, h)
                by_weekday_hour[key] = by_weekday_hour.get(key, 0) + 1
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
        _weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        slack_metrics["weekday_names"] = _weekday_names
        if by_weekday_hour:
            peak_wd, peak_h = max(by_weekday_hour.items(), key=lambda x: x[1])[0]
            if peak_wd in (1, 2, 3) and peak_h in (9, 10, 11):
                slack_metrics["peak_weekday_hour_one_liner"] = "Most active Tue–Thu 9–11"
            else:
                slack_metrics["peak_weekday_hour_one_liner"] = "Most active {} at {:02d}:00".format(
                    _weekday_names[peak_wd], peak_h
                )
        else:
            slack_metrics["peak_weekday_hour_one_liner"] = None
        # Longest threads: root messages (not thread reply) with reply_count
        thread_roots = [
            s for s in slack if not s.get("is_thread_reply") and (s.get("reply_count") or 0) > 0
        ]
        longest_threads = sorted(
            [
                {
                    "channel_name": s.get("channel_name") or s.get("channel_id") or "?",
                    "text": (s.get("text") or "")[:80],
                    "reply_count": s.get("reply_count", 0),
                    "link": s.get("link") or "",
                }
                for s in thread_roots
            ],
            key=lambda x: -x["reply_count"],
        )[:10]
        slack_metrics["longest_threads"] = longest_threads
        slack_metrics["thread_reply_count"] = thread_reply_count
        slack_metrics["top_level_count"] = top_level_count
        slack_metrics["total_reactions"] = total_reactions

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

    # Same month last year: most recent month vs the same calendar month a year earlier
    same_month_last_year = None
    if sorted_months:
        latest = sorted_months[0]
        latest_key = latest.get("month") or ""
        parts = latest_key.split("-")
        if len(parts) == 2:
            try:
                year, mon = int(parts[0]), int(parts[1])
                prior_key = "{:04d}-{:02d}".format(year - 1, mon)
            except (ValueError, IndexError):
                prior_key = None
            prior = next((m for m in monthly if m.get("month") == prior_key), None)
            if prior_key and prior:

                def _month_label(key):
                    p = (key or "").split("-")
                    if len(p) == 2:
                        try:
                            mi = int(p[1])
                            if 1 <= mi <= 12:
                                return "{} {}".format(calendar.month_abbr[mi], p[0])
                        except (ValueError, IndexError):
                            pass
                    return key

                same_month_last_year = {
                    "current_month": latest_key,
                    "current_label": _month_label(latest_key),
                    "previous_year_month": prior_key,
                    "previous_label": _month_label(prior_key),
                    "current": {
                        "jira": latest.get("jira_count") or 0,
                        "gerrit": latest.get("gerrit_count") or 0,
                        "confluence": latest.get("confluence_count") or 0,
                        "slack": latest.get("slack_count") or 0,
                    },
                    "previous": {
                        "jira": prior.get("jira_count") or 0,
                        "gerrit": prior.get("gerrit_count") or 0,
                        "confluence": prior.get("confluence_count") or 0,
                        "slack": prior.get("slack_count") or 0,
                    },
                }

    # Cross-cutting: busiest month (by combined activity), focus score (% in top 2 themes), trend label
    busiest_month_cross = None
    if monthly:

        def _month_total(m):
            return (
                (m.get("jira_count") or 0)
                + (m.get("gerrit_count") or 0)
                + (m.get("confluence_count") or 0)
                + (m.get("slack_count") or 0)
            )

        best = max(monthly, key=_month_total)
        total_act = _month_total(best)
        if total_act > 0:
            parts = (best.get("month") or "").split("-")
            label = best.get("month", "")
            if len(parts) == 2:
                try:
                    mi = int(parts[1])
                    if 1 <= mi <= 12:
                        label = "{} {}".format(calendar.month_abbr[mi], parts[0])
                except (ValueError, IndexError):
                    pass
            busiest_month_cross = {"month": best.get("month"), "label": label, "count": total_act}

    # Cross-cutting: busiest ISO week (by combined activity across sources)
    busiest_week = None
    _week_counts = {}

    def _bump_week(date_str):
        if not date_str or len(date_str) < 10:
            return
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            return
        iso = d.isocalendar()
        key = "{:04d}-W{:02d}".format(iso[0], iso[1])
        _week_counts[key] = _week_counts.get(key, 0) + 1

    for _c in gerrit or []:
        _bump_week(_c.get("created"))
    for _t in jira or []:
        _bump_week(_t.get("updated") or _t.get("created"))
    for _p in confluence or []:
        _bump_week(_p.get("updated"))
    if _week_counts:
        best_week_key, best_week_count = max(_week_counts.items(), key=lambda x: x[1])
        wlabel = best_week_key
        try:
            _y, _w = best_week_key.split("-W")
            monday = datetime.strptime("{}-W{}-1".format(int(_y), int(_w)), "%G-W%V-%u").date()
            wlabel = "Week {} (starting {}), {}".format(int(_w), monday.strftime("%b %d"), int(_y))
        except (ValueError, IndexError):
            pass
        busiest_week = {"week": best_week_key, "label": wlabel, "count": best_week_count}

    focus_score_pct = None
    total_activity = len(jira or []) + len(gerrit or []) + len(confluence or []) + len(slack or [])
    if themes and total_activity > 0:
        top2 = sorted(themes.items(), key=lambda x: -x[1])[:2]
        top2_sum = sum(c for _, c in top2)
        focus_score_pct = round(100 * top2_sum / total_activity)
    trend_label = None
    if period_comparison:
        c6 = period_comparison.get("current_6m") or {}
        p6 = period_comparison.get("previous_6m") or {}
        cur = (
            (c6.get("jira") or 0)
            + (c6.get("gerrit") or 0)
            + (c6.get("confluence") or 0)
            + (c6.get("slack") or 0)
        )
        prev = (
            (p6.get("jira") or 0)
            + (p6.get("gerrit") or 0)
            + (p6.get("confluence") or 0)
            + (p6.get("slack") or 0)
        )
        if cur > prev:
            trend_label = "up"
        elif cur < prev:
            trend_label = "down"
        else:
            trend_label = "flat"

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
    objectives = []
    for obj in get_objectives(user_id):
        objectives.append({**obj, "computed_progress": compute_objective_progress(obj, totals)})
    team_optin = get_team_optin(user_id)
    team_comparison = None
    if team_optin:
        _team_themes = [
            {"name": k, "count": v} for k, v in sorted(themes.items(), key=lambda x: -x[1])
        ]
        update_team_metrics(user_id, totals, themes=_team_themes, monthly=monthly)
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

    # Stale open Gerrit changes (open >= 14 days) with links for the full page
    open_gerrit = [c for c in (gerrit or []) if (c.get("status") or "").upper() == "NEW"]
    stale_changes_list = []
    now_utc = datetime.utcnow()
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
        days_open = (now_utc - t).days
        if days_open >= 14:
            project = (c.get("project") or "").strip() or "project"
            num = c.get("number") or ""
            link = ""
            if GERRIT_URL and num:
                link = "{}/c/{}/+/{}".format(GERRIT_URL.rstrip("/"), quote(project), num)
            stale_changes_list.append(
                {
                    "number": num,
                    "message": (c.get("message") or "")[:100],
                    "project": project,
                    "link": link,
                    "days_open": days_open,
                }
            )
    if stale_changes_list:
        stale_changes_list.sort(key=lambda x: -x["days_open"])
    gerrit_metrics["stale_changes_list"] = stale_changes_list

    # Nudges: stale Gerrit, set goal
    nudges = []
    open_count = len(open_gerrit)
    stale_count = len(stale_changes_list)
    if open_gerrit:
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
        "objectives": objectives,
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
        "same_month_last_year": same_month_last_year,
        "busiest_month_cross": busiest_month_cross,
        "busiest_week": busiest_week,
        "focus_score_pct": focus_score_pct,
        "trend_label": trend_label,
        "months": months,
        "time_range_label": time_range_label,
        "time_range_options": TIME_RANGE_OPTIONS,
        "fetched_at": raw_fetched_at or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return result
