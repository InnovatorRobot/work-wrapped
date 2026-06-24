"""Email digest: compose a "your week/month" summary and send it via SMTP.

The background scheduler builds digests from each user's most recent cached data
(no service credentials needed) so it can run unattended. The /api/digest/test
endpoint uses the live session so a user can preview a full digest immediately.
"""
