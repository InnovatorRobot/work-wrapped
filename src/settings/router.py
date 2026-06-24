"""Settings routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from config import TIME_RANGE_OPTIONS, VALID_MONTHS
from templates import templates, _template_context
from auth.dependencies import require_session
from settings.service import get_user_settings, set_user_settings
from team.service import get_team_optin

router = APIRouter()


@router.get("/settings", name="settings_page")
async def settings_page(request: Request, session: dict = Depends(require_session)):
    settings = get_user_settings(session.get("user_id"))
    ctx = _template_context(
        request,
        current_route="settings_page",
        settings=settings,
        team_optin=get_team_optin(session.get("user_id")),
        time_range_options=TIME_RANGE_OPTIONS,
    )
    return templates.TemplateResponse("settings.html", ctx)


@router.get("/api/settings")
async def api_settings_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse(get_user_settings(session.get("user_id")))


@router.post("/api/settings")
async def api_settings_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    saved = set_user_settings(session.get("user_id"), payload)
    # Apply the default time range to the active session immediately.
    if saved.get("default_months") in VALID_MONTHS:
        request.session["months"] = saved["default_months"]
    return JSONResponse({"ok": True, "settings": saved})


