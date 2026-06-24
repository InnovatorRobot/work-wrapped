"""Connection routes: connect/disconnect each service."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from config import GERRIT_URL, JIRA_URL, CONFLUENCE_URL
from templates import templates, _template_context
from auth.dependencies import require_session
from connections.service import get_session_connections
from connections.credentials import (
    set_credentials,
    delete_credentials,
    session_with_credentials,
    _FIELD_MAP,
)
from clients import (
    get_gerrit_client,
    get_jira_client,
    get_confluence_client,
    get_slack_client,
    GerritError,
    JiraError,
    ConfluenceError,
    SlackError,
)
from summary.cache import invalidate_service_cache

router = APIRouter()


@router.get("/connections", name="connections_page")
async def connections_page(request: Request, session: dict = Depends(require_session)):
    ctx = _template_context(
        request,
        current_route="connections_page",
        connections=get_session_connections(session_with_credentials(dict(session))),
    )
    return templates.TemplateResponse("connections.html", ctx)


@router.get("/api/connections")
async def api_connections(request: Request, session: dict = Depends(require_session)):
    """Connection status per service (for the React UI)."""
    return JSONResponse(get_session_connections(session_with_credentials(dict(session))))


@router.post("/api/connect/gerrit")
async def api_connect_gerrit(request: Request, session: dict = Depends(require_session)):
    if not GERRIT_URL:
        return JSONResponse(
            {"ok": False, "error": "Gerrit is not configured on the server."}, status_code=400
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username or not password:
        return JSONResponse(
            {"ok": False, "error": "Username and HTTP password are required."}, status_code=400
        )
    try:
        client = get_gerrit_client()
        client.authenticate(username, password)
    except GerritError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    set_credentials(session.get("user_id"), "gerrit", {"username": username, "password": password})
    request.session.pop("gerrit_username", None)
    request.session.pop("gerrit_password", None)
    invalidate_service_cache(session.get("user_id"))
    return JSONResponse({"ok": True, "identifier": username})


@router.post("/api/connect/jira")
async def api_connect_jira(request: Request, session: dict = Depends(require_session)):
    if not JIRA_URL:
        return JSONResponse(
            {"ok": False, "error": "Jira is not configured on the server."}, status_code=400
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    email = (payload.get("email") or "").strip()
    token = payload.get("api_token") or ""
    if not email or not token:
        return JSONResponse(
            {"ok": False, "error": "Email and password/API token are required."}, status_code=400
        )
    try:
        me = get_jira_client().get_myself(email, token)
        if not me:
            return JSONResponse(
                {"ok": False, "error": "Could not verify Jira credentials."}, status_code=400
            )
    except JiraError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    set_credentials(session.get("user_id"), "jira", {"email": email, "api_token": token})
    request.session.pop("jira_email", None)
    request.session.pop("jira_api_token", None)
    invalidate_service_cache(session.get("user_id"))
    return JSONResponse({"ok": True, "identifier": email})


@router.post("/api/connect/confluence")
async def api_connect_confluence(request: Request, session: dict = Depends(require_session)):
    if not CONFLUENCE_URL:
        return JSONResponse(
            {"ok": False, "error": "Confluence is not configured on the server."}, status_code=400
        )
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    email = (payload.get("email") or "").strip()
    token = payload.get("api_token") or ""
    if not email or not token:
        return JSONResponse(
            {"ok": False, "error": "Email and password/API token are required."}, status_code=400
        )
    try:
        me = get_confluence_client().get_current_user((email, token))
        if not me:
            return JSONResponse(
                {"ok": False, "error": "Could not verify Confluence credentials."}, status_code=400
            )
    except ConfluenceError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    set_credentials(session.get("user_id"), "confluence", {"email": email, "api_token": token})
    request.session.pop("confluence_email", None)
    request.session.pop("confluence_api_token", None)
    invalidate_service_cache(session.get("user_id"))
    return JSONResponse({"ok": True, "identifier": email})


@router.post("/api/connect/slack")
async def api_connect_slack(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    token = (payload.get("token") or "").strip()
    if not token:
        return JSONResponse(
            {"ok": False, "error": "A Slack User OAuth Token is required."}, status_code=400
        )
    try:
        info = get_slack_client().auth_test(token)
    except SlackError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    set_credentials(
        session.get("user_id"), "slack", {"token": token, "name": (info or {}).get("user", "")}
    )
    request.session.pop("slack_token", None)
    request.session.pop("slack_name", None)
    invalidate_service_cache(session.get("user_id"))
    return JSONResponse({"ok": True, "identifier": (info or {}).get("user", "")})


@router.post("/api/disconnect/{service}")
async def api_disconnect(service: str, request: Request, session: dict = Depends(require_session)):
    if service not in _FIELD_MAP:
        return JSONResponse({"ok": False, "error": "Unknown service."}, status_code=404)
    delete_credentials(session.get("user_id"), service)
    for _, skey in _FIELD_MAP[service]:
        request.session.pop(skey, None)
    invalidate_service_cache(session.get("user_id"))
    return JSONResponse({"ok": True})
