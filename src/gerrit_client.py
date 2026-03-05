"""
Gerrit REST API client for authentication and fetching user changes.
Uses HTTP Basic auth with email + HTTP password (from Gerrit Settings).
"""

import requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, quote

# Gerrit prefixes JSON with )]}' to prevent XSSI - we must strip it
GERRIT_JSON_PREFIX = ")]}'\n"


def _parse_gerrit_response(resp):
    """Parse Gerrit JSON response (strips XSSI prefix)."""
    if not resp.text:
        return None
    text = resp.text
    if text.startswith(GERRIT_JSON_PREFIX):
        text = text[len(GERRIT_JSON_PREFIX) :]
    import json
    return json.loads(text) if text.strip() else None


class GerritError(Exception):
    """Gerrit API error."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class GerritClient:
    """Client for Gerrit REST API."""

    def __init__(self, base_url, verify_ssl=True):
        """
        Args:
            base_url: Gerrit base URL, e.g. https://gerrit.example.com
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.verify = verify_ssl

    def _url(self, path):
        """Build full URL. Use /a/ prefix for authenticated endpoints."""
        path = path if path.startswith("/") else "/" + path
        if not path.startswith("/a/"):
            path = "/a" + path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def authenticate(self, username, password):
        """
        Verify credentials by calling /a/accounts/self.
        Returns account info if valid, raises GerritError if invalid.

        Args:
            username: Gerrit username or email (depends on server config)
            password: HTTP password from Gerrit Settings → HTTP Password

        Returns:
            dict with _account_id, name, email, username
        """
        url = self._url("/accounts/self")
        try:
            resp = self._session.get(
                url,
                auth=(username, password),
                timeout=30,
            )
        except requests.exceptions.SSLError as e:
            raise GerritError(
                "SSL error connecting to Gerrit. Try setting GERRIT_VERIFY_SSL=false if using a self-signed certificate."
            )
        except requests.exceptions.ConnectionError as e:
            raise GerritError("Cannot reach Gerrit. Check GERRIT_URL and your network.")
        except requests.exceptions.RequestException as e:
            raise GerritError(f"Connection error: {e!s}")

        if resp.status_code == 401:
            raise GerritError(
                "Invalid email/username or HTTP password. Use your Gerrit username if email does not work, and the HTTP Password from Settings → HTTP Password.",
                status_code=401,
            )
        if resp.status_code != 200:
            raise GerritError(
                f"Gerrit returned {resp.status_code}",
                status_code=resp.status_code,
            )
        data = _parse_gerrit_response(resp)
        if not data:
            raise GerritError("Invalid response from Gerrit")
        return data

    def get_changes(
        self,
        username,
        password,
        owner_query="self",
        after_date=None,
        limit=500,
        options=None,
    ):
        """
        Fetch changes (code reviews) for a user.

        Args:
            username: Gerrit username or email
            password: HTTP password
            owner_query: "self" (when authenticated) or "email:user@example.com"
            after_date: datetime - only changes after this date
            limit: max number of changes to return
            options: list of option strings, e.g. ["CURRENT_REVISION", "CURRENT_FILES"]

        Returns:
            list of change dicts
        """
        # Build query: owner:self or owner:email:user@example.com
        query_parts = [f"owner:{owner_query}"]
        if after_date:
            after_str = after_date.strftime("%Y-%m-%d")
            query_parts.append(f"after:{after_str}")
        query = "+".join(query_parts)

        params = {"q": query, "n": limit}
        if options:
            for opt in options:
                params.setdefault("o", []).append(opt)

        url = self._url("/changes/")
        try:
            resp = self._session.get(
                url,
                auth=(username, password),
                params=params,
                timeout=60,
            )
        except requests.exceptions.SSLError:
            raise GerritError(
                "SSL error. Try GERRIT_VERIFY_SSL=false for self-signed certificates."
            )
        except requests.exceptions.ConnectionError:
            raise GerritError("Cannot reach Gerrit.")
        except requests.exceptions.RequestException as e:
            raise GerritError(f"Connection error: {e!s}")

        if resp.status_code == 401:
            raise GerritError("Authentication failed", status_code=401)
        if resp.status_code != 200:
            raise GerritError(
                f"Gerrit returned {resp.status_code}",
                status_code=resp.status_code,
            )
        data = _parse_gerrit_response(resp)
        return data if isinstance(data, list) else []

    def get_change_comments(self, change_id, username, password):
        """
        Fetch all published comments on a change.
        change_id: the change's "id" (e.g. project~branch~Ihash) or _number.
        Returns a flat list of comment dicts, each with "author" (dict with name, username, email, _account_id).
        """
        path = "/changes/{}/comments".format(quote(str(change_id)))
        url = self._url(path)
        try:
            resp = self._session.get(
                url,
                auth=(username, password),
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            raise GerritError("Failed to fetch comments: {}".format(e))
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise GerritError(
                "Comments request failed: {}".format(resp.status_code),
                status_code=resp.status_code,
            )
        data = _parse_gerrit_response(resp)
        if not isinstance(data, dict):
            return []
        comments = []
        for file_comments in data.values():
            if isinstance(file_comments, list):
                comments.extend(file_comments)
        return comments

    def get_my_changes(self, username, password, months=12):
        """
        Get all changes for the user in the last N months.
        Returns list of changes with subject, project, created, status, etc.
        Tries with date filter first; if empty, fetches without date and filters in Python
        (some Gerrit setups use different date semantics).
        """
        days_back = max(1, min(months * 31, 365 * 5))  # cap ~5 years
        after = datetime.now(timezone.utc) - timedelta(days=days_back)
        after_str = after.strftime("%Y-%m-%d")
        changes = self.get_changes(
            username,
            password,
            owner_query="self",
            after_date=after,
            limit=500,
            options=["CURRENT_REVISION", "CURRENT_FILES", "DETAILED_LABELS", "DETAILED_ACCOUNTS"],
        )
        # If no results, try without date filter (server may not support "after" as expected)
        if not changes:
            all_changes = self.get_changes(
                username,
                password,
                owner_query="self",
                after_date=None,
                limit=500,
                options=["CURRENT_REVISION", "CURRENT_FILES", "DETAILED_LABELS", "DETAILED_ACCOUNTS"],
            )
            for ch in all_changes:
                created = ch.get("created") or ""
                if created and created[:10] >= after_str:
                    changes.append(ch)
        return changes

    def get_changes_reviewed(self, username, password, months=12, limit=200):
        """
        Fetch changes where the current user is reviewer (not owner) in the last N months.
        Returns list of change dicts with id, _number, project, created, subject, status, etc.
        Used for "patches I reviewed" count and review velocity (by month), and for counting comments I wrote.
        """
        days_back = max(1, min(months * 31, 365 * 2))
        after = datetime.now(timezone.utc) - timedelta(days=days_back)
        after_str = after.strftime("%Y-%m-%d")
        # reviewer:self = changes where I am in the reviewer list (Gerrit standard)
        query = "reviewer:self+after:{}".format(after_str)
        params = {"q": query, "n": limit}
        params["o"] = ["CURRENT_REVISION", "DETAILED_ACCOUNTS"]
        url = self._url("/changes/")
        try:
            resp = self._session.get(
                url,
                auth=(username, password),
                params=params,
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            raise GerritError("Connection error: {}".format(e))
        if resp.status_code == 401:
            raise GerritError("Authentication failed", status_code=401)
        if resp.status_code != 200:
            raise GerritError("Gerrit returned {}".format(resp.status_code), status_code=resp.status_code)
        data = _parse_gerrit_response(resp)
        changes = data if isinstance(data, list) else []
        # Filter by date in Python (reviewer:self may not support after: on all servers)
        out = []
        for ch in changes:
            created = (ch.get("created") or "")[:10]
            if created and created >= after_str:
                out.append(ch)
            if len(out) >= limit:
                break
        return out
