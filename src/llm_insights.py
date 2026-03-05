"""
LLM-backed insights for Work Wrapped: feed commit messages, Confluence titles,
and Jira ticket titles to an LLM and get themes, summaries, or other structured output.

Uses an OpenAI-compatible API. Set in .env:

  Option A — GitHub Copilot via local gateway (if you only have Copilot):
    Run a local proxy that uses your Copilot session (e.g. copilot-api on GitHub). Then:
    OPENAI_BASE_URL=http://127.0.0.1:3030/v1
    OPENAI_API_KEY=anything
    OPENAI_MODEL=gpt-4o
    (The api.githubcopilot.com endpoint does not accept Personal Access Tokens.)

  Option B — OpenAI (or same model family as Copilot):
    OPENAI_API_KEY=sk-...   (from https://platform.openai.com/api-keys)
    OPENAI_MODEL=gpt-4o     (or gpt-4o-mini)

  Option C — Azure OpenAI / Microsoft Copilot:
    OPENAI_API_KEY=<your-azure-api-key>
    OPENAI_BASE_URL=https://<your-resource>.openai.azure.com/openai/deployments/<deployment-name>
    OPENAI_MODEL=<deployment-name>
    OPENAI_USE_AZURE=true

"""

import os
import json
import requests

# Load .env from project root (parent of src/)
try:
    from dotenv import load_dotenv

    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _env_path = os.path.join(_root, ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

USE_COPILOT_LLM = os.environ.get("USE_COPILOT_LLM", "").lower() in ("1", "true", "yes")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_USE_AZURE = os.environ.get("OPENAI_USE_AZURE", "").lower() in ("1", "true", "yes")
MAX_INPUT_CHARS = 12000  # cap input size per call to avoid token limits

# Resolve which LLM backend to use and set base URL / auth
if USE_COPILOT_LLM and GITHUB_TOKEN:
    _LLM_BASE_URL = "https://api.githubcopilot.com"
    _LLM_API_KEY = GITHUB_TOKEN
    _LLM_USE_AZURE = False
elif OPENAI_API_KEY:
    _LLM_BASE_URL = OPENAI_BASE_URL or "https://api.openai.com/v1"
    _LLM_API_KEY = OPENAI_API_KEY
    _LLM_USE_AZURE = OPENAI_USE_AZURE
else:
    _LLM_BASE_URL = None
    _LLM_API_KEY = None
    _LLM_USE_AZURE = False


class LLMError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _call_llm(messages, max_tokens=800):
    """
    Call OpenAI-compatible chat completions API.
    messages: list of {"role": "system"|"user"|"assistant", "content": "..."}
    Returns response text or raises LLMError.
    """
    if not _LLM_API_KEY or not _LLM_BASE_URL:
        raise LLMError(
            "No LLM configured. Set USE_COPILOT_LLM=true and GITHUB_TOKEN=ghp_... in .env to use Copilot, "
            "or set OPENAI_API_KEY for OpenAI/Azure."
        )
    url = "{}/chat/completions".format(_LLM_BASE_URL)
    if _LLM_USE_AZURE:
        headers = {"api-key": _LLM_API_KEY, "Content-Type": "application/json"}
    else:
        headers = {
            "Authorization": "Bearer {}".format(_LLM_API_KEY),
            "Content-Type": "application/json",
        }
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    timeout_sec = 120 if ("127.0.0.1" in _LLM_BASE_URL or "localhost" in _LLM_BASE_URL) else 60
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    except requests.RequestException as e:
        raise LLMError("LLM request failed: {}".format(e))
    if r.status_code != 200:
        try:
            err = r.json()
            msg = err.get("error", {}).get("message", err.get("message", r.text[:200]))
        except Exception:
            msg = r.text[:200] if r.text else str(r.status_code)
        raise LLMError("LLM API error: {}".format(msg), r.status_code)
    data = r.json()
    choice = (data.get("choices") or [None])[0]
    if not choice:
        raise LLMError("LLM returned no choices")
    return (choice.get("message") or {}).get("content") or ""


def _truncate_lines(items, max_chars=MAX_INPUT_CHARS, prefix="- "):
    """Turn list of strings into a single block, truncating if too long."""
    lines = []
    total = 0
    for i, s in enumerate(items):
        line = prefix + (s or "").strip()
        if not line.strip():
            continue
        if total + len(line) + 1 > max_chars:
            lines.append("... ({} more items truncated)".format(len(items) - i))
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "(no items)"


def insights_from_commits(commit_messages, max_items=200):
    """
    Feed commit messages (e.g. Gerrit change subjects) to the LLM.
    Returns a string: themes and a short narrative summary.
    """
    if not commit_messages:
        return None
    text = _truncate_lines(commit_messages[:max_items], MAX_INPUT_CHARS)
    system = (
        "You are a helpful assistant that analyzes software development activity. "
        "Given a list of commit/change messages, identify 3–5 main themes or focus areas "
        "and write a very short narrative paragraph (2–4 sentences) summarizing what this work is about. "
        "Be concise and factual; no fluff."
    )
    user = (
        "Here are commit/change messages from the last 12 months:\n\n{}\n\n"
        "List the main themes (bullet points) and then a short summary paragraph."
    ).format(text)
    return _call_llm([{"role": "system", "content": system}, {"role": "user", "content": user}])


def insights_from_confluence_titles(titles, max_items=200):
    """
    Feed Confluence page titles to the LLM.
    Returns a string: themes and a short summary of documentation focus.
    """
    if not titles:
        return None
    text = _truncate_lines(titles[:max_items], MAX_INPUT_CHARS)
    system = (
        "You are a helpful assistant that analyzes documentation and knowledge base activity. "
        "Given a list of Confluence page titles, identify 3–5 main themes or topics "
        "and write a very short paragraph (2–4 sentences) summarizing what areas this person documented or contributed to. "
        "Be concise and factual."
    )
    user = (
        "Here are Confluence page titles (created or updated by the user) from the last 12 months:\n\n{}\n\n"
        "List the main themes (bullet points) and then a short summary paragraph."
    ).format(text)
    return _call_llm([{"role": "system", "content": system}, {"role": "user", "content": user}])


def categorize_confluence_titles(titles, max_items=200):
    """
    Categorize Confluence page titles into 3-8 topic buckets.
    Returns dict:
      {
        "categories": [{"name": str, "count": int, "examples": [str, ...]}, ...],
        "summary": str
      }
    Returns empty structure on LLM/JSON errors.
    """
    if not titles:
        return {"categories": [], "summary": ""}

    text = _truncate_lines(titles[:max_items], MAX_INPUT_CHARS)
    system = (
        "You analyze Confluence page titles and group them into practical topic categories. "
        "Respond in strict JSON only. No markdown, no extra text."
    )
    user = (
        "Group these Confluence titles into 3 to 8 categories. "
        "Return JSON object with this exact shape: "
        '{{"categories":[{{"name":"...","count":1,"examples":["...","..."]}}],"summary":"..."}}. '
        "Rules: category names should be short (2-5 words), counts must match number of titles in the category, "
        "examples should have up to 3 real titles from input, and categories sorted by count desc. "
        "Keep summary to 1-2 sentences.\n\nTitles:\n{}"
    ).format(text)

    try:
        raw = _call_llm(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=500,
        ).strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            if len(parts) >= 2:
                raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        categories = parsed.get("categories") if isinstance(parsed, dict) else []
        summary = parsed.get("summary") if isinstance(parsed, dict) else ""
        cleaned = []
        for item in categories or []:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            try:
                count = int(item.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            examples = item.get("examples") if isinstance(item.get("examples"), list) else []
            examples = [str(x).strip() for x in examples if str(x).strip()][:3]
            cleaned.append({"name": name, "count": max(0, count), "examples": examples})
        cleaned = sorted(cleaned, key=lambda x: -x.get("count", 0))[:8]
        return {"categories": cleaned, "summary": (summary or "").strip()}
    except (LLMError, json.JSONDecodeError, TypeError, ValueError):
        return {"categories": [], "summary": ""}


def insights_from_jira_titles(ticket_titles, max_items=200):
    """
    Feed Jira ticket titles (and optionally keys) to the LLM.
    ticket_titles: list of strings like "PROJ-123 Fix login bug" or just "Fix login bug".
    Returns a string: themes and a short summary of ticket focus.
    """
    if not ticket_titles:
        return None
    text = _truncate_lines(ticket_titles[:max_items], MAX_INPUT_CHARS)
    system = (
        "You are a helpful assistant that analyzes project and issue tracking activity. "
        "Given a list of Jira ticket titles (and possibly keys), identify 3–5 main themes or focus areas "
        "and write a very short paragraph (2–4 sentences) summarizing what kind of work these tickets represent. "
        "Be concise and factual."
    )
    user = (
        "Here are Jira ticket titles (assigned to or created by the user) from the last 12 months:\n\n{}\n\n"
        "List the main themes (bullet points) and then a short summary paragraph."
    ).format(text)
    return _call_llm([{"role": "system", "content": system}, {"role": "user", "content": user}])


def combined_year_in_review(commits=None, confluence_titles=None, jira_titles=None):
    """
    Feed all three sources to the LLM and get one combined Work Wrapped narrative.
    Each of commits, confluence_titles, jira_titles can be a list of strings or None.
    Returns a string: unified themes and narrative.
    """
    parts = []
    if commits:
        parts.append("COMMIT / CODE REVIEW MESSAGES:\n" + _truncate_lines(commits[:80], 4000))
    if confluence_titles:
        parts.append("CONFLUENCE PAGE TITLES:\n" + _truncate_lines(confluence_titles[:80], 4000))
    if jira_titles:
        parts.append("JIRA TICKET TITLES:\n" + _truncate_lines(jira_titles[:80], 4000))
    if not parts:
        return None
    text = "\n\n".join(parts)
    system = (
        "You are a helpful assistant writing a personal Work Wrapped summary for a developer. "
        "You will receive three types of data: commit messages, Confluence page titles, and Jira ticket titles. "
        "Write one short narrative (4–8 sentences) that summarizes what this person worked on over the year: "
        "main themes, areas of impact (code, docs, project work), and any clear focus areas. "
        "Be encouraging and factual; no generic fluff."
    )
    user = "Here is the data:\n\n{}\n\nWrite the short Work Wrapped narrative.".format(text)
    return _call_llm(
        [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=600
    )


# --- Optional: structured JSON output (themes only) ---


def themes_from_commits(commit_messages, max_items=150):
    """Ask LLM to return only a JSON list of theme labels. Returns list of strings or [] on error."""
    if not commit_messages:
        return []
    text = _truncate_lines(commit_messages[:max_items], 8000)
    user = (
        "From these commit messages, extract 3–6 short theme labels (e.g. 'API design', 'Testing', 'Refactoring'). "
        'Reply with a JSON array of strings only, e.g. ["Theme A", "Theme B"]:\n\n{}'
    ).format(text)
    try:
        out = _call_llm([{"role": "user", "content": user}], max_tokens=200)
        out = out.strip()
        if out.startswith("```"):
            out = out.split("```")[1]
            if out.startswith("json"):
                out = out[4:]
        out = json.loads(out.strip())
        return out if isinstance(out, list) else []
    except (json.JSONDecodeError, LLMError):
        return []


# --- Usage from app or CLI ---
# from llm_insights import (
#     insights_from_commits,
#     insights_from_confluence_titles,
#     insights_from_jira_titles,
#     combined_year_in_review,
#     themes_from_commits,
#     LLMError,
# )
# commits = [c["message"] for c in gerrit_list]
# print(insights_from_commits(commits))
# titles_c = [p["title"] for p in confluence_list]
# print(insights_from_confluence_titles(titles_c))
# titles_j = [t["title"] or t["key"] for t in jira_list]
# print(insights_from_jira_titles(titles_j))
# print(combined_year_in_review(commits, titles_c, titles_j))
