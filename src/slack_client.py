"""
Slack Web API client: fetch messages sent by the current user in the last N months.
Uses a User OAuth Token (xoxp-...) with scopes: channels:read, groups:read,
channels:history, groups:history (and optionally im:read, im:history for DMs).
"""

import requests
from datetime import datetime, timedelta, timezone

SLACK_API_BASE = "https://slack.com/api"


class SlackError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class SlackClient:
    def __init__(self, base_url=SLACK_API_BASE):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()

    def _post(self, method, token, **params):
        url = "{}/{}".format(self.base_url, method)
        headers = {"Authorization": "Bearer {}".format(token)}
        r = self._session.post(url, headers=headers, json=params, timeout=30)
        data = r.json() if r.text else {}
        if not data.get("ok"):
            msg = data.get("error", "unknown") or r.text[:200]
            raise SlackError("Slack API error: {}".format(msg), r.status_code)
        return data

    def _get(self, method, token, params=None):
        url = "{}/{}".format(self.base_url, method)
        headers = {"Authorization": "Bearer {}".format(token)}
        r = self._session.get(url, headers=headers, params=params or {}, timeout=30)
        data = r.json() if r.text else {}
        if not data.get("ok"):
            msg = data.get("error", "unknown") or r.text[:200]
            raise SlackError("Slack API error: {}".format(msg), r.status_code)
        return data

    def auth_test(self, token):
        """Get current user id and workspace url. Returns dict with user, url, team, etc."""
        return self._post("auth.test", token)

    def users_conversations(self, token, types="public_channel,private_channel", limit=100, cursor=None):
        """List channels the user is in. Returns { channels: [...], response_metadata: { next_cursor } }."""
        params = {"types": types, "limit": limit, "exclude_archived": True}
        if cursor:
            params["cursor"] = cursor
        return self._get("users.conversations", token, params)

    def conversations_history(self, token, channel, oldest_ts, limit=200, cursor=None):
        """Get messages in a channel. Returns { messages: [...], has_more, response_metadata }."""
        params = {"channel": channel, "oldest": oldest_ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._get("conversations.history", token, params)

    def get_my_messages(self, token, months=12, max_messages=500, max_channels=40):
        """
        Fetch messages sent by the current user in the last N months.
        Uses auth.test, users.conversations, then conversations.history per channel (filter by user).
        Returns list of dicts: { ts, channel_id, channel_name, text, month, link }.
        """
        auth = self.auth_test(token)
        user_id = auth.get("user_id")
        team_url = (auth.get("url") or "").rstrip("/")
        if not user_id:
            raise SlackError("Slack auth did not return user id")

        oldest_ts = str(int((datetime.now(timezone.utc) - timedelta(days=months * 30)).timestamp()))
        channels = []
        cursor = None
        while True:
            resp = self.users_conversations(token, limit=100, cursor=cursor)
            channels.extend(resp.get("channels") or [])
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor or len(channels) >= max_channels:
                break
        channels = channels[:max_channels]

        out = []
        for ch in channels:
            if len(out) >= max_messages:
                break
            ch_id = ch.get("id")
            ch_name = (ch.get("name") or ch.get("channel", {}).get("name") or ch_id or "?")
            cursor = None
            while True:
                try:
                    resp = self.conversations_history(token, ch_id, oldest_ts, limit=200, cursor=cursor)
                except SlackError:
                    break
                msgs = resp.get("messages") or []
                for m in msgs:
                    if m.get("user") != user_id:
                        continue
                    if m.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
                        continue
                    ts = m.get("ts") or ""
                    thread_ts = m.get("thread_ts") or ""
                    is_thread_reply = bool(thread_ts and thread_ts != ts)
                    text = (m.get("text") or "").strip()[:200]
                    try:
                        sec = float(ts) if ts else 0
                        dt = datetime.fromtimestamp(sec, tz=timezone.utc)
                        month = dt.strftime("%Y-%m")
                        hour = dt.hour
                        weekday = dt.weekday()  # 0=Mon, 6=Sun
                    except (ValueError, OSError):
                        month = ""
                        hour = None
                        weekday = None
                    link = ""
                    if team_url and ch_id and ts:
                        ts_part = ts.replace(".", "")
                        link = "{}/archives/{}/p{}".format(team_url, ch_id, ts_part)
                    reactions = m.get("reactions") or []
                    reaction_count = sum(r.get("count", 0) for r in reactions if isinstance(r, dict))
                    reply_count = m.get("reply_count") if isinstance(m.get("reply_count"), (int, float)) else None
                    out.append({
                        "ts": ts,
                        "channel_id": ch_id,
                        "channel_name": ch_name,
                        "text": text,
                        "month": month,
                        "link": link,
                        "hour": hour,
                        "weekday": weekday,
                        "is_thread_reply": is_thread_reply,
                        "reaction_count": reaction_count,
                        "reply_count": reply_count,
                    })
                    if len(out) >= max_messages:
                        break
                if len(out) >= max_messages:
                    break
                if not resp.get("has_more"):
                    break
                cursor = (resp.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break

        # Sort by ts descending (newest first)
        out.sort(key=lambda x: x.get("ts") or "", reverse=True)
        return out[:max_messages]
