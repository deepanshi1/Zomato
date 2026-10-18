# Deployment

ZomatoReco deploys as two pieces:

| Piece | Host | What runs |
| --- | --- | --- |
| Backend | **Railway** | The FastAPI app (`GET /facets`, `POST /recommendations`) in a Docker image that includes the catalog. |
| Frontend | **Vercel** | The static page in `app/static` (HTML, CSS, JS). No server code. |

The browser loads the page from Vercel and calls the Railway API directly. Two settings connect them:

- **`API_BASE_URL`** (Vercel): the Railway URL. The Vercel build writes it into `app/static/config.js`, and `app.js` prefixes every request with it.
- **`CORS_ORIGINS`** (Railway): the Vercel URL. The backend lets only that origin call it from a browser.

Running locally is unchanged: `config.js` ships with an empty base, so the page calls the API on the same origin, and `uvicorn` still serves the page at http://localhost:8000.

## Files involved

| File | Purpose |
| --- | --- |
| `Dockerfile`, `.dockerignore` | Backend image: runtime packages, `app/`, and the built catalog. Binds to Railway's `PORT`. |
| `railway.json` | Tells Railway to build the Dockerfile and health-check `/facets`. |
| `data/catalog.parquet`, `data/facets.json` | Built catalog (~4 MB), committed so Railway's build can copy it. |
| `vercel.json` | Static site: no install step, build runs `deploy/write-config.mjs`, serves `app/static`, rewrites `/static/*` to the root. |
| `.vercelignore` | Uploads only `app/static`, `deploy/`, and `vercel.json` to Vercel. |
| `deploy/write-config.mjs` | Writes `config.js` from `API_BASE_URL`; fails the build if it is missing. |
| `app/static/config.js` | `window.API_BASE`. Empty in the repo (same origin). |
| `app/main.py` → `cors_origins()` | Reads `CORS_ORIGINS` (comma-separated) and enables CORS for those origins only. |

### Why the catalog is committed

Ingestion downloads the Hugging Face dataset (about 550 MB of cache), then parses and dedupes it. That is too slow and memory-hungry for a build step, and it would repeat on every deploy. The finished catalog is about 4 MB of public dataset content, so it is built once locally and committed. Rebuild and recommit it whenever ingestion changes.

## Environment variables

**Railway (backend)**

| Variable | Value |
| --- | --- |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` |
| `LLM_API_KEY` | Your Groq key (console.groq.com/keys) |
| `LLM_MODEL` | `openai/gpt-oss-120b` |
| `LLM_RESPONSE_FORMAT` | `json_schema` |
| `CORS_ORIGINS` | The Vercel production URL, e.g. `https://zomatoreco.vercel.app` (no trailing slash; comma-separate several) |
| Optional | `CANDIDATE_POOL`, `DEFAULT_LIMIT`, `LLM_TIMEOUT_SECONDS`. Bad values stop the app at startup. |

Railway sets `PORT`. The image sets `CATALOG_PATH`.

**Vercel (frontend)**

| Variable | Value |
| --- | --- |
| `API_BASE_URL` | The Railway public URL, e.g. `https://zomatoreco-production.up.railway.app` |

## 1. Prepare locally

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m ingest.build_catalog      # only if data/ is missing or ingestion changed
pytest                              # offline; should pass
```

Install the CLIs and log in (each opens a browser):

```bash
npm i -g @railway/cli vercel
railway login
vercel login
```

## 2. Deploy the backend on Railway

From the repo root:

```bash
railway init --name zomatoreco      # creates the project and links this folder
railway up --detach                 # uploads the folder; Railway builds the Dockerfile
railway service                     # link the service the upload created, if not linked
railway variables \
  --set "LLM_BASE_URL=https://api.groq.com/openai/v1" \
  --set "LLM_API_KEY=<your Groq key>" \
  --set "LLM_MODEL=openai/gpt-oss-120b" \
  --set "LLM_RESPONSE_FORMAT=json_schema"
railway domain                      # generates the public *.up.railway.app URL
```

`railway up` respects `.gitignore`, which is why the catalog must not be ignored. Setting variables triggers a redeploy. Check it:

```bash
curl -s https://<railway-url>/facets | head -c 200     # expect JSON with localities
```

The Railway dashboard works too: **New Project → Deploy from GitHub repo** picks up `railway.json`; add the variables under **Variables** and click **Generate Domain** under **Settings → Networking**.

## 3. Deploy the frontend on Vercel

From the repo root:

```bash
vercel link --yes --project zomatoreco
printf 'https://<railway-url>' | vercel env add API_BASE_URL production
vercel deploy --prod
```

Vercel uploads only what `.vercelignore` allows, runs `node deploy/write-config.mjs`, and serves `app/static`. Note the production URL it prints (e.g. `https://zomatoreco.vercel.app`).

## 4. Connect them: allow the frontend origin

```bash
railway variables --set "CORS_ORIGINS=https://zomatoreco.vercel.app"
```

Railway redeploys. Without this step the page loads but every API call fails with a CORS error in the browser console.

Vercel preview deployments get their own URLs, which are not in `CORS_ORIGINS`, so previews cannot call the API unless you add their origins too.

## 5. Verify

```bash
API=https://<railway-url>
WEB=https://zomatoreco.vercel.app

# Backend: catalog loaded
curl -s $API/facets | head -c 200

# Backend: full path through the model, expect recommendations
curl -s -X POST $API/recommendations -H 'Content-Type: application/json' \
  -d '{"locality":"Banashankari","budget":"medium","min_rating":4.0,"cuisine":"Italian"}'

# CORS: expect access-control-allow-origin: $WEB
curl -si -X OPTIONS $API/recommendations -H "Origin: $WEB" \
  -H 'Access-Control-Request-Method: POST' -H 'Access-Control-Request-Headers: content-type' \
  | grep -i access-control-allow-origin

# Frontend: config points at the backend
curl -s $WEB/static/config.js
```

Then open the Vercel URL and run a search through the form.

| Symptom | Likely cause |
| --- | --- |
| Page says the restaurant list is not available; console shows a CORS error | `CORS_ORIGINS` missing or does not exactly match the Vercel URL (scheme, no trailing slash). |
| Page calls `vercel.app/facets` and gets 404 | `config.js` still empty: `API_BASE_URL` was not set when Vercel built. Set it and redeploy. |
| Vercel build fails with "API_BASE_URL is not set" | Same; add the variable for the Production environment. |
| 503 from the API | Catalog files missing from the image. Check they are committed and `COPY data/...` succeeded. |
| 502 on searches that match restaurants | LLM variables wrong, or Groq rate limit. Check `railway logs`; retry after ~25 seconds. |
| Railway deploy fails health check | App did not start: bad `LLM_RESPONSE_FORMAT`, `CANDIDATE_POOL`, or `DEFAULT_LIMIT`. `railway logs` names it. |

## Updating

- **Backend code:** `railway up --detach` (or push, if the service deploys from GitHub).
- **Frontend code:** `vercel deploy --prod` (or push, if the project is connected to GitHub).
- **Catalog:** rerun `python -m ingest.build_catalog`, commit `data/`, redeploy the backend.
- **Railway URL changes:** update `API_BASE_URL` in Vercel and redeploy the frontend.
- **Vercel URL changes:** update `CORS_ORIGINS` in Railway.
- **Key rotation:** `railway variables --set "LLM_API_KEY=..."`.

## Before sharing the URL publicly

The API has no authentication and no rate limiting. CORS only stops other websites' pages from calling it in a browser. Scripts and `curl` can still call it, and each request that matches restaurants spends your Groq quota.

- On Groq's free tier, a few requests a minute exhaust the token allowance and everyone gets 502 until it resets. For more than a demo, use a paid tier or `LLM_MODEL=openai/gpt-oss-20b`.
- Set a spending limit in the Groq console on a paid tier.
- If abuse appears, add per-IP rate limiting (for example `slowapi`).
- Railway's free trial credit runs out; check the plan before relying on the backend staying up.
