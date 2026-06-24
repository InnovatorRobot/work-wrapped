"""Local user accounts (email + password) and session establishment."""

import hashlib
import json
import os
import secrets
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from config import DATA_DIR as _DATA_DIR, DEFAULT_MONTHS
from database import session_scope
from models import User
from settings.service import get_user_settings


def _hash_password(password, salt=None):
    """Return (salt_hex, hash_hex) using PBKDF2-HMAC-SHA256."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), bytes.fromhex(salt), 200_000
    )
    return salt, dk.hex()


def _verify_password(password, salt, expected_hash):
    if not (salt and expected_hash):
        return False
    try:
        _, computed = _hash_password(password, salt)
    except ValueError:
        return False
    return secrets.compare_digest(computed, expected_hash)


def _normalize_email(email):
    return (email or "").strip().lower()


def get_user_by_email(email):
    """Return user dict (with 'id') for the given email, or None."""
    email = _normalize_email(email)
    if not email:
        return None
    with session_scope() as s:
        user = s.query(User).filter(User.email == email).one_or_none()
        return user.to_dict() if user else None


def get_user_by_id(user_id):
    """Return user dict for the given id, or None."""
    if not user_id:
        return None
    with session_scope() as s:
        user = s.query(User).filter(User.id == str(user_id)).one_or_none()
        return user.to_dict() if user else None


def list_users():
    """Return all users as dicts (id, email, name)."""
    with session_scope() as s:
        return [u.to_dict() for u in s.query(User).all()]


def create_user(email, password, name=""):
    """Create a local account in the database. Returns (user_dict, error_message)."""
    email = _normalize_email(email)
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return None, "Enter a valid email address."
    if not password or len(password) < 8:
        return None, "Password must be at least 8 characters."
    if get_user_by_email(email):
        return None, "An account with that email already exists. Sign in instead."
    salt, pw_hash = _hash_password(password)
    user = User(
        id=secrets.token_hex(8),
        email=email,
        name=(name or "").strip()[:80] or email.split("@")[0],
        password_salt=salt,
        password_hash=pw_hash,
        created_at=datetime.utcnow(),
    )
    try:
        with session_scope() as s:
            s.add(user)
            s.flush()
            result = user.to_dict()
        return result, None
    except IntegrityError:
        return None, "An account with that email already exists. Sign in instead."


def authenticate_user(email, password):
    """Return user dict if email/password match, else None."""
    user = get_user_by_email(email)
    if not user:
        return None
    if _verify_password(password, user.get("password_salt"), user.get("password_hash")):
        return user
    return None


def _migrate_json_users():
    """One-time import of any legacy data/users.json accounts into the database."""
    path = os.path.join(_DATA_DIR, "users.json")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(legacy, dict) or not legacy:
        return
    imported = 0
    with session_scope() as s:
        for uid, u in legacy.items():
            email = _normalize_email(u.get("email"))
            if not email:
                continue
            exists = s.query(User).filter(User.email == email).one_or_none()
            if exists:
                continue
            s.add(
                User(
                    id=str(uid),
                    email=email,
                    name=(u.get("name") or "")[:120],
                    password_salt=u.get("password_salt") or "",
                    password_hash=u.get("password_hash") or "",
                    created_at=datetime.utcnow(),
                )
            )
            imported += 1
    if imported:
        # Keep the JSON as a backup but mark it migrated so we don't re-import.
        try:
            os.rename(path, path + ".migrated")
        except OSError:
            pass


def _establish_session(request, user):
    """Set up a fresh logged-in session for a local account."""
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["user_name"] = user.get("name") or user.get("email")
    request.session["user_email"] = user.get("email")
    settings = get_user_settings(user["id"])
    request.session["months"] = settings.get("default_months", DEFAULT_MONTHS)
