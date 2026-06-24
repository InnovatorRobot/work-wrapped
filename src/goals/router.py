"""Goals and objectives routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from templates import templates, _template_context
from auth.dependencies import require_session
from goals.service import (
    get_goals,
    set_goals,
    get_objectives,
    add_objective,
    update_objective,
    delete_objective,
)

router = APIRouter()


@router.get("/goals", name="goals_page")
async def goals_page(request: Request, session: dict = Depends(require_session)):
    ctx = _template_context(request, current_route="goals_page")
    return templates.TemplateResponse("goals.html", ctx)


@router.get("/api/goals")
async def api_goals_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse(get_goals(session.get("user_id")))


@router.post("/api/goals")
async def api_goals_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    set_goals(session.get("user_id"), payload)
    return JSONResponse(get_goals(session.get("user_id")))


@router.get("/api/objectives")
async def api_objectives_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse({"objectives": get_objectives(session.get("user_id"))})


@router.post("/api/objectives")
async def api_objectives_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    obj, error = add_objective(session.get("user_id"), payload)
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    return JSONResponse({"ok": True, "objective": obj})


@router.post("/api/objectives/{obj_id}")
async def api_objectives_update(
    obj_id: str, request: Request, session: dict = Depends(require_session)
):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    obj, error = update_objective(session.get("user_id"), obj_id, payload)
    if error:
        status = 404 if error == "Objective not found." else 400
        return JSONResponse({"ok": False, "error": error}, status_code=status)
    return JSONResponse({"ok": True, "objective": obj})


@router.delete("/api/objectives/{obj_id}")
async def api_objectives_delete(
    obj_id: str, request: Request, session: dict = Depends(require_session)
):
    removed = delete_objective(session.get("user_id"), obj_id)
    if not removed:
        return JSONResponse({"ok": False, "error": "Objective not found."}, status_code=404)
    return JSONResponse({"ok": True})
