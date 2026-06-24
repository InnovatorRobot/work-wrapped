# Work Wrapped — Project Documentation

*Personal & Team Dashboard for work activity across Jira, Gerrit, Confluence, and Slack.*

---

## Overview

**Work Wrapped** is an internal dashboard that aggregates your work activity from **Gerrit**, **Jira**, **Confluence**, and **Slack** into a single view. It answers: *"What did I actually work on?"* and supports reflection, 1:1 preparation, and optional team-level insights — **not** for ranking or comparing individuals.

| Item | Description |
|------|-------------|
| **Purpose** | One place to see your tickets, code changes, Confluence pages, and Slack activity over a chosen time range (e.g. last 12 months). |
| **Users** | Individuals (personal view) and optionally managers (team view with opt-in aggregation). |
| **Current state** | Proof of concept; single deployment (FastAPI + Jinja2 + static). Scalable design for ~500 users is documented in the architecture. |

---

## Purpose & Value

- **Personal view** — "What did I actually work on this year?" — Like Spotify Wrapped, for your work.
- **Team view** — "What themes and impact does the team have?" — For managers to have aggregated info in one place (opt-in).
- **Not for ranking or comparing** — For reflection, 1:1 prep, and self-improvement.
- **Single place** — No need to open four tools to prepare for a review or 1:1.

---

## Features

### Personal dashboard

| Feature | Description |
|---------|-------------|
| **Time range** | Last 3, 6, 12, 24, or 36 months. |
| **Totals** | Tickets (Jira), changes (Gerrit), pages (Confluence), messages (Slack). |
| **Activity over time** | Stacked bar chart by month. |
| **Themes / projects** | Top areas across all sources. |
| **Talking points** | Auto-generated bullets for 1:1 or self-review. |
| **Reminders** | e.g. open Gerrit changes older than 14 days, or prompt to set goals. |
| **Export** | PDF, one-pager PDF, JSON, CSV. |
| **Shareable link** | Read-only link to your summary (e.g. for your manager); expires in 30 days. |

### Integrations

| Source | What is shown |
|--------|----------------|
| **Gerrit** | Your changes (merged/open/abandoned), lines added/removed, time to merge, reviewers, comment counts, stale open changes list with links. |
| **Jira** | Tickets assigned to or created by you; by status, project, epic, sprint; time to resolution, time in review, first response; In Review/Blocked counts, time in To Do, reopened count, comments per ticket, story points (velocity). |
| **Confluence** | Pages you created or updated; by space; created vs updated by month (two lines over time); most edited pages. |
| **Slack** | Messages you sent; by channel; peak hour/weekday; "Most active Tue–Thu 9–11" style one-liner; longest threads; thread vs top-level, reactions. |

### Goals & team

- **Goals** — Optional targets (e.g. tickets done, reviews, messages) with progress bars.
- **Snapshots** — Save a checkpoint (e.g. "Q1 check-in") and compare now vs then.
- **Team comparison (opt-in)** — Include your summary in team average; see "You vs team average (N participants)."

### Cross-cutting metrics

- **Busiest month** — Month with highest combined activity.
- **Focus score** — Percentage of activity in your top two areas.
- **Trend** — Up / down / flat (last 6 months vs previous 6 months).

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3, FastAPI, Uvicorn |
| **Frontend** | Vanilla HTML, CSS, JavaScript (no framework); Jinja2 templates |
| **HTTP client** | `requests` for Gerrit, Jira, Confluence, Slack APIs |
| **PDF export** | WeasyPrint |
| **Persistence (current)** | JSON files in `data/` (goals, snapshots, share links, team opt-in, team metrics); session in memory |
| **Deployment** | Single process or Docker; see *Architecture* for scaled design (PostgreSQL, optional Redis) |

---

## Getting Started

### Prerequisites

- Python 3
- Gerrit instance (required for login)
- Optional: Jira, Confluence, Slack (configure URLs and provide credentials at login)

### 1. Configure environment

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- **GERRIT_URL** — Your Gerrit base URL (e.g. `https://gerrit.your-company.com`)

Optional:

- **JIRA_URL** — Jira base URL (e.g. `https://your-company.atlassian.net`)
- **CONFLUENCE_URL** — Confluence base URL (if different from Jira)
- **SECRET_KEY** — Session secret (required in production)
- **GERRIT_VERIFY_SSL** / **JIRA_VERIFY_SSL** — Set to `false` only if using self-signed certs

### 2. Install and run (local)

```bash
pip install -r requirements.txt
python run.py
```

Open **http://localhost:5001** — you will be redirected to login.

### 3. Run with Docker

```bash
docker compose up --build
```

Open **http://localhost:5001**. The app reads environment variables from `.env` via `docker-compose.yml`.

**Version:** The app version is read from the `VERSION` file (e.g. `1.0.0`) and shown in the UI header and at `GET /api/version`.

---

## Login & Credentials

- **Gerrit (required)** — Use your **Gerrit username** and **HTTP Password** (not your normal login password). Generate the HTTP password in **Gerrit → Settings → HTTP Password**.
- **Jira (optional)** — If `JIRA_URL` is set, you can enter Jira email and API token at login to include your Jira tickets. Create an API token at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
- **Confluence (optional)** — If configured, use Confluence email and API token, or leave blank to reuse Jira credentials when using the same Atlassian account.
- **Slack (optional)** — User OAuth Token (xoxp-...) from [api.slack.com/apps](https://api.slack.com/apps); scopes: channels:read, channels:history, groups:read, groups:history.

Credentials are used only to fetch data on your behalf; they are not stored on disk in the current PoC (session only).

---

## Project Structure

| Path | Description |
|------|-------------|
| `src/` | Python backend: `app.py` (FastAPI app, routes, metrics), `*_client.py` (Gerrit, Jira, Confluence, Slack), `llm_insights.py` (optional AI categorization). |
| `frontend/` | HTML templates (Jinja2), static assets; `base.html` is the main layout. |
| `data/` | JSON files for goals, team opt-in, team metrics, snapshots, share links (created at runtime). |
| `docs/` | Architecture and Confluence documentation. |
| `.env` | Local configuration (not committed); `.env.example` is the template. |
| `VERSION` | Application version string (e.g. `1.0.0`). |

---

## API Overview (for integrators)

The backend exposes REST endpoints used by the frontend. Key ones:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/personal` | GET | Personal summary (totals, themes, metrics). Query: `months`, `refresh`. |
| `/api/goals` | GET / POST | Get or set user goals (tickets_done, reviews, messages). |
| `/api/team-comparison` | GET / POST | Get or set team opt-in. |
| `/api/snapshots` | GET / POST | List or create snapshots. |
| `/api/share` | POST | Create a shareable read-only link. |
| `/share/{token}` | GET | Public view of a shared summary (no login). |
| `/api/version` | GET | Application version. |
| `/api/export/json`, `/api/export/csv` | GET | Export data as JSON or CSV. |
| `/export/pdf`, `/export/onepager` | GET | Export as PDF (full or one-pager). |

Authentication is session-based (cookie). Unauthenticated users are redirected to `/login`.

---

## Performance Notes

- **Parallel fetches** — Gerrit, Jira, Confluence, and Slack are requested in parallel; total wait time is roughly the slowest source.
- **Caching** — Personal summary is cached in memory per (user, time range); use `?refresh=1` to force refetch.
- **Jira** — For faster Jira load, leave `JIRA_INCLUDE_CHANGELOG` unset or `false`. Set to `true` only if you need "time to grab" and "time in review" metrics (slower request).

---

## Architecture & Scaling

The current deployment is a **proof of concept**: single process, in-memory session, JSON-file persistence. For scaling to **~500 users**, the project has a documented architecture that includes:

- **Two services** — Frontend (static/SPA) and Backend (FastAPI, API-only or serving static).
- **Database** — PostgreSQL for users, goals, snapshots, share links, team metrics, and optional session store.
- **Optional Redis** — Session store and/or response cache (e.g. personal summary TTL).
- **Stateless backend** — Multiple replicas behind a load balancer; credentials stored encrypted in DB or vault.

See **`docs/ARCHITECTURE.md`** in the repository for the full design, data model, and migration path.

---

## Versioning & Releases

- **VERSION file** — Contains the application version (e.g. `1.0.0`). Shown in the UI and at `/api/version`.
- **Docker** — Build with `docker build -t work-wrapped:$(cat VERSION) --build-arg VERSION=$(cat VERSION) .` for tagged images.
- **Releases** — Update `VERSION`, build, and push the image to your registry; document the tag in release notes.

---

## Security & Compliance

- **Credentials** — Never commit `.env`. Use `.env.example` as a template only. In production, set `SECRET_KEY` to a strong random value.
- **Share links** — Expire after 30 days (configurable via `SHARE_LINK_EXPIRY_DAYS`). No authentication required to view a valid share link; treat the token as secret.
- **Data** — All data is fetched per user from external systems; the app does not store full ticket or message content long-term in the current PoC (only aggregates and user-entered goals/snapshots).

---

## Support & Contributing

- **Documentation** — This page (Confluence), README and `docs/` in the repo.
- **Ideas / roadmap** — See `IDEAS.md` in the repository for implemented features and possible enhancements (e.g. settings page, email digest, real team view).
- **Issues** — Track bugs and feature requests in your preferred issue tracker (e.g. GitHub Issues, Jira).

---

*Last updated for Work Wrapped PoC; architecture doc describes the path to a production-ready deployment for ~500 users.*
