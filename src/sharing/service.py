"""Snapshots and shareable links (stored in JSON)."""

import os
import secrets
from datetime import datetime

from storage import _load_json, _save_json


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


