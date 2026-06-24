"""Digest routes: send a test digest to yourself now."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from config import smtp_configured
from auth.dependencies import require_session
from digest.service import send_digest_for_user

router = APIRouter()


@router.post("/api/digest/test")
async def api_digest_test(request: Request, session: dict = Depends(require_session)):
    email = session.get("user_email")
    if not email:
        return JSONResponse(
            {"ok": False, "error": "Your account has no email address."}, status_code=400
        )
    if not smtp_configured():
        return JSONResponse(
            {
                "ok": False,
                "configured": False,
                "error": "Email is not configured. Set SMTP_HOST (and related) in .env, then restart.",
            }
        )
    user = {
        "id": session.get("user_id"),
        "name": session.get("user_name", ""),
        "email": email,
    }
    ok, err = send_digest_for_user(user, "test", session_data=dict(session))
    if ok:
        return JSONResponse({"ok": True, "sent_to": email})
    return JSONResponse({"ok": False, "configured": True, "error": err or "Send failed."})
