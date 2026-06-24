"""Jinja2 templates and shared template-context helpers."""

from fastapi import Request
from fastapi.templating import Jinja2Templates

from config import FRONTEND_DIR, app_version

templates = Jinja2Templates(directory=FRONTEND_DIR)


def _template_context(request: Request, current_route=None, **kwargs):
    """Build context for Jinja2 with request, session, url_for, app_version."""

    def url_for(name: str, **path_params):
        if name == "static":
            return "/static/" + (path_params.get("filename") or "")
        return request.app.url_path_for(name, **path_params)

    ctx = {
        "request": request,
        "session": request.session,
        "url_for": url_for,
        "app_version": app_version(),
        **kwargs,
    }
    if current_route is not None:
        ctx["current_route"] = current_route
    return ctx


def _render_template_string(template_name: str, **context):
    """Render a template to string (for export/WeasyPrint)."""
    return templates.env.get_template(template_name).render(**context)
