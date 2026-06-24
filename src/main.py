"""Application entrypoint: FastAPI app assembly and router wiring."""

import os
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import SECRET_KEY, FRONTEND_DIR, app_version, DEMO_MODE
from database import init_db
from auth.service import _migrate_json_users
from auth.dependencies import LoginRequired

_DEFAULT_SECRET = "dev-secret-key-change-in-production"
if (
    SECRET_KEY == _DEFAULT_SECRET
    and not DEMO_MODE
    and os.environ.get("ALLOW_INSECURE_SECRET", "").lower() not in ("1", "true", "yes")
):
    raise RuntimeError(
        "Refusing to start with the default SECRET_KEY. Set a strong SECRET_KEY in .env "
        '(e.g. `python3 -c "import secrets;print(secrets.token_hex(32))"`). '
        "For local dev you may set DEMO_MODE=true or ALLOW_INSECURE_SECRET=true."
    )

from auth.router import router as auth_router
from summary.router import router as summary_router
from settings.router import router as settings_router
from connections.router import router as connections_router
from goals.router import router as goals_router
from team.router import router as team_router
from sharing.router import router as sharing_router
from meetings.router import router as meetings_router
from manager.router import router as manager_router
from digest.router import router as digest_router

app = FastAPI(title="Work Wrapped")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", https_only=False)


@app.middleware("http")
async def _csrf_guard(request: Request, call_next):
    """Block cross-origin state-changing requests (CSRF). Pairs with SameSite=Lax."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if urlparse(origin).netloc and host and urlparse(origin).netloc != host:
                return JSONResponse(
                    {"ok": False, "error": "Cross-origin request blocked."}, status_code=403
                )
    return await call_next(request)


app.mount(
    "/static",
    StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")),
    name="static",
)


@app.on_event("startup")
def _on_startup():
    """Create database tables, migrate legacy users, and start the digest scheduler."""
    init_db()
    try:
        _migrate_json_users()
    except Exception:
        pass
    try:
        from digest.service import start_scheduler

        start_scheduler()
    except Exception:
        pass


@app.exception_handler(LoginRequired)
def _login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url="/login?next=" + quote(exc.next_url, safe="/"))


@app.get("/api/version")
async def api_version():
    return JSONResponse({"version": app_version()})


@app.get("/healthz")
async def healthz():
    """Liveness/readiness probe: checks the database is reachable."""
    status, code = "ok", 200
    try:
        from sqlalchemy import text
        from database import session_scope

        with session_scope() as s:
            s.execute(text("SELECT 1"))
    except Exception:
        status, code = "degraded", 503
    return JSONResponse({"status": status, "version": app_version()}, status_code=code)


app.include_router(auth_router)
app.include_router(summary_router)
app.include_router(settings_router)
app.include_router(connections_router)
app.include_router(goals_router)
app.include_router(team_router)
app.include_router(sharing_router)
app.include_router(meetings_router)
app.include_router(manager_router)
app.include_router(digest_router)
