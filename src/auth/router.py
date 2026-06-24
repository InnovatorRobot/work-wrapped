"""Auth routes: login, signup, logout, demo."""

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from config import DEMO_MODE, DEFAULT_MONTHS
from templates import templates, _template_context
from auth.service import authenticate_user, create_user, _establish_session
from settings.service import get_user_settings

router = APIRouter()


@router.get("/login", name="login")
async def login_get(request: Request):
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    ctx = _template_context(
        request,
        error=None,
        active_tab="signin",
        demo_mode=DEMO_MODE,
    )
    return templates.TemplateResponse("login.html", ctx)


@router.post("/login")
async def login_post(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
):
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    error = None
    email = (email or "").strip()
    if not email or not password:
        error = "Email and password are required."
    else:
        user = authenticate_user(email, password)
        if not user:
            error = "Invalid email or password."
        else:
            _establish_session(request, user)
            next_url = request.query_params.get("next") or request.app.url_path_for("index")
            return RedirectResponse(url=next_url, status_code=303)
    ctx = _template_context(
        request, error=error, active_tab="signin", prefill_email=email, demo_mode=DEMO_MODE
    )
    return templates.TemplateResponse("login.html", ctx)


@router.post("/signup", name="signup")
async def signup_post(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
):
    if "user_id" in request.session:
        return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    error = None
    email = (email or "").strip()
    if password != password2:
        error = "Passwords do not match."
    else:
        user, error = create_user(email, password, name)
        if user and not error:
            _establish_session(request, user)
            return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)
    ctx = _template_context(
        request,
        error=error,
        active_tab="signup",
        prefill_email=email,
        prefill_name=(name or "").strip(),
        demo_mode=DEMO_MODE,
    )
    return templates.TemplateResponse("login.html", ctx)


@router.get("/logout", name="logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=request.app.url_path_for("login"), status_code=303)


@router.get("/demo", name="demo_login")
async def demo_login(request: Request):
    """Enter a sample session to explore the UI without connecting real services.
    Only available when DEMO_MODE is enabled."""
    if not DEMO_MODE:
        return RedirectResponse(url=request.app.url_path_for("login"), status_code=303)
    request.session.clear()
    request.session["user_id"] = "demo"
    request.session["user_name"] = "Demo User"
    request.session["user_email"] = "demo@example.com"
    request.session["demo_mode"] = True
    settings = get_user_settings("demo")
    request.session["months"] = settings.get("default_months", DEFAULT_MONTHS)
    return RedirectResponse(url=request.app.url_path_for("index"), status_code=303)


