# Deployment plan

This plan takes ZomatoReco from a local app to a public one: the FastAPI backend on **Railway** and the static page on **Vercel**. `deployment.md` is the command runbook. This file sets the order, what each phase decides, and the checks that close it. Each phase leaves something working before the next one starts.

The deployment is complete when a diner opens the Vercel URL, picks a locality and budget, and gets a ranked shortlist from the Railway API, with no CORS errors in the browser console.

## Ground rules

- Finish a phase only when its exit checks pass.
- Deploy only committed code. The Railway and Vercel CLIs upload the working folder, so uncommitted edits would go live without a record.
- Keep secrets in the hosts' variable stores. `.env` stays local and is never committed or uploaded.
- Deploy the backend first. The frontend build needs the backend URL, and the backend's CORS setting needs the frontend URL, so the two are connected last.

## Current state

The split deployment is already scaffolded (commit `def2a05`):

| Piece | Status |
| --- | --- |
| `Dockerfile`, `.dockerignore`, `railway.json` | Ready. Python 3.12 slim image with runtime packages, `app/`, and the catalog; binds to `PORT`; health check on `/facets`. |
| `data/catalog.parquet`, `data/facets.json` | Committed (about 4 MB), so the image build does not run ingestion. |
| `vercel.json`, `.vercelignore`, `deploy/write-config.mjs` | Ready. Uploads only `app/static` and the build script; the build writes `config.js` from `API_BASE_URL`. |
| `app/main.py` → `cors_origins()` | Ready. Reads `CORS_ORIGINS`; empty means same-origin only. |
| Railway and Vercel CLIs | Installed (`/opt/homebrew/bin`). |

Phase 0 decisions (done):

- The pastel redesign is committed.
- The Stitch mock-ups are committed as design references and excluded from the Docker build context in `.dockerignore`.
- Google Fonts (Quicksand, Inter) stay; `implementation-plan.md` now records them as the one external asset, with system-font fallbacks.

What is still open:

- The repo has no git remote, so the hosts cannot deploy from GitHub yet. The CLI path works without one.
- Docker is not installed locally, so the image has not been built on this machine. The local virtualenv runs Python 3.15; the image uses 3.12.

## Phase 0 — Release readiness

**Goal.** A clean, committed tree that passes the tests and is ready to upload.

**Tasks**

1. Commit the frontend redesign.
2. Decide what to do with the Stitch mock-ups: commit them as design references or add `stitch_bangalore_food_recommendation_engine/` to `.gitignore`. Either way, add the folder to `.dockerignore` so it never reaches the Railway build context. `.vercelignore` already excludes it.
3. Decide on the Google Fonts link in `index.html`. The Phase 5 plan says no external fonts. Either accept the dependency and update `implementation-plan.md`, or drop the link and fall back to system fonts. The page works either way.
4. Run `pytest` and a local smoke run (`uvicorn app.main:app --env-file .env`) with one search.
5. Optional: create a GitHub repo and push `main`, if you want deploy-on-push later (Phase 5).

**Exit checks**

- `git status` is clean.
- `pytest` passes.
- A local search returns a shortlist.

## Phase 1 — Accounts and keys

**Goal.** Every account and secret the deploy needs exists before anything is uploaded.

**Tasks**

1. `railway login` and `vercel login`.
2. Get a Groq API key for production from console.groq.com/keys. Use a separate key from the local one, so either can be revoked on its own.
3. Pick the model tier. The Groq free tier rate-limits after a few searches a minute, which shows up as 502s; this already happened during local testing. For a demo, `openai/gpt-oss-120b` on the free tier is fine. For real traffic, use a paid tier with a spending limit, or `openai/gpt-oss-20b`.
4. Check the Railway plan. The trial credit runs out, and the backend stops when it does.

**Exit checks**

- `railway whoami` and `vercel whoami` both name your account.
- The production Groq key answers `GET https://api.groq.com/openai/v1/models`.

## Phase 2 — Backend on Railway

**Goal.** The API runs publicly at a `*.up.railway.app` URL.

**Tasks**

1. `railway init --name zomatoreco`, then `railway up --detach`. Railway builds the Dockerfile in its own builder, so local Docker is not needed.
2. Set the variables: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_RESPONSE_FORMAT`. Leave `CORS_ORIGINS` unset for now. Railway sets `PORT`, and the image sets `CATALOG_PATH`.
3. `railway domain` to generate the public URL. Record it as `API`.
4. Watch `railway logs` through the first boot. The image runs Python 3.12 while local tests ran on 3.15, so this is the first real run on the production Python.

**Exit checks**

- The deploy passes Railway's `/facets` health check.
- `curl $API/facets` returns localities and cuisines.
- `POST $API/recommendations` (Banashankari, medium, 4.0) returns recommendations with explanations, not a 502.

**Rollback.** Railway keeps earlier deployments. Use **Redeploy** on the last good one in the dashboard.

## Phase 3 — Frontend on Vercel

**Goal.** The static page is live and points at the Railway API.

**Tasks**

1. `vercel link --yes --project zomatoreco`.
2. Add `API_BASE_URL=$API` for the **Production** environment. The build fails without it, by design.
3. `vercel deploy --prod`. Record the production URL as `WEB`.

**Exit checks**

- `curl $WEB/static/config.js` shows `window.API_BASE = "<API>"`.
- `$WEB` loads with styles and illustrations. The search will fail until Phase 4 because of CORS, and that is expected at this point.

**Rollback.** `vercel rollback`, or promote an earlier deployment in the dashboard.

## Phase 4 — Connect and verify end to end

**Goal.** The browser on `WEB` can call `API`, and the whole diner flow works in production.

**Tasks**

1. `railway variables --set "CORS_ORIGINS=$WEB"`, with an exact origin: scheme included, no trailing slash. Railway redeploys.
2. Run the verification commands in `deployment.md` §5: facets, a recommendation, the CORS preflight, and `config.js`.
3. In a browser on `WEB`, repeat the Phase 6 manual checks from `implementation-plan.md`:
   - a normal search (Banashankari, medium, 4.0, "family-friendly, quick service");
   - "All cuisines";
   - a search that should match nothing (for example Afghan), to see the empty-state sentence;
   - a phone-width check (400px, no horizontal scroll).
4. Check the browser console during those searches.

**Exit checks**

- The CORS preflight returns `access-control-allow-origin: $WEB`.
- All four browser checks behave as they do locally.
- The console shows no CORS errors or failed requests, apart from deliberate error-path tests.

## Phase 5 — Ongoing operation

**Goal.** Updates are routine, and cost and abuse stay bounded.

**Tasks**

1. **Deploy-on-push (optional).** Once the repo is on GitHub, connect the Railway service and the Vercel project to it. After that, every push to `main` deploys both. Keep `API_BASE_URL` and `CORS_ORIGINS` in the hosts. Vercel preview URLs are not in `CORS_ORIGINS`, so previews can't search unless you add their origins.
2. **Updating:**
   - Backend: `railway up --detach`, or a push once connected.
   - Frontend: `vercel deploy --prod`, or a push once connected.
   - Catalog: rebuild locally, commit `data/`, then redeploy the backend.
   - If either URL changes, update the other host's variable.
3. **Cost and abuse.** The API has no authentication or rate limit. CORS stops other websites, not scripts. Before sharing the URL widely:
   - set a Groq spending limit;
   - consider per-IP rate limiting (for example `slowapi`) on `POST /recommendations`;
   - watch `railway logs` for repeated "rate limit reached" lines.
4. **Key rotation.** `railway variables --set "LLM_API_KEY=..."` and revoke the old key in Groq.

**Exit checks**

- A one-line change to `app/static` and one to `app/` each reach production through the update path you chose, and Phase 4's checks still pass.

## Phase map

| Phase | Produces | Depends on |
| --- | --- | --- |
| 0 | Clean, tested, committed tree | — |
| 1 | Logged-in CLIs, production Groq key, plan choices | — |
| 2 | Public Railway API (`API`) | 0, 1 |
| 3 | Public Vercel page (`WEB`) pointing at `API` | 2 |
| 4 | CORS connected; production flow verified | 2, 3 |
| 5 | Repeatable updates, bounded cost | 4 |

Phases 0 and 1 can run in parallel. Phases 2, 3, and 4 must run in order, because each one needs a URL from the one before.
