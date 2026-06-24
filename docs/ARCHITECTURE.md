# Work Wrapped — Architecture for ~500 Users

This document describes a production-ready design to scale the current PoC from a single-user/small-team deployment to **~500 users**, with a clear split between **frontend** and **backend** services.

---

## 1. Current PoC vs Target

| Aspect | Current (PoC) | Target (~500 users) |
|--------|----------------|----------------------|
| **Deployment** | Single process (FastAPI + Jinja2 + static) | Frontend service + Backend API service |
| **State** | In-memory cache, JSON files on disk | Stateless backend; DB + optional Redis |
| **Sessions** | In-memory (cookie-signed); lost on restart | Stored in DB or Redis; survive restarts and replicas |
| **Persistence** | `data/*.json` (goals, snapshots, share links, team metrics) | Relational database (PostgreSQL) |
| **Credentials** | In session (memory) | Encrypted in DB or vault; fetched per request |
| **Concurrency** | JSON read/write races under load | DB transactions; optional cache layer |
| **Scale** | Single instance | Backend can run multiple replicas behind a load balancer |

---

## 2. High-Level Architecture

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                     USERS (browsers)                     │
                    └────────────────────────────┬────────────────────────────┘
                                                 │ HTTPS
                    ┌────────────────────────────▼────────────────────────────┐
                    │  FRONTEND SERVICE                                         │
                    │  • Static assets (HTML, CSS, JS) or SPA                   │
                    │  • Served by CDN / Nginx / static host                    │
                    │  • All API calls go to Backend (same origin or CORS)      │
                    └────────────────────────────┬────────────────────────────┘
                                                 │ REST API (JSON)
                    ┌────────────────────────────▼────────────────────────────┐
                    │  BACKEND SERVICE (FastAPI)                               │
                    │  • Auth (login, session, tokens)                         │
                    │  • Proxy to Gerrit / Jira / Confluence / Slack          │
                    │  • Aggregation, metrics, goals, snapshots, share links    │
                    │  • Stateless; N replicas behind load balancer           │
                    └─────┬──────────────────────────────────┬────────────────┘
                          │                                  │
          ┌───────────────▼───────────────┐    ┌─────────────▼─────────────┐
          │  PostgreSQL                    │    │  Redis (optional)          │
          │  • Users / identities          │    │  • Session store          │
          │  • Goals, opt-in, snapshots    │    │  • Response cache         │
          │  • Share links, team metrics   │    │  (e.g. personal summary   │
          │  • Optional: metric history    │    │   TTL 5–15 min)           │
          └───────────────────────────────┘    └───────────────────────────┘
                          │
          ┌───────────────▼───────────────────────────────────────────────────┐
          │  EXTERNAL APIS (Gerrit, Jira, Confluence, Slack)                   │
          │  Backend only; per-user credentials from DB or vault                │
          └───────────────────────────────────────────────────────────────────┘
```

---

## 3. Two Services: Frontend and Backend

### 3.1 Frontend service

**Role:** Serve the UI and talk to the backend only (no direct Gerrit/Jira/etc.).

**Options:**

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A. Static + Backend-rendered** | Keep Jinja2 templates; backend serves HTML for `/`, `/jira`, etc., and static files from backend or CDN | Easiest migration; one less deploy | Frontend and backend deploy together; no true “micro” split |
| **B. Static site only** | Build HTML/JS that only calls backend API; serve from Nginx, S3+CloudFront, or separate container | Clear separation; CDN caching; deploy frontend independently | Need to implement API-first backend and a small SPA or static JS app |
| **C. SPA (React/Vue/etc.)** | Single-page app; backend is API-only | Best UX and independent releases | More code and tooling; still optional for 500 users |

**Recommendation for 500 users:** **Option B** is a good balance: static HTML/JS (can stay minimal, like today’s vanilla JS) that only calls the backend API. Backend serves **only** JSON API + static assets (or you serve static from a separate host). No server-side rendering required.

**Responsibilities:**

- Serve static assets (HTML, CSS, JS, images).
- Handle routing (e.g. `/`, `/jira`, `/login`) with client-side or hash routing if needed.
- Call backend API for data (`/api/personal`, `/api/goals`, etc.).
- Send session cookie or Bearer token with each request.

---

### 3.2 Backend service

**Role:** Auth, business logic, persistence, and calling external APIs.

**Responsibilities:**

- **Auth:** Login (e.g. Gerrit or company SSO), issue session token; validate token on every request.
- **User and credentials:** Store user identity and, per integration, encrypted credentials or token references (Gerrit HTTP password, Jira/Confluence/Slack tokens). Fetch from DB (or vault) per request when calling external APIs.
- **API:** REST (or GraphQL) endpoints for:
  - Personal summary (with time range)
  - Goals, team opt-in, snapshots, share links
  - Team aggregate (for opted-in users)
  - Export (PDF, JSON, CSV) can stay server-generated or be built from API data
- **External calls:** Backend only calls Gerrit, Jira, Confluence, Slack (rate limiting per user/source to avoid hitting provider limits).
- **Persistence:** All current JSON-backed data moves to PostgreSQL (see data model below).
- **Optional:** Background worker to pre-compute metrics or refresh cache (e.g. nightly) to reduce latency and load.

**Stateless:** No in-memory user cache. Cache only in Redis (with TTL) if you want to reduce DB and external API load. Session in DB or Redis so any replica can serve any user.

---

## 4. Data Model (PostgreSQL)

Replace `data/*.json` with tables along these lines:

```
users
  id (PK), external_id (e.g. Gerrit account id), email, name, created_at, updated_at

user_integrations
  id (PK), user_id (FK), provider (gerrit|jira|confluence|slack), 
  encrypted_credentials or token_ref, updated_at

goals
  user_id (PK), tickets_done, reviews, messages, updated_at

team_optin
  user_id (PK), include boolean, updated_at

snapshots
  id (PK), user_id (FK), label, snapshot_date, totals (JSONB), created_at

share_links
  token (PK), user_id (FK), payload (JSONB), created_at, expires_at

team_metrics
  user_id (PK), totals (JSONB), updated_at   -- for opted-in users only

sessions (if stored in DB)
  id (PK), user_id (FK), token_hash, expires_at, created_at

-- Optional: for historical trends without re-fetching APIs
metric_snapshots
  id (PK), user_id (FK), snapshot_date, totals (JSONB), by_source (JSONB), created_at
```

- **Credentials:** Prefer encrypting at rest (e.g. application-level encryption with a key from env) or use a vault; backend decrypts only when calling the external API.
- **Share links:** Index on `expires_at` and run a periodic job (or query) to delete expired rows.

---

## 5. Auth and Sessions

- **Login:** Keep “Gerrit username + HTTP password” as one option, or add OAuth/OIDC (e.g. company IdP) for 500 users.
- **Session:** After login, backend creates a session (e.g. random token), stores it in **DB or Redis** with `user_id` and expiry, sets cookie (or returns token for SPA).
- **Every request:** Backend resolves session from cookie/token → `user_id` → load user and integrations from DB, then runs logic. No in-memory session store so multiple replicas stay consistent.

---

## 6. API Design (Backend)

Keep current behaviour, expose as a clear REST API:

- `POST /api/auth/login` — body: credentials; response: session cookie or token.
- `POST /api/auth/logout` — invalidate session.
- `GET /api/personal?months=12&refresh=0` — personal summary (reuse current aggregation).
- `GET /api/goals`, `POST /api/goals` — goals.
- `GET /api/team-comparison`, `POST /api/team-comparison` — opt-in.
- `GET /api/snapshots`, `POST /api/snapshots` — snapshots.
- `POST /api/share` — create share link; `GET /share/{token}` — public view (can stay server-rendered or use API).
- `GET /api/team` — team aggregate.
- `GET /api/export/json`, `GET /api/export/csv`, `GET /export/pdf`, etc. — as today.

Frontend (static or SPA) only calls these; no direct access to Gerrit/Jira/Confluence/Slack from the browser.

---

## 7. Deployment (500 users)

- **Frontend:** Deploy static assets to CDN or a small Nginx (or Caddy) container. Single deployment unit.
- **Backend:** Run 2+ FastAPI replicas behind a load balancer (e.g. Kubernetes, ECS, or VM + Nginx). Env vars: DB URL, Redis URL (if used), secret key, external API base URLs.
- **PostgreSQL:** Managed (e.g. RDS, Azure Database) or self-hosted; backups and connection pooling (e.g. PgBouncer) recommended.
- **Redis:** Optional; one small instance for sessions and/or response cache.
- **Secrets:** DB password, encryption key for credentials, session secret — from env or a secret manager (e.g. AWS Secrets Manager, Azure Key Vault).

---

## 8. Migration Path from PoC

1. **Introduce DB:** Add PostgreSQL (and optional Redis). Implement tables and replace `_load_json` / `_save_json` with DB access (per user) for goals, opt-in, snapshots, share links, team metrics.
2. **Sessions in DB/Redis:** Replace in-memory session store so sessions survive restarts and work across replicas.
3. **Credentials:** Move from “store in session” to “store encrypted in DB (or vault) keyed by user_id + provider”. On each request, load and decrypt only for the current user.
4. **Remove in-memory cache:** Either no cache or Redis cache for personal summary (short TTL) keyed by `user_id + months`.
5. **Split frontend (optional but recommended):** Extract static assets and any server-rendered “shell” into a separate deploy; backend serves only API (and maybe `/share/{token}`). Frontend configured with backend API base URL.
6. **Add rate limiting and monitoring:** Per-user or per-IP limits on login and heavy endpoints; health checks and logging for debugging at scale.

This gives you a clear path from the current PoC to a two-service (frontend + backend), DB-backed design that supports ~500 users and leaves room for historical metrics and background jobs later.
