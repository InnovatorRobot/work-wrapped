"""Manager view + shared comments on objectives and 1:1 meetings (JSON-backed)."""

import secrets
from datetime import datetime, timezone

from storage import _load_json, _save_json
from settings.service import get_user_settings
from auth.service import list_users
from goals.service import get_objectives
from meetings.service import get_meetings

_COMMENTS_FILE = "manager_comments.json"
_VALID_KINDS = ("objective", "meeting")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(owner_id, kind, target_id):
    return "{}:{}:{}".format(owner_id, kind, target_id)


def get_comments(owner_id, kind, target_id):
    if not (owner_id and kind and target_id):
        return []
    data = _load_json(_COMMENTS_FILE)
    return data.get(_key(owner_id, kind, target_id)) or []


def add_comment(owner_id, kind, target_id, author_id, author_name, text):
    text = (text or "").strip()
    if not (owner_id and kind in _VALID_KINDS and target_id and text):
        return None
    data = _load_json(_COMMENTS_FILE)
    key = _key(owner_id, kind, target_id)
    items = data.get(key) or []
    comment = {
        "id": secrets.token_hex(6),
        "author_id": author_id,
        "author_name": author_name or "",
        "text": text[:2000],
        "date": _now(),
    }
    items.append(comment)
    data[key] = items
    _save_json(_COMMENTS_FILE, data)
    return comment


def is_manager_of(manager_email, owner_id):
    """True if `manager_email` is the opted-in manager of user `owner_id`."""
    if not (manager_email and owner_id):
        return False
    st = get_user_settings(owner_id)
    return bool(st.get("share_with_manager")) and (
        (st.get("manager_email") or "").strip().lower() == manager_email.strip().lower()
    )


def get_reports(manager_email):
    """Users who opted in to share with this manager, with their objectives & 1:1s."""
    if not manager_email:
        return []
    me = manager_email.strip().lower()
    reports = []
    for u in list_users():
        st = get_user_settings(u["id"])
        if not st.get("share_with_manager"):
            continue
        if (st.get("manager_email") or "").strip().lower() != me:
            continue
        objectives = [
            {**o, "comments": get_comments(u["id"], "objective", o.get("id"))}
            for o in get_objectives(u["id"])
        ]
        meetings = [
            {**m, "comments": get_comments(u["id"], "meeting", m.get("id"))}
            for m in get_meetings(u["id"])
        ]
        reports.append(
            {
                "user_id": u["id"],
                "name": u.get("name") or u.get("email"),
                "email": u.get("email"),
                "objectives": objectives,
                "meetings": meetings,
            }
        )
    return reports
