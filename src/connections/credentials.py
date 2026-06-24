"""Per-service credential storage, encrypted at rest in the database.

Credentials (Gerrit HTTP password, Jira/Confluence API tokens, Slack token) used
to live in the signed session cookie. They now live server-side in the
``credentials`` table, encrypted with Fernet using a key derived from SECRET_KEY,
and are merged into the request context only when needed to call a service.
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from config import SECRET_KEY
from database import session_scope
from models import Credential

# Map each service's stored fields to the session-style keys the fetchers expect.
_FIELD_MAP = {
    "gerrit": [("username", "gerrit_username"), ("password", "gerrit_password")],
    "jira": [("email", "jira_email"), ("api_token", "jira_api_token")],
    "confluence": [("email", "confluence_email"), ("api_token", "confluence_api_token")],
    "slack": [("token", "slack_token"), ("name", "slack_name")],
}
# Legacy session keys to clear from the cookie once creds move to the DB.
_ALL_SESSION_KEYS = [skey for fields in _FIELD_MAP.values() for _, skey in fields]


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def set_credentials(user_id, service, fields):
    """Encrypt and upsert credentials for (user, service)."""
    if not user_id or service not in _FIELD_MAP:
        return
    token = _fernet().encrypt(json.dumps(fields or {}).encode("utf-8")).decode("utf-8")
    with session_scope() as s:
        row = (
            s.query(Credential)
            .filter(Credential.user_id == str(user_id), Credential.service == service)
            .one_or_none()
        )
        if row:
            row.payload = token
        else:
            s.add(Credential(user_id=str(user_id), service=service, payload=token))


def get_credentials(user_id, service):
    """Return the decrypted fields dict for (user, service), or {}."""
    if not user_id or service not in _FIELD_MAP:
        return {}
    with session_scope() as s:
        row = (
            s.query(Credential)
            .filter(Credential.user_id == str(user_id), Credential.service == service)
            .one_or_none()
        )
        if not row:
            return {}
        try:
            return json.loads(_fernet().decrypt(row.payload.encode("utf-8")).decode("utf-8"))
        except (InvalidToken, ValueError, TypeError):
            return {}


def delete_credentials(user_id, service):
    """Remove stored credentials for (user, service)."""
    if not user_id or service not in _FIELD_MAP:
        return
    with session_scope() as s:
        s.query(Credential).filter(
            Credential.user_id == str(user_id), Credential.service == service
        ).delete(synchronize_session=False)


def get_all_credentials(user_id):
    """Return all of a user's credentials as session-style keys (gerrit_username, ...)."""
    out = {}
    if not user_id:
        return out
    for service, fields in _FIELD_MAP.items():
        creds = get_credentials(user_id, service)
        for fkey, skey in fields:
            val = creds.get(fkey)
            if val not in (None, ""):
                out[skey] = val
    return out


def session_with_credentials(session_data):
    """Return a copy of session_data with the user's DB credentials merged in.

    DB credentials take precedence; any legacy creds still in the session remain
    as a fallback (so existing sessions keep working until the user reconnects).
    """
    sd = dict(session_data or {})
    user_id = sd.get("user_id")
    if user_id:
        sd.update(get_all_credentials(user_id))
    return sd
