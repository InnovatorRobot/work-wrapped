"""Persistent service-content cache (DB-backed) and parallel fetch orchestration."""

import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from config import CACHE_TTL_MINUTES
from database import session_scope
from models import ServiceCache
from summary.fetchers import (
    _fetch_gerrit,
    _fetch_jira,
    _fetch_confluence,
    _fetch_confluence_created,
    _fetch_slack,
)


# Persistent service-content cache lives in the database (table: service_cache).
# Raw fetched data per (user_id, months) is stored so we don't re-query Gerrit /
# Jira / Confluence / Slack on every page load.


def _service_cache_get(user_id, months):
    """Return cached raw service data dict for (user, months) if present and fresh, else None."""
    if not user_id:
        return None
    try:
        with session_scope() as s:
            row = (
                s.query(ServiceCache)
                .filter(ServiceCache.user_id == str(user_id), ServiceCache.cache_key == str(months))
                .one_or_none()
            )
            if not row:
                return None
            if CACHE_TTL_MINUTES and row.fetched_at:
                age = (datetime.utcnow() - row.fetched_at).total_seconds()
                if age > CACHE_TTL_MINUTES * 60:
                    return None
            data = json.loads(row.payload)
            data["_cached_fetched_at"] = (
                row.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.fetched_at else None
            )
            return data
    except Exception:
        return None


def _service_cache_set(user_id, months, raw):
    """Store/refresh the raw service data for (user, months)."""
    if not user_id:
        return
    try:
        payload = json.dumps(raw)
    except (TypeError, ValueError):
        return
    try:
        with session_scope() as s:
            row = (
                s.query(ServiceCache)
                .filter(ServiceCache.user_id == str(user_id), ServiceCache.cache_key == str(months))
                .one_or_none()
            )
            if row:
                row.payload = payload
                row.fetched_at = datetime.utcnow()
            else:
                s.add(
                    ServiceCache(
                        user_id=str(user_id),
                        cache_key=str(months),
                        payload=payload,
                        fetched_at=datetime.utcnow(),
                    )
                )
    except Exception:
        pass


def invalidate_service_cache(user_id, months=None):
    """Delete cached service content for a user (all time ranges, or a specific one)."""
    if not user_id:
        return
    try:
        with session_scope() as s:
            q = s.query(ServiceCache).filter(ServiceCache.user_id == str(user_id))
            if months is not None:
                q = q.filter(ServiceCache.cache_key == str(months))
            q.delete(synchronize_session=False)
    except Exception:
        pass


def _fetch_all_services(session_data, months):
    """Fetch raw content from all connected services in parallel. Returns a dict bundle."""
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut_gerrit = ex.submit(_fetch_gerrit, session_data, months)
        fut_jira = ex.submit(_fetch_jira, session_data, months)
        fut_confluence = ex.submit(_fetch_confluence, session_data, months)
        fut_confluence_created = ex.submit(_fetch_confluence_created, session_data, months)
        fut_slack = ex.submit(_fetch_slack, session_data, months)
        gerrit, reviewer_comment_counts, gerrit_error, gerrit_reviewed_stats = fut_gerrit.result()
        jira, jira_me, jira_error = fut_jira.result()
        confluence, confluence_error = fut_confluence.result()
        confluence_created, _ = fut_confluence_created.result()
        slack, slack_error = fut_slack.result()
    return {
        "gerrit": gerrit,
        "reviewer_comment_counts": reviewer_comment_counts,
        "gerrit_error": gerrit_error,
        "gerrit_reviewed_stats": gerrit_reviewed_stats,
        "jira": jira,
        "jira_me": jira_me,
        "jira_error": jira_error,
        "confluence": confluence,
        "confluence_error": confluence_error,
        "confluence_created": confluence_created,
        "slack": slack,
        "slack_error": slack_error,
    }

