"""Goals and rich objectives (stored in JSON)."""

import secrets
from datetime import datetime, timezone

from storage import _load_json, _save_json


def get_goals(user_id):
    """Return goals dict for user: e.g. tickets_done, reviews, messages (optional targets)."""
    if not user_id:
        return {}
    data = _load_json("goals.json")
    return data.get(str(user_id)) or {}


def set_goals(user_id, goals):
    """Save numeric metric targets for user. goals: dict with optional tickets_done, reviews, messages.
    Preserves any existing rich objectives stored alongside the metric targets."""
    if not user_id:
        return
    data = _load_json("goals.json")
    current = data.get(str(user_id)) or {}
    for k in ("tickets_done", "reviews", "messages"):
        if k not in (goals or {}):
            continue
        v = goals[k]
        if v is None or str(v).strip() == "":
            current.pop(k, None)
            continue
        try:
            current[k] = int(str(v).strip())
        except (TypeError, ValueError):
            pass
    data[str(user_id)] = current
    _save_json("goals.json", data)


# --- Rich objectives (title, status, target date, progress) ---
OBJECTIVE_CATEGORIES = ("delivery", "learning", "collaboration", "other")
OBJECTIVE_STATUSES = ("not_started", "in_progress", "done")
OBJECTIVE_METRICS = ("tickets_done", "reviews", "messages")


def _clean_objective(payload, existing=None):
    """Validate and normalize an objective payload. Returns (objective_dict, error)."""
    obj = dict(existing or {})
    title = str((payload or {}).get("title", obj.get("title", ""))).strip()[:140]
    if not title:
        return None, "Title is required."
    obj["title"] = title
    obj["description"] = str(
        (payload or {}).get("description", obj.get("description", ""))
    ).strip()[:600]

    category = str((payload or {}).get("category", obj.get("category", "other"))).strip().lower()
    obj["category"] = category if category in OBJECTIVE_CATEGORIES else "other"

    status = str((payload or {}).get("status", obj.get("status", "not_started"))).strip().lower()
    obj["status"] = status if status in OBJECTIVE_STATUSES else "not_started"

    target_date = str((payload or {}).get("target_date", obj.get("target_date", ""))).strip()[:10]
    obj["target_date"] = target_date

    metric = str((payload or {}).get("metric", obj.get("metric", ""))).strip()
    obj["metric"] = metric if metric in OBJECTIVE_METRICS else ""

    if "target" in (payload or {}) or "target" not in obj:
        raw_target = (payload or {}).get("target", obj.get("target"))
        try:
            obj["target"] = int(raw_target) if raw_target not in (None, "") else None
        except (TypeError, ValueError):
            obj["target"] = None

    if "progress" in (payload or {}) or "progress" not in obj:
        try:
            p = int((payload or {}).get("progress", obj.get("progress", 0)))
        except (TypeError, ValueError):
            p = 0
        obj["progress"] = max(0, min(100, p))

    # Evidence: attach real numbers/themes to back up the objective.
    if "evidence" in (payload or {}) or "evidence" not in obj:
        raw_ev = (payload or {}).get("evidence", obj.get("evidence") or [])
        evidence = []
        if isinstance(raw_ev, list):
            for item in raw_ev[:20]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).strip()[:120]
                if not label:
                    continue
                source = str(item.get("source", "manual")).strip().lower()
                if source not in ("jira", "gerrit", "confluence", "slack", "theme", "manual"):
                    source = "manual"
                val = item.get("value")
                try:
                    val = int(val) if val not in (None, "") else None
                except (TypeError, ValueError):
                    val = None
                evidence.append({"label": label, "value": val, "source": source})
        obj["evidence"] = evidence
    return obj, None


def get_objectives(user_id):
    """Return the list of rich objectives for the user."""
    if not user_id:
        return []
    data = _load_json("goals.json")
    return list((data.get(str(user_id)) or {}).get("objectives") or [])


def add_objective(user_id, payload):
    """Create a new objective. Returns (objective, error)."""
    if not user_id:
        return None, "Not signed in."
    obj, error = _clean_objective(payload)
    if error:
        return None, error
    obj["id"] = secrets.token_hex(6)
    obj["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = _load_json("goals.json")
    current = data.get(str(user_id)) or {}
    objectives = list(current.get("objectives") or [])
    objectives.append(obj)
    current["objectives"] = objectives
    data[str(user_id)] = current
    _save_json("goals.json", data)
    return obj, None


def update_objective(user_id, obj_id, payload):
    """Update an existing objective. Returns (objective, error)."""
    if not user_id:
        return None, "Not signed in."
    data = _load_json("goals.json")
    current = data.get(str(user_id)) or {}
    objectives = list(current.get("objectives") or [])
    for i, existing in enumerate(objectives):
        if existing.get("id") == obj_id:
            obj, error = _clean_objective(payload, existing)
            if error:
                return None, error
            obj["id"] = obj_id
            obj["created_at"] = existing.get("created_at")
            objectives[i] = obj
            current["objectives"] = objectives
            data[str(user_id)] = current
            _save_json("goals.json", data)
            return obj, None
    return None, "Objective not found."


def delete_objective(user_id, obj_id):
    """Delete an objective. Returns True if removed."""
    if not user_id:
        return False
    data = _load_json("goals.json")
    current = data.get(str(user_id)) or {}
    objectives = list(current.get("objectives") or [])
    new_objectives = [o for o in objectives if o.get("id") != obj_id]
    if len(new_objectives) == len(objectives):
        return False
    current["objectives"] = new_objectives
    data[str(user_id)] = current
    _save_json("goals.json", data)
    return True


def compute_objective_progress(objective, totals):
    """Return a 0-100 percent for an objective, derived from a linked metric or manual progress."""
    if objective.get("status") == "done":
        return 100
    metric = objective.get("metric")
    target = objective.get("target")
    if metric in OBJECTIVE_METRICS and target:
        metric_to_total = {"tickets_done": "jira", "reviews": "gerrit", "messages": "slack"}
        current = (totals or {}).get(metric_to_total[metric], 0)
        try:
            return max(0, min(100, round(current / int(target) * 100)))
        except (TypeError, ValueError, ZeroDivisionError):
            return 0
    try:
        return max(0, min(100, int(objective.get("progress", 0))))
    except (TypeError, ValueError):
        return 0
