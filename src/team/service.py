"""Team comparison (opt-in), team metrics storage, and the aggregate team view.

Privacy: the team view only ever exposes aggregates (sums/averages and merged
themes) across opted-in users. Individual names are never included.
"""

from datetime import datetime, timezone

from storage import _load_json, _save_json

_METRICS_FILE = "team_metrics.json"
_OPTIN_FILE = "team_optin.json"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_team_optin(user_id):
    """Whether user has opted in to include their metrics in the team aggregate."""
    if not user_id:
        return False
    data = _load_json(_OPTIN_FILE)
    return bool(data.get(str(user_id), False))


def set_team_optin(user_id, include):
    """Set opt-in for the team view/comparison. Removes stored metrics on opt-out."""
    if not user_id:
        return
    data = _load_json(_OPTIN_FILE)
    data[str(user_id)] = bool(include)
    _save_json(_OPTIN_FILE, data)
    if not include:
        metrics = _load_json(_METRICS_FILE)
        if str(user_id) in metrics:
            del metrics[str(user_id)]
            _save_json(_METRICS_FILE, metrics)


def update_team_metrics(user_id, totals, themes=None, monthly=None):
    """Store the user's latest totals/themes for the team aggregate (opted-in only)."""
    if not user_id or not get_team_optin(user_id):
        return
    data = _load_json(_METRICS_FILE)
    data[str(user_id)] = {
        "totals": dict(totals or {}),
        "themes": [
            {"name": t.get("name"), "count": t.get("count", 0)}
            for t in (themes or [])
            if t.get("name")
        ][:20],
        "monthly": monthly or [],
        "updated_at": _now(),
    }
    _save_json(_METRICS_FILE, data)


def _entry_totals(v):
    """Support both the new {'totals': {...}} shape and the legacy flat totals dict."""
    if isinstance(v, dict) and "totals" in v:
        return v.get("totals") or {}
    return v or {}


def get_team_average():
    """Average totals across all opted-in users who have metrics stored."""
    data = _load_json(_METRICS_FILE)
    if not data:
        return None
    n = len(data)
    avg = {"jira": 0, "gerrit": 0, "confluence": 0, "slack": 0}
    for v in data.values():
        t = _entry_totals(v)
        for k in avg:
            avg[k] += t.get(k, 0)
    for k in avg:
        avg[k] = round(avg[k] / n, 1) if n else 0
    return {"average": avg, "participant_count": n}


def get_team_summary(team_name=None):
    """Aggregate view across opted-in users — totals (sum + average) and merged themes.

    Never includes individual names.
    """
    data = _load_json(_METRICS_FILE)
    participant_count = len(data)
    keys = ("jira", "gerrit", "confluence", "slack")
    totals = {k: 0 for k in keys}
    theme_counts = {}
    latest = None

    for v in data.values():
        t = _entry_totals(v)
        for k in keys:
            totals[k] += int(t.get(k, 0) or 0)
        if isinstance(v, dict):
            for th in v.get("themes") or []:
                name = th.get("name")
                if name:
                    theme_counts[name] = theme_counts.get(name, 0) + int(th.get("count", 0) or 0)
            up = v.get("updated_at")
            if up and (latest is None or up > latest):
                latest = up

    average = {
        k: (round(totals[k] / participant_count, 1) if participant_count else 0) for k in keys
    }
    themes = [
        {"name": n, "count": c} for n, c in sorted(theme_counts.items(), key=lambda x: -x[1])
    ][:12]

    highlights = []
    if participant_count:
        highlights.append(
            "{} contributor{} opted in.".format(
                participant_count, "s" if participant_count != 1 else ""
            )
        )
        total_items = sum(totals.values())
        if total_items:
            highlights.append("{} items of activity across the team.".format(total_items))
        if themes:
            highlights.append(
                "Top team area: {} ({}).".format(themes[0]["name"], themes[0]["count"])
            )
    else:
        highlights.append("No one has opted in yet. Enable team sharing in Settings.")

    return {
        "team": team_name or "All",
        "participant_count": participant_count,
        "totals": totals,
        "average": average,
        "themes": themes,
        "updated_at": latest,
        "highlights": highlights,
    }
