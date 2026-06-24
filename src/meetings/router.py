"""1:1 meetings routes: the page plus a small REST API.

New meetings get their agenda auto-seeded from the user's summary highlights and
nudges, the manager is pulled from settings, and open action items are carried
forward from the previous 1:1 (handled in the service layer).
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from templates import templates, _template_context
from auth.dependencies import require_session
from settings.service import get_user_settings
from summary.service import get_personal_summary
from meetings.service import (
    get_meetings,
    get_meeting,
    create_meeting,
    update_meeting,
    delete_meeting,
)

router = APIRouter()


def _seed_agenda_from_summary(session_data):
    """Build suggested agenda lines from the user's summary highlights + nudges."""
    try:
        summary = get_personal_summary(dict(session_data))
    except Exception:
        return []
    lines = []
    for h in summary.get("highlights") or []:
        if isinstance(h, str) and h.strip():
            lines.append(h.strip())
    for n in summary.get("nudges") or []:
        msg = (n or {}).get("message")
        if msg and msg.strip():
            lines.append(msg.strip())
    seen, out = set(), []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out[:8]


@router.get("/meetings", name="meetings_page")
async def meetings_page(request: Request, session: dict = Depends(require_session)):
    ctx = _template_context(request, current_route="meetings_page")
    return templates.TemplateResponse("meetings.html", ctx)


@router.get("/api/meetings")
async def api_meetings_list(request: Request, session: dict = Depends(require_session)):
    return JSONResponse({"meetings": get_meetings(session.get("user_id"))})


@router.get("/api/meetings/{meeting_id}")
async def api_meeting_get(
    meeting_id: str, request: Request, session: dict = Depends(require_session)
):
    meeting = get_meeting(session.get("user_id"), meeting_id)
    if not meeting:
        return JSONResponse({"ok": False, "error": "Meeting not found."}, status_code=404)
    return JSONResponse({"ok": True, "meeting": meeting})


@router.post("/api/meetings")
async def api_meeting_create(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    user_id = session.get("user_id")
    settings = get_user_settings(user_id)
    seed = _seed_agenda_from_summary(session) if payload.get("seed", True) else []
    meeting = create_meeting(
        user_id,
        title=payload.get("title", ""),
        date=payload.get("date", ""),
        manager_name=settings.get("manager_name", ""),
        manager_email=settings.get("manager_email", ""),
        seed_agenda=seed,
    )
    if not meeting:
        return JSONResponse({"ok": False, "error": "Could not create meeting."}, status_code=400)
    return JSONResponse({"ok": True, "meeting": meeting})


@router.post("/api/meetings/{meeting_id}")
async def api_meeting_update(
    meeting_id: str, request: Request, session: dict = Depends(require_session)
):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    meeting, error = update_meeting(session.get("user_id"), meeting_id, payload)
    if error:
        status = 404 if error == "Meeting not found." else 400
        return JSONResponse({"ok": False, "error": error}, status_code=status)
    return JSONResponse({"ok": True, "meeting": meeting})


@router.delete("/api/meetings/{meeting_id}")
async def api_meeting_delete(
    meeting_id: str, request: Request, session: dict = Depends(require_session)
):
    removed = delete_meeting(session.get("user_id"), meeting_id)
    if not removed:
        return JSONResponse({"ok": False, "error": "Meeting not found."}, status_code=404)
    return JSONResponse({"ok": True})
