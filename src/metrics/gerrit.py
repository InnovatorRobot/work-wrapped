"""Gerrit metric computation from raw change data."""

from datetime import datetime

from config import GERRIT_EXCLUDE_REVIEWERS
from metrics.common import _percentiles


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
                "topic": (ch.get("topic") or "").strip(),
                "patch_sets": len(revs) if isinstance(revs, dict) and revs else 1,
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

    # By topic (changes grouped by Gerrit topic) and rework (patch sets per change)
    by_topic = {}
    for c in gerrit or []:
        tp = (c.get("topic") or "").strip()
        if tp:
            by_topic[tp] = by_topic.get(tp, 0) + 1
    top_topics = sorted(by_topic.items(), key=lambda x: -x[1])[:8]
    patch_set_counts = [int(c.get("patch_sets") or 1) for c in (gerrit or [])]
    avg_patch_sets = (
        round(sum(patch_set_counts) / len(patch_set_counts), 1) if patch_set_counts else None
    )
    changes_with_rework = sum(1 for n in patch_set_counts if n > 1)
    max_patch_sets = max(patch_set_counts) if patch_set_counts else 0
    most_revised = sorted(
        [
            {
                "number": c.get("number"),
                "message": (c.get("message") or "")[:100],
                "project": c.get("project") or "",
                "patch_sets": int(c.get("patch_sets") or 1),
            }
            for c in (gerrit or [])
            if int(c.get("patch_sets") or 1) > 1
        ],
        key=lambda x: -x["patch_sets"],
    )[:5]

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
        "top_topics": top_topics,
        "topics_count": len(by_topic),
        "avg_patch_sets": avg_patch_sets,
        "changes_with_rework": changes_with_rework,
        "max_patch_sets": max_patch_sets,
        "most_revised": most_revised,
    }
    if reviewed_stats:
        out["reviewed_count"] = reviewed_stats.get("reviewed_count", 0)
        rbm = reviewed_stats.get("reviewed_by_month") or {}
        out["reviewed_by_month"] = rbm
        out["reviewed_by_month_list"] = sorted(rbm.items(), key=lambda x: x[0])
        out["reviewed_by_month_max"] = max(rbm.values(), default=1)
        out["comments_given"] = reviewed_stats.get("comments_given", 0)
