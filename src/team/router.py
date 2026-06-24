"""Team view: aggregate (opt-in) totals & themes, plus CSV/PDF export."""

import csv
import io

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, Response, PlainTextResponse

from templates import templates, _template_context
from auth.dependencies import require_session
from team.service import get_team_optin, set_team_optin, get_team_summary

router = APIRouter()


@router.get("/api/team-comparison")
async def api_team_comparison_get(request: Request, session: dict = Depends(require_session)):
    return JSONResponse({"include": get_team_optin(session.get("user_id"))})


@router.post("/api/team-comparison")
async def api_team_comparison_post(request: Request, session: dict = Depends(require_session)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    set_team_optin(session.get("user_id"), payload.get("include", False))
    return JSONResponse({"include": get_team_optin(session.get("user_id"))})


@router.get("/api/team")
async def api_team(request: Request, session: dict = Depends(require_session)):
    team = request.query_params.get("team")
    return JSONResponse(get_team_summary(team))


@router.get("/team", name="team_page")
async def team_page(request: Request, session: dict = Depends(require_session)):
    ctx = _template_context(
        request,
        current_route="team_page",
        team=get_team_summary(),
        opted_in=get_team_optin(session.get("user_id")),
    )
    return templates.TemplateResponse("team.html", ctx)


@router.get("/api/team/export/csv")
async def team_export_csv(request: Request, session: dict = Depends(require_session)):
    t = get_team_summary()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["metric", "value"])
    w.writerow(["participants", t.get("participant_count", 0)])
    totals = t.get("totals") or {}
    average = t.get("average") or {}
    for k in ("jira", "gerrit", "confluence", "slack"):
        w.writerow(["total_" + k, totals.get(k, 0)])
        w.writerow(["avg_" + k, average.get(k, 0)])
    w.writerow([])
    w.writerow(["theme", "count"])
    for th in t.get("themes") or []:
        w.writerow([th.get("name", ""), th.get("count", 0)])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=team-summary.csv"},
    )


def _team_pdf_html(t):
    totals = t.get("totals") or {}
    average = t.get("average") or {}
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            k.capitalize(), totals.get(k, 0), average.get(k, 0)
        )
        for k in ("jira", "gerrit", "confluence", "slack")
    )
    themes = "".join(
        "<li>{} <span class='c'>({})</span></li>".format(th.get("name", ""), th.get("count", 0))
        for th in (t.get("themes") or [])
    )
    return """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    body{{font-family:sans-serif;color:#1a2232;margin:32px;}}
    h1{{font-size:22px;margin:0 0 4px;}} .sub{{color:#667;margin:0 0 20px;}}
    table{{border-collapse:collapse;width:100%;margin-bottom:20px;}}
    th,td{{border:1px solid #ccd;padding:8px 10px;text-align:left;font-size:13px;}}
    th{{background:#f2f5fb;}} ul{{columns:2;font-size:13px;}} .c{{color:#889;}}
    </style></head><body>
    <h1>Team Summary</h1>
    <p class="sub">{n} contributor(s) opted in. Aggregates only — no individual names.</p>
    <table><tr><th>Source</th><th>Team total</th><th>Average / person</th></tr>{rows}</table>
    <h3>Top team areas</h3><ul>{themes}</ul>
    </body></html>""".format(
        n=t.get("participant_count", 0), rows=rows, themes=themes or "<li>—</li>"
    )


@router.get("/team/export/pdf")
async def team_export_pdf(request: Request, session: dict = Depends(require_session)):
    html = _team_pdf_html(get_team_summary())
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration

        pdf_bytes = HTML(string=html).write_pdf(font_config=FontConfiguration())
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=team-summary.pdf"},
        )
    except Exception as e:
        return PlainTextResponse(
            "Team PDF failed (WeasyPrint error: {}). Use CSV or print from the browser.".format(e),
            status_code=503,
        )
