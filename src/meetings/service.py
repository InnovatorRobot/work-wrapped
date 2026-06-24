"""1:1 meetings: agenda, notes, carry-forward action items, and history (JSON-backed).

Each user has a list of meetings stored in ``data/meetings.json`` keyed by user id.
A meeting holds an agenda (talking points, optionally seeded from the user's
activity), free-form notes, and action items. When a new meeting is created, any
still-open action items from the most recent previous meeting are carried forward.
"""

import secrets
from datetime import datetime, timezone

from storage import _load_json, _save_json

_FILE = "meetings.json"
_VALID_OWNERS = ("me", "manager")
_VALID_MEETING_STATUS = ("scheduled", "completed")
_VALID_ACTION_STATUS = ("open", "done")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _new_id():
    return secrets.token_hex(6)


def _clean_agenda_item(payload, existing=None):
    payload = payload or {}
    existing = existing or {}
    text = str(payload.get("text", existing.get("text", ""))).strip()[:500]
    if not text:
        return None
    return {
        "id": payload.get("id") or existing.get("id") or _new_id(),
        "text": text,
        "source": payload.get("source") or existing.get("source") or "manual",
        "done": bool(payload.get("done", existing.get("done", False))),
    }


def _clean_action_item(payload, existing=None):
    payload = payload or {}
    existing = existing or {}
    text = str(payload.get("text", existing.get("text", ""))).strip()[:500]
    if not text:
        return None
    owner = payload.get("owner", existing.get("owner", "me"))
    if owner not in _VALID_OWNERS:
        owner = "me"
    status = payload.get("status", existing.get("status", "open"))
    if status not in _VALID_ACTION_STATUS:
        status = "open"
    return {
        "id": payload.get("id") or existing.get("id") or _new_id(),
        "text": text,
        "owner": owner,
        "due_date": str(payload.get("due_date", existing.get("due_date", "")) or "").strip()[:10],
        "status": status,
        "carried_over": bool(payload.get("carried_over", existing.get("carried_over", False))),
    }


def _sorted(meetings):
    """Most recent first (by date, then creation time)."""
    return sorted(
        meetings,
        key=lambda m: (m.get("date", ""), m.get("created_at", "")),
        reverse=True,
    )


def get_meetings(user_id):
    """Return the user's meetings, most recent first."""
    if not user_id:
        return []
    data = _load_json(_FILE)
    return _sorted(data.get(str(user_id)) or [])


def get_meeting(user_id, meeting_id):
    """Return a single meeting or None."""
    for m in get_meetings(user_id):
        if m.get("id") == meeting_id:
            return m
    return None


def _open_actions_from_latest(sorted_meetings):
    """Carry forward open action items from the most recent meeting."""
    if not sorted_meetings:
        return []
    latest = sorted_meetings[0]
    carried = []
    for a in latest.get("action_items", []):
        if a.get("status") != "done" and (a.get("text") or "").strip():
            carried.append(
                {
                    "id": _new_id(),
                    "text": a["text"],
                    "owner": a.get("owner", "me"),
                    "due_date": a.get("due_date", ""),
                    "status": "open",
                    "carried_over": True,
                }
            )
    return carried


def create_meeting(user_id, title="", date="", manager_name="", manager_email="", seed_agenda=None):
    """Create a meeting, seeding the agenda and carrying forward open actions."""
    if not user_id:
        return None
    data = _load_json(_FILE)
    key = str(user_id)
    meetings = data.get(key) or []
    sorted_existing = _sorted(meetings)

    agenda = []
    for text in seed_agenda or []:
        item = _clean_agenda_item({"text": text, "source": "seed"})
        if item:
            agenda.append(item)

    meeting = {
        "id": _new_id(),
        "title": (title or "").strip()[:120] or "1:1 check-in",
        "date": (date or "").strip()[:10] or _today(),
        "manager_name": (manager_name or "").strip()[:120],
        "manager_email": (manager_email or "").strip()[:120],
        "status": "scheduled",
        "agenda": agenda,
        "notes": "",
        "action_items": _open_actions_from_latest(sorted_existing),
        "created_at": _now(),
        "updated_at": _now(),
    }
    meetings.append(meeting)
    data[key] = meetings
    _save_json(_FILE, data)
    return meeting


def update_meeting(user_id, meeting_id, payload):
    """Update a meeting. Lists (agenda, action_items) are replaced wholesale."""
    if not user_id:
        return None, "Not authenticated."
    data = _load_json(_FILE)
    key = str(user_id)
    meetings = data.get(key) or []
    idx = next((i for i, m in enumerate(meetings) if m.get("id") == meeting_id), None)
    if idx is None:
        return None, "Meeting not found."
    meeting = meetings[idx]
    payload = payload or {}

    if "title" in payload:
        meeting["title"] = str(payload["title"]).strip()[:120] or meeting.get(
            "title", "1:1 check-in"
        )
    if "date" in payload and str(payload["date"]).strip():
        meeting["date"] = str(payload["date"]).strip()[:10]
    if "status" in payload and payload["status"] in _VALID_MEETING_STATUS:
        meeting["status"] = payload["status"]
    if "notes" in payload:
        meeting["notes"] = str(payload["notes"] or "")[:20000]
    for field in ("manager_name", "manager_email"):
        if field in payload and payload[field] is not None:
            meeting[field] = str(payload[field]).strip()[:120]
    if isinstance(payload.get("agenda"), list):
        cleaned = [_clean_agenda_item(it) for it in payload["agenda"]]
        meeting["agenda"] = [it for it in cleaned if it]
    if isinstance(payload.get("action_items"), list):
        cleaned = [_clean_action_item(it) for it in payload["action_items"]]
        meeting["action_items"] = [it for it in cleaned if it]

    meeting["updated_at"] = _now()
    meetings[idx] = meeting
    data[key] = meetings
    _save_json(_FILE, data)
    return meeting, None


def delete_meeting(user_id, meeting_id):
    """Delete a meeting. Returns True if something was removed."""
    if not user_id:
        return False
    data = _load_json(_FILE)
    key = str(user_id)
    meetings = data.get(key) or []
    remaining = [m for m in meetings if m.get("id") != meeting_id]
    if len(remaining) == len(meetings):
        return False
    data[key] = remaining
    _save_json(_FILE, data)
    return True
