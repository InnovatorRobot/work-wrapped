"""
Jira REST API client: fetch issues assigned to or created by the current user.
Uses Basic auth with email + API token (Jira Cloud) or username + password/token (Server).
"""

import os
import requests
from urllib.parse import urljoin, quote
from datetime import datetime, timedelta, timezone

# Optional: custom field key for Epic Link, e.g. customfield_10008 (overrides auto-detection)
EPIC_FIELD = os.environ.get("JIRA_EPIC_FIELD")
# Common Epic Link field IDs (Jira Cloud: customfield_10014; Server/DC: customfield_10008, customfield_10009, etc.)
EPIC_LINK_FIELDS = ["customfield_10014", "customfield_10008", "customfield_10009"]
# Include changelog for time-to-grab, assigned→resolved, and time-in-review metrics (set to 0/false/no to disable for faster Jira fetch)
INCLUDE_CHANGELOG = os.environ.get("JIRA_INCLUDE_CHANGELOG", "true").lower() not in ("0", "false", "no")


class JiraError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class JiraClient:
    def __init__(self, base_url, verify_ssl=True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.verify = verify_ssl

    def _url(self, path):
        path = path if path.startswith("/") else "/" + path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _auth(self, email, api_token):
        return (email, api_token)

    def search_my_issues(self, email, api_token, months=12, max_results=500):
        """
        Fetch issues assigned to OR reported by the current user (updated/created in last N months).
        Tries Basic auth first; if 401, tries cookie-based session.
        If date-filtered JQL returns 0 issues, retries without date filter and filters in Python
        (some Jira Server versions don't support "updated >= -12m" in JQL).
        """
        auth = self._auth(email, api_token)
        jql_with_date = f"(assignee = currentUser() OR reporter = currentUser()) AND updated >= -{months}m"
        jql_no_date = "assignee = currentUser() OR reporter = currentUser()"
        cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        # 1) Try with date filter (Basic auth then cookie)
        result = self._search_issues(auth, email, api_token, jql_with_date, max_results)
        # 2) If 0 results, try without date filter and filter in Python
        if result is not None and len(result) == 0:
            result = self._search_issues(auth, email, api_token, jql_no_date, max_results)
            if result and len(result) > 0:
                filtered = []
                for iss in result:
                    fields = iss.get("fields") or {}
                    updated = (fields.get("updated") or fields.get("created") or "")[:10]
                    if updated >= cutoff:
                        filtered.append(iss)
                result = filtered[:max_results]

        if result is not None:
            return result
        return self._search_jql_paginated(email, api_token, jql_with_date, max_results)

    def _search_issues(self, auth, email, api_token, jql, max_results):
        """Run search with Basic auth; on 401 try cookie session then retry. Returns list or None on 404."""
        for api_path in ["/rest/api/2/search", "/rest/api/3/search"]:
            try:
                r = self._search_classic(api_path, auth, jql, max_results)
                if r is not None:
                    return r
            except JiraError as e:
                if e.status_code != 401:
                    raise
                break
        try:
            self._login_session(email, api_token)
            for api_path in ["/rest/api/2/search", "/rest/api/3/search"]:
                r = self._search_classic(api_path, None, jql, max_results)
                if r is not None:
                    return r
        except JiraError:
            raise
        return None

    def _login_session(self, username, password):
        """Create a session via POST .../rest/auth/1/session (cookie-based). Tries with and without /jira context path."""
        for path in ["/rest/auth/1/session", "/jira/rest/auth/1/session"]:
            url = self._url(path)
            try:
                resp = self._session.post(
                    url,
                    json={"username": username, "password": password},
                    timeout=30,
                    headers={"Content-Type": "application/json"},
                )
            except requests.exceptions.RequestException as e:
                raise JiraError(f"Could not reach Jira: {e!s}")
            if resp.status_code == 404:
                continue
            if resp.status_code in (200, 201):
                return
            if resp.status_code == 401:
                raise JiraError(
                    "Jira rejected the login. Use your Jira username (not email) and your normal Jira password. "
                    "Same as when you open jira.zenseact.com in the browser.",
                    status_code=401,
                )
            if resp.status_code != 404:
                raise JiraError(f"Jira login returned {resp.status_code}", status_code=resp.status_code)
        raise JiraError("Jira session login not available (404). Your Jira may have API access disabled.")

    def get_myself(self, email, api_token):
        """Return current user info (name, displayName, key) for JQL comparison."""
        auth = self._auth(email, api_token)
        for path in ["/rest/api/2/myself", "/rest/api/3/myself"]:
            url = self._url(path)
            try:
                resp = self._session.get(url, auth=auth, timeout=30, headers={"Accept": "application/json"})
            except requests.exceptions.RequestException as e:
                raise JiraError(f"Could not reach Jira: {e!s}")
            if resp.status_code == 401:
                try:
                    self._login_session(email, api_token)
                    resp = self._session.get(url, auth=None, timeout=30, headers={"Accept": "application/json"})
                except JiraError:
                    raise
            if resp.status_code == 404:
                continue
            if resp.status_code != 200:
                raise JiraError(f"Jira returned {resp.status_code}", status_code=resp.status_code)
            data = resp.json()
            return {
                "name": data.get("name") or data.get("key") or "",
                "displayName": data.get("displayName") or data.get("name") or "",
                "key": data.get("key") or data.get("name") or "",
                "accountId": data.get("accountId") or "",
            }
        raise JiraError("Could not get current user from Jira.")

    def _search_classic(self, api_path, auth, jql, max_results):
        """GET /rest/api/2/search or /rest/api/3/search with startAt pagination. Returns list or None on 404. auth=None uses session cookie."""
        url = self._url(api_path)
        base_fields = "summary,project,status,issuetype,created,updated,resolutiondate,assignee,reporter,parent,labels,priority,components"
        extra = list(EPIC_LINK_FIELDS) + ["customfield_10020"]
        if EPIC_FIELD and EPIC_FIELD not in extra:
            extra.append(EPIC_FIELD)
        fields = f"{base_fields},{','.join(extra)}"
        params = {
            "jql": jql,
            "maxResults": min(100, max_results),
            "startAt": 0,
            "fields": fields,
        }
        if INCLUDE_CHANGELOG:
            params["expand"] = "changelog"
        all_issues = []
        try:
            while True:
                timeout_sec = 120 if INCLUDE_CHANGELOG else 60
                resp = self._session.get(
                    url, auth=auth, params=params, timeout=timeout_sec, headers={"Accept": "application/json"},
                )
                if resp.status_code == 401:
                    raise JiraError(
                        "Jira rejected the login. Use your Jira username (not email) and your normal Jira password. "
                        "Same as when you open jira.zenseact.com in the browser.",
                        status_code=401,
                    )
                if resp.status_code == 404:
                    return None
                if resp.status_code != 200:
                    raise JiraError(f"Jira returned {resp.status_code}", status_code=resp.status_code)
                data = resp.json()
                issues = data.get("issues") or []
                all_issues.extend(issues)
                start_at = data.get("startAt", 0) + len(issues)
                total = data.get("total", 0)
                if start_at >= total or len(issues) == 0 or len(all_issues) >= max_results:
                    break
                params["startAt"] = start_at
        except JiraError:
            raise
        except requests.exceptions.SSLError:
            raise JiraError("SSL error connecting to Jira. Try JIRA_VERIFY_SSL=false.")
        except requests.exceptions.ConnectionError:
            raise JiraError("Cannot reach Jira. Check JIRA_URL and network.")
        except requests.exceptions.RequestException as e:
            raise JiraError(f"Connection error: {e!s}")
        return all_issues

    def get_issues_by_keys(self, email, api_token, keys, fields="summary"):
        """Fetch issues by key; returns list of issue dicts with key and fields (e.g. summary). Used to resolve epic names."""
        if not keys:
            return []
        keys = list(dict.fromkeys(k for k in keys if k))
        auth = self._auth(email, api_token)
        all_issues = []
        chunk = 50
        for i in range(0, len(keys), chunk):
            batch = keys[i : i + chunk]
            jql = "key in ({})".format(",".join(batch))
            url = self._url("/rest/api/2/search")
            params = {"jql": jql, "maxResults": chunk, "fields": fields}
            try:
                resp = self._session.get(
                    url, auth=auth, params=params, timeout=30, headers={"Accept": "application/json"}
                )
            except requests.exceptions.RequestException:
                continue
            if resp.status_code != 200:
                continue
            data = resp.json()
            all_issues.extend(data.get("issues") or [])
        return all_issues

    def _search_jql_paginated(self, email, api_token, jql, max_results):
        """Jira Cloud new endpoint: GET /rest/api/3/search/jql with nextPageToken."""
        auth = self._auth(email, api_token)
        all_issues = []
        url = self._url("/rest/api/3/search/jql")
        base_fields = "summary,project,status,issuetype,created,updated,resolutiondate,assignee,reporter,parent,labels,priority,components"
        extra = list(EPIC_LINK_FIELDS) + ["customfield_10020"]
        if EPIC_FIELD and EPIC_FIELD not in extra:
            extra.append(EPIC_FIELD)
        fields = f"{base_fields},{','.join(extra)}"
        params = {
            "jql": jql,
            "maxResults": min(100, max_results),
            "fields": fields,
        }
        next_token = None
        while True:
            if next_token is not None:
                params["nextPageToken"] = next_token
            resp = self._session.get(
                url,
                auth=auth,
                params=params,
                timeout=60,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 401:
                raise JiraError(
                    "Jira rejected the login. Use Jira username + password (Server) or email + API token (Cloud).",
                    status_code=401,
                )
            if resp.status_code != 200:
                raise JiraError(f"Jira returned {resp.status_code}", status_code=resp.status_code)
            data = resp.json()
            issues = data.get("values") or data.get("issues") or []
            all_issues.extend(issues)
            next_token = data.get("nextPageToken")
            if not next_token or len(all_issues) >= max_results:
                break
        return all_issues
