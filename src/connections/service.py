"""Per-service connection status derived from the session."""

from config import GERRIT_URL, JIRA_URL, CONFLUENCE_URL


def get_session_connections(session_data):
    """Return connection status + identifier for each service from the session."""
    return {
        "gerrit": {
            "connected": bool(
                session_data.get("gerrit_username") and session_data.get("gerrit_password")
            ),
            "identifier": session_data.get("gerrit_username", ""),
            "configured": bool(GERRIT_URL),
        },
        "jira": {
            "connected": bool(
                session_data.get("jira_email") and session_data.get("jira_api_token")
            ),
            "identifier": session_data.get("jira_email", ""),
            "configured": bool(JIRA_URL),
        },
        "confluence": {
            "connected": bool(
                session_data.get("confluence_email") and session_data.get("confluence_api_token")
            ),
            "identifier": session_data.get("confluence_email", ""),
            "configured": bool(CONFLUENCE_URL),
        },
        "slack": {
            "connected": bool(session_data.get("slack_token")),
            "identifier": session_data.get("slack_name", ""),
            "configured": True,
        },
    }

