"""External service clients and their factory functions."""

from config import (
    GERRIT_URL,
    GERRIT_VERIFY_SSL,
    JIRA_URL,
    JIRA_VERIFY_SSL,
    CONFLUENCE_URL,
    CONFLUENCE_VERIFY_SSL,
)
from clients.gerrit import GerritClient, GerritError
from clients.jira import JiraClient, JiraError
from clients.confluence import ConfluenceClient, ConfluenceError
from clients.slack import SlackClient, SlackError

__all__ = [
    "GerritClient",
    "GerritError",
    "JiraClient",
    "JiraError",
    "ConfluenceClient",
    "ConfluenceError",
    "SlackClient",
    "SlackError",
    "get_gerrit_client",
    "get_jira_client",
    "get_confluence_client",
    "get_slack_client",
]


def get_gerrit_client():
    if not GERRIT_URL:
        raise GerritError("GERRIT_URL is not configured")
    return GerritClient(GERRIT_URL, verify_ssl=GERRIT_VERIFY_SSL)


def get_jira_client():
    if not JIRA_URL:
        raise JiraError("JIRA_URL is not configured")
    return JiraClient(JIRA_URL, verify_ssl=JIRA_VERIFY_SSL)


def get_confluence_client():
    if not CONFLUENCE_URL:
        raise ConfluenceError("CONFLUENCE_URL is not configured")
    return ConfluenceClient(CONFLUENCE_URL, verify_ssl=CONFLUENCE_VERIFY_SSL)


def get_slack_client():
    return SlackClient()
