# Work Wrapped — Personal & Team Dashboard

A dashboard that gathers work activity across **Jira**, **Slack**, **Confluence**, and **Gerrit** into clear summaries and drill-downs.

## Publishing to GitHub

- Ensure `.env` is never committed (it’s in `.gitignore`). Only `.env.example` is tracked as a template.
- Replace `YOUR_USERNAME` in the clone URL below with your GitHub username after you create the repo.
- Optionally add your name/year in `LICENSE`.

## Purpose

- **Personal view**: "What did I actually work on this year?" — Like Spotify Wrapped, for your work
- **Team view**: "What themes and impact does the team have?" — For managers to have info in one place
- **Not for ranking or comparing** — For reflection, 1:1 prep, and self-improvement

## Quick Start

### 1. Configure Gerrit

Create a `.env` file (or export variables):

```bash
cp .env.example .env
# Edit .env:
# GERRIT_URL=https://gerrit.your-company.com
```

Optional:
- `GERRIT_VERIFY_SSL=false` — Disable SSL verification (e.g. for self-signed certs)
- `JIRA_URL` — Jira base URL (e.g. `https://your-company.atlassian.net`) to enable Jira ticket fetch
- `JIRA_VERIFY_SSL=false` — Disable SSL verification for Jira
- `SECRET_KEY` — Session secret (required in production)

### 2. Run the app

```bash
git clone https://github.com/YOUR_USERNAME/year_in_review.git
cd year_in_review
cp .env.example .env
# Edit .env and set at least GERRIT_URL

pip install -r requirements.txt
python run.py
```

Open http://localhost:5001 — you'll be redirected to login.

**Project layout:** Python code in `src/`, HTML in `frontend/`. The app loads `.env` from the project root.

### Run with Docker

Have a `.env` file in the project root (see above), then:

```bash
docker compose up --build
```

Open http://localhost:5001. Environment variables are read from `.env` via `env_file` in `docker-compose.yml`.

**Including `.env` in the image:** If you have a `.env` file in the project root when you build, it is copied into the image. That way you can share a single image with your Gerrit/Jira/Confluence URLs (and other non-secret config) built in; recipients can run the container without creating their own `.env`. (They still use their own login credentials at the app’s login page.) If you build without a `.env`, the image falls back to `.env.example`.

### Docker image versioning

The app version is read from the **`VERSION`** file in the project root (e.g. `1.0.0`). It is shown in the UI header and at `GET /api/version`.

**Build and tag an image with a specific version** (e.g. to share with colleagues):

```bash
# Use the version from ./VERSION (e.g. 1.0.0)
export VERSION=$(cat VERSION)
docker compose build
# Image is tagged: work-wrapped:1.0.0
```

Or build and tag manually:

```bash
docker build -t work-wrapped:$(cat VERSION) --build-arg VERSION=$(cat VERSION) .
docker tag work-wrapped:$(cat VERSION) work-wrapped:latest   # optional
```

**When you release a new version:**  
1. Update `VERSION` (e.g. to `1.0.1`).  
2. Build and push: `VERSION=$(cat VERSION) docker compose build` then push to your registry as `work-wrapped:1.0.1`.  
3. Colleagues pull and run: `docker pull yourregistry/work-wrapped:1.0.1` and `docker run -p 5001:5001 yourregistry/work-wrapped:1.0.1`. They can confirm the version in the app header or with `curl http://localhost:5001/api/version`.

To run the image without Compose:

```bash
docker build -t work-wrapped .
docker run -p 5001:5001 work-wrapped
```
You can still override config at run time with `--env-file .env` or `-e VAR=value` if needed.

### Sharing the image with someone else

If you built the image with a `.env` in the project root, that config is inside the image. Recipients can run it as-is (they sign in with their own Gerrit/Jira/etc. credentials on the login page).

**Option A: Save/load as a file**

On your machine (build with your `.env` in place so it’s in the image):
```bash
docker build -t work-wrapped .
docker save -o work-wrapped.tar work-wrapped
```
Send `work-wrapped.tar`. On their machine:
```bash
docker load -i work-wrapped.tar
docker run -p 5001:5001 work-wrapped
```
If you built without `.env`, they can run with their own: `docker run -p 5001:5001 --env-file .env work-wrapped`.

**Option B: Push to a registry (Docker Hub, GHCR, etc.)**

```bash
docker tag work-wrapped yourusername/work-wrapped:latest
docker push yourusername/work-wrapped:latest
```
They run: `docker pull yourusername/work-wrapped:latest` then `docker run -p 5001:5001 yourusername/work-wrapped:latest` (or with `--env-file .env` to override config).

### 3. Log in

Use your **Gerrit email** and **HTTP Password**:
- Email: your Gerrit account email
- Password: Generate from **Gerrit → Settings → HTTP Password**

> **Note:** The HTTP password is different from your normal login password. Generate it in Gerrit under Settings → HTTP Password.

### 4. Optional: Jira tickets

If `JIRA_URL` is set, the login page shows optional **Jira email** and **Jira API token**. Fill them to include your Jira tickets (assigned to or created by you, last 12 months) in the dashboard. Create an API token at [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

## Current Features

- **Gerrit** — Auth + your changes from the last 12 months
- **Jira** — Tickets assigned to or created by you (optional; set JIRA_URL + credentials at login)
- **Personal view** — Gerrit + Jira, projects/themes, Work Wrapped metrics
- **Team view** — Placeholder (needs more sources for aggregation)
- **Simple dark UI** — Minimal, clean design

## Next Steps

1. Confluence API integration
3. Add Slack API (with allowed channels)
4. Team aggregation across users
5. Search and filters

## Performance

- **Parallel fetches:** Gerrit, Jira, Confluence, and Slack are requested in parallel so total wait time is roughly the slowest source, not the sum of all four.
- **Gerrit comments:** Reviewer comment counts are fetched in parallel for the last 25 changes (reduced from 80) to keep the page fast.
- **Jira changelog (default on):** By default the app does *not* request issue changelog (so Jira is much faster for a full year). To enable “time to grab” and “time in review” metrics, set `JIRA_INCLUDE_CHANGELOG=true` in `.env`; the Jira request will be slower.

## Tech

- Python 3
- FastAPI, Uvicorn
- requests (Gerrit REST API)
- Vanilla HTML/CSS/JS (no framework)
