"""
Confluence REST API client: fetch pages created or updated by the current user.
Uses Basic auth with email + API token (Cloud) or username + password (Server).
Supports both Confluence Server/Data Center and Confluence Cloud.
"""

import requests
from urllib.parse import urljoin, quote
from datetime import datetime, timedelta, timezone


class ConfluenceError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _cql_escape(s):
    """Escape a string for use inside CQL double quotes (escape \ and ")."""
    if not s:
        return '""'
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class ConfluenceClient:
    def __init__(self, base_url, verify_ssl=True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.verify = verify_ssl

    def _url(self, path):
        path = path if path.startswith("/") else "/" + path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def get_current_user(self, auth):
        """
        Get the current authenticated user. Returns dict with username, userKey (Server), accountId (Cloud).
        Confluence Server: GET /rest/api/user/current returns type, username, userKey, etc.
        """
        url = self._url("/rest/api/user/current")
        r = self._session.get(url, auth=auth, timeout=15)
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def _fetch_cql(self, auth, cql, expand, limit_per_page, start_at):
        path = "/rest/api/content/search?cql={}&limit={}&start={}&expand={}".format(
            quote(cql), limit_per_page, start_at, expand
        )
        url = self._url(path)
        r = self._session.get(url, auth=auth, timeout=30)
        if r.status_code != 200:
            try:
                body = r.json()
                msg = body.get("message") or body.get("reason") or r.text[:200]
            except Exception:
                msg = r.text[:200] if r.text else r.reason
            raise ConfluenceError("Confluence search failed: {}".format(msg), r.status_code)
        return r.json()

    def _content_from_result(self, item):
        """Normalize search result: Server may return content at top level or under 'content'."""
        if not isinstance(item, dict):
            return None
        if item.get("content"):
            return item["content"]
        if item.get("id") and item.get("type"):
            return item
        return None

    def search_my_pages(self, email, api_token, months=12, max_results=200):
        """
        Fetch pages created or last updated by the current user in the last N months.
        Uses explicit username in CQL when available (currentUser() often fails with Basic auth on Server).
        """
        auth = (email, api_token)
        expand = "space,history,version"
        limit_per_page = min(50, max_results)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        # Get current user so we can use creator=username or userKey (more reliable than currentUser() with Basic auth)
        current_user_data = self.get_current_user(auth)
        # Try identifiers in order: username (Server), userKey (Server), accountId (Cloud)
        user_ids = []
        if isinstance(current_user_data, dict):
            for key in ("username", "userKey", "accountId", "name"):
                val = current_user_data.get(key)
                if val and str(val).strip() and val not in user_ids:
                    user_ids.append(str(val).strip())

        # 1) Try with explicit user id(s) + date (best for Server)
        for user_id in user_ids:
            user_cql = "(creator={} OR contributor={})".format(
                _cql_escape(user_id), _cql_escape(user_id)
            )
            cql_with_user_and_date = (
                'type=page AND {} AND lastModified>=endOfDay("-{}M") order by lastModified desc'
            ).format(user_cql, months)
            try:
                pages = self._search_paginated(
                    auth, cql_with_user_and_date, expand, limit_per_page, max_results, cutoff=None
                )
                if pages:
                    return pages
            except ConfluenceError as e:
                if e.status_code not in (400, 404):
                    raise
            cql_with_user = "type=page AND {} order by lastModified desc".format(user_cql)
            try:
                pages = self._search_paginated(
                    auth, cql_with_user, expand, limit_per_page, max_results, cutoff=cutoff
                )
                if pages:
                    return pages
            except ConfluenceError as e:
                if e.status_code not in (400, 404):
                    raise

        # 2) Fallback: currentUser() (works when session/cookie is used)
        cql_current = (
            "type=page AND (creator=currentUser() OR contributor=currentUser()) "
            'AND lastModified>=endOfDay("-{}M") order by lastModified desc'
        ).format(months)
        try:
            return self._search_paginated(
                auth, cql_current, expand, limit_per_page, max_results, cutoff=None
            )
        except ConfluenceError as e:
            if e.status_code not in (400, 404):
                raise
        cql_current_no_date = "type=page AND (creator=currentUser() OR contributor=currentUser()) order by lastModified desc"
        return self._search_paginated(
            auth, cql_current_no_date, expand, limit_per_page, max_results, cutoff=cutoff
        )

    def search_my_pages_created(self, email, api_token, months=12, max_results=500):
        """
        Fetch page IDs (or minimal content) created by the current user in the last N months.
        Used for "pages created vs updated" metrics. Returns list of content dicts with at least 'id'.
        """
        auth = (email, api_token)
        expand = "space,history,version"
        limit_per_page = 50
        current_user_data = self.get_current_user(auth)
        user_ids = []
        if isinstance(current_user_data, dict):
            for key in ("username", "userKey", "accountId", "name"):
                val = current_user_data.get(key)
                if val and str(val).strip() and val not in user_ids:
                    user_ids.append(str(val).strip())
        for user_id in user_ids:
            cql = 'type=page AND creator={} AND created>=endOfDay("-{}M") order by created desc'.format(
                _cql_escape(user_id), months
            )
            try:
                return self._search_paginated(
                    auth, cql, expand, limit_per_page, max_results, cutoff=None
                )
            except ConfluenceError as e:
                if e.status_code not in (400, 404):
                    raise
        cql = 'type=page AND creator=currentUser() AND created>=endOfDay("-{}M") order by created desc'.format(
            months
        )
        try:
            return self._search_paginated(
                auth, cql, expand, limit_per_page, max_results, cutoff=None
            )
        except ConfluenceError:
            return []

    def _search_paginated(self, auth, cql, expand, limit_per_page, max_results, cutoff=None):
        start = 0
        all_results = []
        while start < max_results:
            data = self._fetch_cql(auth, cql, expand, limit_per_page, start)
            results = data.get("results") or []
            for item in results:
                content = self._content_from_result(item)
                if not content:
                    continue
                if cutoff:
                    when = None
                    hist = content.get("history") or {}
                    if isinstance(hist, dict):
                        lu = hist.get("lastUpdated") or {}
                        when = (lu.get("when") or "")[:10]
                    if when and when < cutoff:
                        continue
                all_results.append(content)
                if len(all_results) >= max_results:
                    break
            if len(results) < limit_per_page:
                break
            start += limit_per_page
            if len(all_results) >= max_results:
                break
        return all_results[:max_results]
