"""Per-service data fetchers (Gerrit/Jira/Confluence/Slack)."""

from concurrent.futures import ThreadPoolExecutor

from config import GERRIT_URL, JIRA_URL, CONFLUENCE_URL, GERRIT_EXCLUDE_REVIEWERS
from clients import (
    get_gerrit_client,
    get_jira_client,
    get_confluence_client,
    get_slack_client,
    GerritError,
    JiraError,
    ConfluenceError,
    SlackError,
)
from metrics.gerrit import _gerrit_changes_to_commits
from metrics.jira import _jira_issues_to_tickets, _enrich_jira_epic_names
from metrics.confluence import _confluence_pages_to_list


def _fetch_gerrit(session_data, months):
    """Fetch Gerrit changes, reviewer comment counts, and (optionally) changes I reviewed + comments I wrote.
    Returns (gerrit_list, reviewer_comment_counts, error_str, reviewed_stats). reviewed_stats: {reviewed_count, reviewed_by_month, comments_given}.
    """
    if not GERRIT_URL:
        return [], {}, "Gerrit is not configured.", {}
    if not session_data.get("gerrit_username") or not session_data.get("gerrit_password"):
        return [], {}, None, {}
    try:
        client = get_gerrit_client()
        changes = client.get_my_changes(
            session_data["gerrit_username"],
            session_data["gerrit_password"],
            months=months,
        )
        gerrit = _gerrit_changes_to_commits(changes)
        reviewer_comment_counts = {}
        # Fetch comment counts on my changes (comments I received) - parallel, 25 changes
        changes_to_fetch = changes[:25]

        def _comments_for_change(ch):
            change_id = ch.get("id") or ch.get("_number")
            if not change_id:
                return []
            try:
                return client.get_change_comments(
                    change_id,
                    session_data["gerrit_username"],
                    session_data["gerrit_password"],
                )
            except GerritError:
                return []

        with ThreadPoolExecutor(max_workers=10) as ex:
            for comments in ex.map(_comments_for_change, changes_to_fetch):
                for c in comments:
                    author = c.get("author") or {}
                    name = (
                        author.get("name") or author.get("username") or author.get("email") or ""
                    ).strip()
                    if not name or name.lower() in GERRIT_EXCLUDE_REVIEWERS:
                        continue
                    reviewer_comment_counts[name] = reviewer_comment_counts.get(name, 0) + 1

        # Changes where I'm reviewer: for review velocity and "comments I wrote"
        reviewed_stats = {"reviewed_count": 0, "reviewed_by_month": {}, "comments_given": 0}
        try:
            reviewed_changes = client.get_changes_reviewed(
                session_data["gerrit_username"],
                session_data["gerrit_password"],
                months=months,
                limit=200,
            )
        except GerritError:
            reviewed_changes = []
        for ch in reviewed_changes:
            reviewed_stats["reviewed_count"] += 1
            created = (ch.get("created") or "")[:7]
            if created:
                reviewed_stats["reviewed_by_month"][created] = (
                    reviewed_stats["reviewed_by_month"].get(created, 0) + 1
                )
        # Comments I wrote: fetch comments on first 20 reviewed changes, count where author is me
        me_identifiers = set()
        for key in ("gerrit_username", "gerrit_email", "user_name"):
            v = (session_data.get(key) or "").strip().lower()
            if v:
                me_identifiers.add(v)
        if me_identifiers and reviewed_changes:

            def _my_comments_on_change(ch):
                change_id = ch.get("id") or ch.get("_number")
                if not change_id:
                    return 0
                try:
                    comments = client.get_change_comments(
                        change_id,
                        session_data["gerrit_username"],
                        session_data["gerrit_password"],
                    )
                except GerritError:
                    return 0
                n = 0
                for c in comments:
                    author = c.get("author") or {}
                    for field in ("username", "name", "email"):
                        val = (author.get(field) or "").strip().lower()
                        if val and val in me_identifiers:
                            n += 1
                            break
                return n

            with ThreadPoolExecutor(max_workers=8) as ex:
                for count in ex.map(_my_comments_on_change, reviewed_changes[:20]):
                    reviewed_stats["comments_given"] += count
        return gerrit, reviewer_comment_counts, None, reviewed_stats
    except GerritError as e:
        return [], {}, str(e), {}


def _fetch_jira(session_data, months):
    """Fetch Jira issues and current user. Returns (jira_list, jira_me, error_str)."""
    if not JIRA_URL or not session_data.get("jira_email") or not session_data.get("jira_api_token"):
        return [], None, None
    try:
        client = get_jira_client()
        issues = client.search_my_issues(
            session_data["jira_email"],
            session_data["jira_api_token"],
            months=months,
            max_results=500,
        )
        jira = _jira_issues_to_tickets(issues)
        _enrich_jira_epic_names(
            client, jira, session_data["jira_email"], session_data["jira_api_token"]
        )
        jira_me = None
        try:
            jira_me = client.get_myself(
                session_data["jira_email"],
                session_data["jira_api_token"],
            )
        except JiraError:
            pass
        return jira, jira_me, None
    except JiraError as e:
        return [], None, str(e)


def _fetch_confluence(session_data, months):
    """Fetch Confluence pages. Returns (confluence_list, error_str)."""
    confluence_connected = bool(
        CONFLUENCE_URL
        and (
            (session_data.get("confluence_email") and session_data.get("confluence_api_token"))
            or (session_data.get("jira_email") and session_data.get("jira_api_token"))
        )
    )
    if not confluence_connected:
        return [], None
    cf_email = session_data.get("confluence_email") or session_data.get("jira_email")
    cf_token = session_data.get("confluence_api_token") or session_data.get("jira_api_token")
    try:
        client = get_confluence_client()
        raw_pages = client.search_my_pages(cf_email, cf_token, months=months, max_results=200)
        return _confluence_pages_to_list(raw_pages, CONFLUENCE_URL), None
    except ConfluenceError as e:
        return [], str(e)


def _fetch_confluence_created(session_data, months):
    """Fetch Confluence page IDs created by me in the last N months. Returns (list of content dicts with id, error_str)."""
    confluence_connected = bool(
        CONFLUENCE_URL
        and (
            (session_data.get("confluence_email") and session_data.get("confluence_api_token"))
            or (session_data.get("jira_email") and session_data.get("jira_api_token"))
        )
    )
    if not confluence_connected:
        return [], None
    cf_email = session_data.get("confluence_email") or session_data.get("jira_email")
    cf_token = session_data.get("confluence_api_token") or session_data.get("jira_api_token")
    try:
        client = get_confluence_client()
        raw = client.search_my_pages_created(cf_email, cf_token, months=months, max_results=500)
        return raw, None
    except ConfluenceError:
        return [], None


def _fetch_slack(session_data, months):
    """Fetch Slack messages. Returns (slack_list, error_str)."""
    if not session_data.get("slack_token"):
        return [], None
    try:
        client = get_slack_client()
        slack = client.get_my_messages(
            session_data["slack_token"],
            months=months,
            max_messages=500,
            max_channels=40,
        )
        return slack, None
    except SlackError as e:
        return [], str(e)


