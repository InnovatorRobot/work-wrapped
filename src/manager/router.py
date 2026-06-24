"""Manager routes: view reports' goals/1:1s and post comments (both sides)."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from templates import templates, _template_context
from auth.dependencies import require_session
from manager.service import get_reports, add_comment, get_comments, is_manager_of

router = APIRouter()


def _can_access(session, owner_id):
    """Owner themselves, or the report's opted-in manager."""
    if not owner_id:
        return False
    if str(session.get("user_id")) == str(owner_id):
        return True
    return is_manager_of(session.get("user_email", ""), owner_id)


@router.get("/manager", name="manager_page")
async def manager_page(request: Request, session: dict = Depends(require_session)):
    reports = get_reports(session.get("user_email", ""))
    ctx = _template_context(request, current_route="manager_page", reports=reports)
    return templates.TemplateResponse("manager.html", ctx)


@router.get("/api/manager/reports")
async def api_manager_reports(request: Request, session: dict = Depends(require_session)):
    return JSONResponse({"reports": get_reports(session.get("user_email", ""))})


@router.get("/api/comments")
async def api_comments_get(request: Request, session: dict = Depends(require_session)):
    owner_id = request.query_params.get("owner_id")
    kind = request.query_params.get("kind")
    target_id = request.query_params.get("target_id")
    if not _can_access(session, owner_id):
        return JSONResponse({"ok": False, "error": "Not allowed."}, status_code=403)
    return JSONResponse({"ok": True, "comments": get_comments(owner_id, kind, target_id)})


@router.post("/api/comments")
async def api_comments_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    owner_id = payload.get("owner_id")
    kind = payload.get("kind")
    target_id = payload.get("target_id")
    text = payload.get("text")
    if not _can_access(session, owner_id):
        return JSONResponse({"ok": False, "error": "Not allowed."}, status_code=403)
    comment = add_comment(
        owner_id,
        kind,
        target_id,
        author_id=session.get("user_id"),
        author_name=session.get("user_name", ""),
        text=text,
    )
    if not comment:
        return JSONResponse({"ok": False, "error": "Invalid comment."}, status_code=400)
    return JSONResponse({"ok": True, "comment": comment})
