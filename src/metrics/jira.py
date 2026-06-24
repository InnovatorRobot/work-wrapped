"""Jira metric computation from raw issue data."""

import calendar
import os
import re
from datetime import datetime

from metrics.common import _percentiles


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
    """From issue changelog compute: first assignee date (time to grab), first activity date (first response proxy),
    total days in 'In Review', total days in 'To Do', and whether the ticket was reopened (done -> open).
    Returns (grabbed_date, days_in_review, first_activity_date, days_in_todo, was_reopened).
    """
    grabbed_date = None
    first_activity_date = None
    review_entries = []  # (entry_time, exit_time) for each period in "In Review"
    todo_entries = []  # (entry_time, exit_time) for each period in "To Do" / "Open"
    was_reopened = False
    done_keywords = ("done", "resolved", "closed", "complete")
    todo_keywords = ("to do", "open", "backlog")

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
            from_val = (item.get("fromString") or "").strip().lower()
            to_val = (item.get("toString") or "").strip().lower()

            if (
                field == "assignee"
                and (item.get("toString") or "").strip()
                and grabbed_date is None
            ):
                if ts:
                    grabbed_date = ts.date() if hasattr(ts, "date") else ts
                break
            if field == "status":
                from_review = "review" in from_val
                to_review = "review" in to_val
                if to_review and not from_review and ts:
                    review_entries.append([ts, None])  # entered review
                elif from_review and not to_review and ts:
                    for e in reversed(review_entries):
                        if e[1] is None:
                            e[1] = ts
                            break
                from_done = any(k in from_val for k in done_keywords)
                to_todo = any(k in to_val for k in todo_keywords)
                to_done = any(k in to_val for k in done_keywords)
                from_todo = any(k in from_val for k in todo_keywords)
                if to_todo and from_done:
                    was_reopened = True
                if to_todo and ts:
                    todo_entries.append([ts, None])
                elif from_todo and ts:
                    for e in reversed(todo_entries):
                        if e[1] is None:
                            e[1] = ts
                            break

    days_in_review = 0.0
    for entry, exit_ in review_entries:
        if entry and exit_:
            delta = exit_ - entry
            days_in_review += delta.total_seconds() / 86400.0
    days_in_todo = 0.0
    for entry, exit_ in todo_entries:
        if entry and exit_:
            delta = exit_ - entry
            days_in_todo += delta.total_seconds() / 86400.0
    return (
        grabbed_date,
        round(days_in_review, 2),
        first_activity_date,
        round(days_in_todo, 2),
        was_reopened,
    )


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

        # Changelog: time to grab (first assignment), time in review, first activity, time in To Do, reopened
        (
            grabbed_date,
            days_in_review_float,
            first_activity_date,
            days_in_todo_float,
            was_reopened,
        ) = _jira_changelog_times(iss, created)
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
        days_in_todo = int(round(days_in_todo_float)) if days_in_todo_float else None

        # Comment count (Jira Cloud: comment.total; Server may use comment.comments length)
        comment_count = None
        comment_obj = fields.get("comment") or {}
        if isinstance(comment_obj, dict):
            if "total" in comment_obj:
                comment_count = comment_obj.get("total")
            elif "comments" in comment_obj:
                comments_list = comment_obj.get("comments") or []
                comment_count = len(comments_list) if isinstance(comments_list, list) else None
        if comment_count is not None and not isinstance(comment_count, int):
            try:
                comment_count = int(comment_count)
            except (TypeError, ValueError):
                comment_count = None

        # Story points (customfield_10016 common on Jira Cloud)
        story_points = None
        for fid in ("customfield_10016", "customfield_10004"):
            sp = fields.get(fid)
            if sp is not None and str(sp).strip() != "":
                try:
                    story_points = int(float(sp))
                    break
                except (TypeError, ValueError):
                    pass

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
                "days_in_todo": days_in_todo,
                "was_reopened": was_reopened,
                "comment_count": comment_count,
                "story_points": story_points,
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
    in_review_count = sum(c for s, c in by_status.items() if "review" in (s or "").lower())
    blocked_count = sum(c for s, c in by_status.items() if "blocked" in (s or "").lower())
    days_in_todo_list = [t["days_in_todo"] for t in jira if t.get("days_in_todo") is not None]
    total_days_in_todo = sum(days_in_todo_list) if days_in_todo_list else None
    avg_days_in_todo = (
        round(total_days_in_todo / len(days_in_todo_list), 1) if days_in_todo_list else None
    )
    reopened_count = sum(1 for t in jira if t.get("was_reopened"))
    comment_counts = [t["comment_count"] for t in jira if t.get("comment_count") is not None]
    total_comments = sum(comment_counts) if comment_counts else 0
    comments_per_ticket_avg = (
        round(total_comments / len(comment_counts), 1) if comment_counts else None
    )
    story_points_done = (
        sum(
            t.get("story_points") or 0
            for t in jira
            if t.get("resolutiondate") and (t.get("story_points") is not None)
        )
        or None
    )
    if story_points_done is not None and story_points_done == 0:
        story_points_done = None  # only show if at least one resolved ticket had points
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
        "in_review_count": in_review_count,
        "blocked_count": blocked_count,
        "total_days_in_todo": total_days_in_todo,
        "avg_days_in_todo": avg_days_in_todo,
        "reopened_count": reopened_count,
        "total_comments": total_comments,
        "comments_per_ticket_avg": comments_per_ticket_avg,
        "story_points_done": story_points_done,
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

