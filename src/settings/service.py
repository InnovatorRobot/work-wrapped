"""User settings (defaults, manager)."""

from storage import _load_json, _save_json
from config import VALID_MONTHS

_VALID_DIGEST = ("off", "weekly", "monthly")


def get_user_settings(user_id):
    """Return the user's settings merged over defaults."""
    settings = {
        "default_months": 12,
        "manager_name": "",
        "manager_email": "",
        "share_with_manager": False,
        "digest_frequency": "off",
    }
    if not user_id:
        return settings
    data = _load_json("settings.json")
    stored = data.get(str(user_id)) or {}
    settings.update({k: stored[k] for k in settings if k in stored})
    return settings


def set_user_settings(user_id, values):
    """Persist user settings. Only known keys are stored; invalid values are ignored."""
    if not user_id:
        return get_user_settings(user_id)
    data = _load_json("settings.json")
    current = data.get(str(user_id)) or {}
    values = values or {}
    if "default_months" in values:
        try:
            m = int(values["default_months"])
            if m in VALID_MONTHS:
                current["default_months"] = m
        except (TypeError, ValueError):
            pass
    for key in ("manager_name", "manager_email"):
        if key in values and values[key] is not None:
            current[key] = str(values[key]).strip()[:120]
    if "share_with_manager" in values:
        current["share_with_manager"] = bool(values["share_with_manager"])
    if "digest_frequency" in values:
        freq = str(values["digest_frequency"]).strip().lower()
        if freq in _VALID_DIGEST:
            current["digest_frequency"] = freq
    data[str(user_id)] = current
    _save_json("settings.json", data)
    return get_user_settings(user_id)
