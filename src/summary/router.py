"""Dashboard pages, personal API, summary text, and exports."""

import csv
import hashlib
import io
import time

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, Response, PlainTextResponse

from config import DEFAULT_MONTHS, VALID_MONTHS, TIME_RANGE_OPTIONS, JIRA_URL
from templates import templates, _template_context, _render_template_string
from auth.dependencies import require_session
from summary.service import get_personal_summary

router = APIRouter()

# In-process cache for generated AI summaries: {(user_id, range, content_sig): (ts, text)}
_AI_SUMMARY_CACHE = {}
_AI_CACHE_TTL_SECONDS = 3600


@router.get("/insights", name="insights_page")
async def insights_page(request: Request, session: dict = Depends(require_session)):
    ctx = _template_context(request, current_route="insights_page")
    return templates.TemplateResponse("insights.html", ctx)


def _apply_time_range_from_query(request: Request):
    """If request has ?months= in VALID_MONTHS, set session and return True."""
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
        return True
    return False


@router.get("/", name="index")
async def index(request: Request, session: dict = Depends(require_session)):
    current_user = {
        "id": session.get("user_id"),
        "name": session.get("user_name"),
        "email": session.get("user_email"),
        "team": "",
    }
    ctx = _template_context(request, current_route="index", current_user=current_user)
    return templates.TemplateResponse("index.html", ctx)


@router.get("/gerrit", name="gerrit_full")
async def gerrit_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="gerrit_full",
        gerrit=data["gerrit"],
        gerrit_error=data.get("gerrit_error"),
        gerrit_metrics=data.get("gerrit_metrics") or {},
        totals=data.get("totals") or {},
        monthly=data.get("monthly") or [],
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("gerrit_full.html", ctx)


@router.get("/jira", name="jira_full")
async def jira_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="jira_full",
        jira=data["jira"],
        jira_error=data.get("jira_error"),
        jira_connected=data.get("jira_connected"),
        jira_metrics=data.get("jira_metrics") or {},
        totals=data.get("totals") or {},
        monthly=data.get("monthly") or [],
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
        jira_url=JIRA_URL or "",
    )
    return templates.TemplateResponse("jira_full.html", ctx)


@router.get("/confluence", name="confluence_full")
async def confluence_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="confluence_full",
        confluence=data["confluence"],
        confluence_error=data.get("confluence_error"),
        confluence_connected=data.get("confluence_connected"),
        confluence_metrics=data.get("confluence_metrics") or {},
        totals=data.get("totals") or {},
        monthly=data.get("monthly") or [],
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("confluence_full.html", ctx)


@router.get("/slack", name="slack_full")
async def slack_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="slack_full",
        slack=data["slack"],
        slack_error=data.get("slack_error"),
        slack_connected=data.get("slack_connected"),
        slack_metrics=data.get("slack_metrics") or {},
        totals=data.get("totals") or {},
        monthly=data.get("monthly") or [],
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("slack_full.html", ctx)


@router.get("/outlook", name="outlook_full")
async def outlook_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="outlook_full",
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("outlook_full.html", ctx)


@router.get("/teams", name="teams_full")
async def teams_full(request: Request, session: dict = Depends(require_session)):
    _apply_time_range_from_query(request)
    data = get_personal_summary(dict(session))
    ctx = _template_context(
        request,
        current_route="teams_full",
        months=data.get("months", DEFAULT_MONTHS),
        time_range_label=data.get("time_range_label", "Last 12 months"),
        time_range_options=data.get("time_range_options", TIME_RANGE_OPTIONS),
        time_filter_path=request.url.path,
    )
    return templates.TemplateResponse("teams_full.html", ctx)


@router.get("/api/personal")
async def api_personal(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    force_refresh = bool(request.query_params.get("refresh"))
    data = get_personal_summary(dict(session), force_refresh=force_refresh)
    return JSONResponse(data)


@router.get("/api/summary-text")
async def api_summary_text(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    user = data.get("user") or {}
    totals = data.get("totals") or {}
    time_range_label = data.get("time_range_label", "Last 12 months")
    themes = data.get("themes") or []
    top_themes = themes[:5]
    theme_str = (
        ", ".join("%s (%s)" % (t.get("name", ""), t.get("count", 0)) for t in top_themes)
        if top_themes
        else "—"
    )
    jm = data.get("jira_metrics") or {}
    gm = data.get("gerrit_metrics") or {}
    parts = [
        "In %s: %s closed %s tickets and merged %s changes."
        % (time_range_label, user.get("name", "I"), totals.get("jira", 0), totals.get("gerrit", 0))
    ]
    if totals.get("confluence"):
        parts.append("Updated %s Confluence pages." % totals["confluence"])
    if totals.get("slack"):
        parts.append("Sent %s Slack messages." % totals["slack"])
    if jm.get("done_count") is not None:
        parts.append(
            "Jira: %s done (%s%% done rate)."
            % (jm.get("done_count", 0), jm.get("done_rate_pct", 0))
        )
    if gm.get("merged_count") is not None:
        parts.append(
            "Gerrit: %s merged (%s%% merge rate)."
            % (gm.get("merged_count", 0), gm.get("merge_rate_pct", 0))
        )
    if top_themes:
        parts.append("Top areas: %s." % theme_str)
    pc = data.get("period_comparison")
    if pc:
        c, p = pc.get("current_6m") or {}, pc.get("previous_6m") or {}
        if (c.get("jira", 0) + c.get("gerrit", 0)) and (p.get("jira", 0) + p.get("gerrit", 0)):
            delta = (c.get("jira", 0) + c.get("gerrit", 0)) - (
                p.get("jira", 0) + p.get("gerrit", 0)
            )
            trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
            parts.append("Last 6 months vs previous 6: delivery %s." % trend)
    highlights = data.get("highlights") or []
    if highlights:
        parts.append("")
        parts.extend("• " + h for h in highlights)
    return PlainTextResponse("\n".join(parts))


@router.get("/api/ai-summary")
async def api_ai_summary(request: Request, session: dict = Depends(require_session)):
    """LLM-written narrative of what the user worked on, from their activity.

    Reuses the OpenAI-compatible client, so it also works against a local model
    (point OPENAI_BASE_URL at e.g. http://localhost:11434/v1) — no code change.
    The generated narrative is cached per (user, time range, content) for an hour.
    """
    data = get_personal_summary(dict(session))
    gerrit = data.get("gerrit") or []
    jira = data.get("jira") or []
    confluence = data.get("confluence") or []

    commits = [c.get("message") for c in gerrit if c.get("message")]
    jira_titles = [
        "{} {}".format(t.get("key", ""), t.get("title", "")).strip() for t in jira if t.get("title")
    ]
    confluence_titles = [p.get("title") for p in confluence if p.get("title")]

    if not (commits or jira_titles or confluence_titles):
        return JSONResponse(
            {
                "ok": False,
                "configured": True,
                "error": "No activity to summarize yet. Connect a service and refresh.",
            }
        )

    # Cache key from the user, time range, and a hash of the input content.
    sig = hashlib.sha256(
        (
            "|".join(commits) + "##" + "|".join(jira_titles) + "##" + "|".join(confluence_titles)
        ).encode("utf-8")
    ).hexdigest()
    cache_key = (session.get("user_id"), data.get("time_range_label", ""), sig)
    cached = _AI_SUMMARY_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _AI_CACHE_TTL_SECONDS:
        return JSONResponse(
            {
                "ok": True,
                "configured": True,
                "cached": True,
                "narrative": cached[1],
                "time_range_label": data.get("time_range_label", ""),
            }
        )

    try:
        from clients.llm import combined_year_in_review, LLMError
    except Exception:
        return JSONResponse(
            {"ok": False, "configured": False, "error": "LLM client is unavailable."}
        )

    try:
        narrative = combined_year_in_review(
            commits=commits,
            confluence_titles=confluence_titles,
            jira_titles=jira_titles,
        )
    except LLMError as exc:
        configured = "No LLM configured" not in str(exc)
        return JSONResponse({"ok": False, "configured": configured, "error": str(exc)})

    if not narrative or not narrative.strip():
        return JSONResponse(
            {"ok": False, "configured": True, "error": "The model returned no summary."}
        )

    narrative = narrative.strip()
    _AI_SUMMARY_CACHE[cache_key] = (time.time(), narrative)
    return JSONResponse(
        {
            "ok": True,
            "configured": True,
            "cached": False,
            "narrative": narrative,
            "time_range_label": data.get("time_range_label", ""),
        }
    )


def _build_qa_context(data):
    """Compact, readable text version of the user's summary to ground the LLM's answers."""
    lines = []
    u = data.get("user") or {}
    lines.append("Person: {} <{}>".format(u.get("name", ""), u.get("email", "")))
    lines.append("Time range: {}".format(data.get("time_range_label", "")))
    t = data.get("totals") or {}
    lines.append(
        "Totals — Jira tickets: {}, Gerrit changes: {}, Confluence pages: {}, Slack messages: {}".format(
            t.get("jira", 0), t.get("gerrit", 0), t.get("confluence", 0), t.get("slack", 0)
        )
    )
    themes = data.get("themes") or []
    if themes:
        lines.append(
            "Top areas/projects: "
            + ", ".join("{} ({})".format(x.get("name"), x.get("count")) for x in themes[:10])
        )
    jm = data.get("jira_metrics") or {}
    if jm:
        lines.append(
            "Jira metrics — done: {}, open: {}, done rate: {}%, median days to resolution: {}".format(
                jm.get("done_count"),
                jm.get("open_count"),
                jm.get("done_rate_pct"),
                jm.get("median_resolution_days"),
            )
        )
    gm = data.get("gerrit_metrics") or {}
    if gm:
        lines.append(
            "Gerrit metrics — merged: {}, open: {}, abandoned: {}, merge rate: {}%, median days to merge: {}".format(
                gm.get("merged_count"),
                gm.get("open_count"),
                gm.get("abandoned_count"),
                gm.get("merge_rate_pct"),
                gm.get("median_days_to_merge"),
            )
        )
    monthly = data.get("monthly") or []
    if monthly:
        lines.append("Monthly activity (month: jira/gerrit/confluence/slack):")
        for m in monthly[-24:]:
            lines.append(
                "  {}: {}/{}/{}/{}".format(
                    m.get("month"),
                    m.get("jira_count", 0),
                    m.get("gerrit_count", 0),
                    m.get("confluence_count", 0),
                    m.get("slack_count", 0),
                )
            )
    pc = data.get("period_comparison")
    if pc:
        c, p = pc.get("current_6m") or {}, pc.get("previous_6m") or {}
        lines.append(
            "Last 6 months vs previous 6 — jira {} vs {}, gerrit {} vs {}, slack {} vs {}".format(
                c.get("jira"),
                p.get("jira"),
                c.get("gerrit"),
                p.get("gerrit"),
                c.get("slack"),
                p.get("slack"),
            )
        )
    smly = data.get("same_month_last_year")
    if smly:
        cur, prev = smly.get("current") or {}, smly.get("previous") or {}
        lines.append(
            "{} vs {} — jira {} vs {}, gerrit {} vs {}, confluence {} vs {}, slack {} vs {}".format(
                smly.get("current_label"),
                smly.get("previous_label"),
                cur.get("jira"),
                prev.get("jira"),
                cur.get("gerrit"),
                prev.get("gerrit"),
                cur.get("confluence"),
                prev.get("confluence"),
                cur.get("slack"),
                prev.get("slack"),
            )
        )
    hl = data.get("highlights") or []
    if hl:
        lines.append("Highlights: " + " | ".join(str(h) for h in hl))
    nud = data.get("nudges") or []
    if nud:
        lines.append("Reminders: " + " | ".join((n or {}).get("message", "") for n in nud))
    objs = data.get("objectives") or []
    if objs:
        lines.append("Objectives:")
        for o in objs[:15]:
            lines.append(
                "  - {} [status: {}, progress: {}%]".format(
                    o.get("title", ""), o.get("status", ""), o.get("progress", 0)
                )
            )
    gerrit = data.get("gerrit") or []
    if gerrit:
        lines.append("Recent Gerrit change subjects:")
        for c in gerrit[:30]:
            lines.append("  - {} ({})".format((c.get("message") or "")[:120], c.get("project", "")))
    jira = data.get("jira") or []
    if jira:
        lines.append("Recent Jira tickets:")
        for j in jira[:30]:
            lines.append(
                "  - {} {} ({})".format(
                    j.get("key", ""), (j.get("title") or "")[:120], j.get("project", "")
                )
            )
    confluence = data.get("confluence") or []
    if confluence:
        lines.append("Recent Confluence pages:")
        for p in confluence[:20]:
            lines.append("  - {}".format((p.get("title") or "")[:120]))
    return "\n".join(lines)[:12000]


@router.post("/api/ask")
async def api_ask(request: Request, session: dict = Depends(require_session)):
    """Answer a free-form question grounded in the user's own fetched data (local LLM)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    question = (payload.get("question") or "").strip()
    if not question:
        return JSONResponse({"ok": False, "error": "Please enter a question."}, status_code=400)
    history = payload.get("history") if isinstance(payload.get("history"), list) else []

    data = get_personal_summary(dict(session))
    if not (data.get("gerrit") or data.get("jira") or data.get("confluence") or data.get("slack")):
        return JSONResponse(
            {
                "ok": False,
                "configured": True,
                "error": "No activity to answer from yet. Connect a service and refresh.",
            }
        )

    context = _build_qa_context(data)
    try:
        from clients.llm import answer_question, LLMError
    except Exception:
        return JSONResponse(
            {"ok": False, "configured": False, "error": "LLM client is unavailable."}
        )

    try:
        answer = answer_question(question, context, history=history)
    except LLMError as exc:
        configured = "No LLM configured" not in str(exc)
        return JSONResponse({"ok": False, "configured": configured, "error": str(exc)})

    if not answer or not answer.strip():
        return JSONResponse(
            {"ok": False, "configured": True, "error": "The model returned no answer."}
        )

    return JSONResponse({"ok": True, "configured": True, "answer": answer.strip()})


@router.get("/export/onepager")
async def export_onepager(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    themes = data.get("themes") or []
    top_projects = themes[:3]
    trend_line = None
    pc = data.get("period_comparison")
    if pc:
        c, p = pc.get("current_6m") or {}, pc.get("previous_6m") or {}
        jc, jp = c.get("jira", 0), p.get("jira", 0)
        gc, gp = c.get("gerrit", 0), p.get("gerrit", 0)
        total_p = jp + gp
        if total_p > 0:
            pct = round(100 * (jc + gc - jp - gp) / total_p)
            trend_line = (
                "Last 6 months: {} tickets, {} changes. Previous 6: {}, {}. {}% {}.".format(
                    jc, gc, jp, gp, abs(pct), "up" if pct >= 0 else "down"
                )
            )
        else:
            trend_line = "Last 6 months: {} tickets, {} changes.".format(jc, gc)
    html = _render_template_string(
        "export_onepager.html",
        user=data.get("user") or {},
        totals=data.get("totals") or {},
        time_range_label=data.get("time_range_label", "Last 12 months"),
        top_projects=top_projects,
        trend_line=trend_line,
    )
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration

        font_config = FontConfiguration()
        pdf_bytes = HTML(string=html).write_pdf(font_config=font_config)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=work-wrapped-onepager.pdf"},
        )
    except Exception as e:
        return PlainTextResponse(
            "One-pager PDF failed (WeasyPrint error: {}). Try the full PDF or print from browser.".format(
                str(e)
            ),
            status_code=503,
        )


@router.get("/export/pdf")
async def export_pdf(request: Request, session: dict = Depends(require_session)):
    data = get_personal_summary(dict(session))
    html = _render_template_string(
        "export_print.html",
        user=data.get("user") or {},
        totals=data.get("totals") or {},
        time_range_label=data.get("time_range_label", "Last 12 months"),
        monthly=data.get("monthly") or [],
        themes=data.get("themes") or [],
        gerrit_metrics=data.get("gerrit_metrics") or {},
        jira_metrics=data.get("jira_metrics") or {},
    )
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration

        font_config = FontConfiguration()
        pdf_bytes = HTML(string=html).write_pdf(font_config=font_config)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=work-wrapped.pdf"},
        )
    except Exception as e:
        return PlainTextResponse(
            "PDF export failed (WeasyPrint error: {}). Try printing the dashboard from your browser (Print → Save as PDF).".format(
                str(e)
            ),
            status_code=503,
        )


@router.get("/api/export/json")
async def export_json(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    data = get_personal_summary(dict(session))
    return JSONResponse(
        data,
        headers={"Content-Disposition": "attachment; filename=work-wrapped.json"},
    )


@router.get("/api/export/csv")
async def export_csv(request: Request, session: dict = Depends(require_session)):
    try:
        months_param = int(request.query_params.get("months"))
    except (TypeError, ValueError):
        months_param = None
    if months_param is not None and months_param in VALID_MONTHS:
        request.session["months"] = months_param
    data = get_personal_summary(dict(session))
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(
        [
            "type",
            "key_or_id",
            "title_or_message",
            "status",
            "project_or_space_or_channel",
            "month",
            "link",
        ]
    )
    for t in data.get("jira") or []:
        w.writerow(
            [
                "jira",
                t.get("key", ""),
                (t.get("title") or "")[:200],
                t.get("status", ""),
                t.get("project", ""),
                t.get("month", ""),
                "",
            ]
        )
    for c in data.get("gerrit") or []:
        w.writerow(
            [
                "gerrit",
                c.get("number", ""),
                (c.get("message") or "")[:200],
                c.get("status", ""),
                c.get("project", ""),
                c.get("month", ""),
                "",
            ]
        )
    for p in data.get("confluence") or []:
        w.writerow(
            [
                "confluence",
                p.get("id", ""),
                (p.get("title") or "")[:200],
                "",
                p.get("space") or p.get("space_key", ""),
                p.get("month", ""),
                p.get("link", ""),
            ]
        )
    for s in data.get("slack") or []:
        w.writerow(
            [
                "slack",
                "",
                (s.get("text") or "")[:200],
                "",
                s.get("channel_name") or s.get("channel_id", ""),
                s.get("month", ""),
                s.get("link", ""),
            ]
        )
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=work-wrapped.csv"},
    )
