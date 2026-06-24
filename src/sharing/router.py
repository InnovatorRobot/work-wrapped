"""Sharing routes: snapshots and shareable links."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from templates import templates, _template_context
from auth.dependencies import require_session
from sharing.service import get_snapshots, save_snapshot, save_share_link, get_share_link
from summary.service import get_personal_summary

router = APIRouter()


@router.get("/api/snapshots")
async def api_snapshots_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse(get_snapshots(session.get("user_id")))


@router.post("/api/snapshots")
async def api_snapshots_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    user_id = session.get("user_id")
    label = (payload.get("label") or "").strip() or "Snapshot"
    data = get_personal_summary(dict(session))
    snap = save_snapshot(user_id, label, data.get("totals") or {})
    if not snap:
        return JSONResponse({"error": "Label required"}, status_code=400)
    return JSONResponse({"snapshot": snap, "snapshots": get_snapshots(user_id)})


@router.get("/share/{token}", name="share_view")
async def share_view(request: Request, token: str):
    record = get_share_link(token)
    if not record:
        return templates.TemplateResponse(
            "share_expired.html", _template_context(request), status_code=404
        )
    ctx = _template_context(
        request,
        user=record.get("user") or {},
        totals=record.get("totals") or {},
        time_range_label=record.get("time_range_label", "Last 12 months"),
        themes=record.get("themes") or [],
        highlights=record.get("highlights") or [],
        monthly=record.get("monthly") or [],
        created_at=record.get("created_at", ""),
    )
    return templates.TemplateResponse("share_view.html", ctx)


@router.post("/api/share")
async def api_share(request: Request, session: dict = Depends(require_session)):
    user_id = session.get("user_id")
    data = get_personal_summary(dict(session))
    token = save_share_link(user_id, data)
    if not token:
        return JSONResponse({"error": "Could not create link"}, status_code=500)
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"url": base + "/share/" + token, "token": token})


