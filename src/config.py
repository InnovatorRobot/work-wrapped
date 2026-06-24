"""Global configuration: environment variables, paths, and shared constants."""

import os

# Project root (parent of src/) for .env, VERSION, frontend templates and data.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from project root before reading any environment variables below.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
except ImportError:
    pass


def app_version():
    """Read version from VERSION file in project root (set at Docker build)."""
    try:
        p = os.path.join(_ROOT, "VERSION")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read().strip() or "dev"
    except Exception:
        pass
    return "dev"


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

# Gerrit config
GERRIT_URL = os.environ.get("GERRIT_URL", "").rstrip("/")
GERRIT_VERIFY_SSL = os.environ.get("GERRIT_VERIFY_SSL", "true").lower() == "true"

# Jira config (optional)
JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_VERIFY_SSL = os.environ.get("JIRA_VERIFY_SSL", "true").lower() == "true"

# Confluence config (optional)
CONFLUENCE_URL = os.environ.get("CONFLUENCE_URL", "").rstrip("/")
CONFLUENCE_VERIFY_SSL = os.environ.get("CONFLUENCE_VERIFY_SSL", "true").lower() == "true"

# Demo mode: when enabled, a "View demo" button lets you explore the UI with a
# sample session without connecting to any real service. Off by default.
DEMO_MODE = os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")

# How long cached service content (Gerrit/Jira/Confluence/Slack) stays fresh in the
# database before we re-query the services. Set to 0 to disable expiry.
try:
    CACHE_TTL_MINUTES = int(os.environ.get("CACHE_TTL_MINUTES", "360"))
except ValueError:
    CACHE_TTL_MINUTES = 360

# Gerrit: exclude these reviewers/CC from counts (e.g. bot accounts like svc00140)
GERRIT_EXCLUDE_REVIEWERS = frozenset(
    n.strip().lower()
    for n in os.environ.get("GERRIT_EXCLUDE_REVIEWERS", "svc00140").split(",")
    if n.strip()
)

# Directories
DATA_DIR = os.path.join(_ROOT, "data")
FRONTEND_DIR = os.path.join(_ROOT, "frontend")

# Time range options for filters: (months, label). Default 12.
TIME_RANGE_OPTIONS = [
    (3, "Last 3 months"),
    (6, "Last 6 months"),
    (12, "Last 12 months"),
    (24, "Last 2 years"),
    (36, "Last 3 years"),
]
VALID_MONTHS = frozenset(m for m, _ in TIME_RANGE_OPTIONS)
DEFAULT_MONTHS = 12

# Public base URL used in emails (e.g. digest links). Adjust for your deployment.
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5001").rstrip("/")

# SMTP for the optional email digest. If SMTP_HOST is unset, the digest is disabled
# and the app behaves normally (no emails are sent).
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
try:
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "work-wrapped@localhost").strip()
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")


def smtp_configured():
    return bool(SMTP_HOST)
