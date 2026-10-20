# ZomatoReco Implementation Plan

This plan builds the service described in `problemStatement.md` using the design in `architecture.md`. Each phase leaves the repo runnable and tested before the next one starts. The API can return real restaurants before any model key exists. The model is added only after filtering and grounding are in place.

The first version is complete when a diner submits locality, budget, minimum rating, an optional cuisine (or “All cuisines”), and optional preferences, and sees a ranked shortlist whose name, cuisine, rating, and cost come from the local catalog, with an explanation for each restaurant.

## How to use this plan

- Finish a phase only when its exit checks pass.
- Keep tests offline. They use small fixtures and a fake model client. They do not download Hugging Face data or call a live model.
- Leave accounts, saved preferences, live Zomato search, maps, booking, and multi-turn chat out of every phase.

## Phase 0 — Project skeleton

**Goal.** Create the layout, dependencies, and configuration the later phases import.

**Tasks**

1. Add `requirements.txt` with FastAPI, Uvicorn, Pydantic, `datasets`, PyArrow, Pandas, HTTPX, and Pytest.
2. Add the package folders from the architecture: `app/`, `ingest/`, `tests/`, and an empty `data/` directory.
3. Add `.env.example` with `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `CATALOG_PATH`, `CANDIDATE_POOL`, and `DEFAULT_LIMIT`. Phase 4 adds `LLM_RESPONSE_FORMAT` and fills in the Groq defaults.
4. Add `.gitignore` entries for `.env`, `data/`, `__pycache__/`, and `.venv/`.
5. Add a short `README.md` that states the run order: create a virtualenv, install requirements, run ingestion, start the API.

**Exit checks**

- `pip install -r requirements.txt` succeeds in a fresh virtualenv.
- `.env` is gitignored. `.env.example` contains names only, no secrets.

## Phase 1 — Catalog ingestion

**Goal.** Turn the Hugging Face dataset into one local row per restaurant, plus facet lists for the form.

**Satisfies.** Problem-statement step “Data ingestion”: load `ManikaSaini/zomato-restaurant-recommendation` and extract name, location, cuisine, cost, and rating.

**Tasks**

1. Implement `ingest/build_catalog.py` to load the dataset with the Hugging Face `datasets` library.
2. Normalize each row into the catalog schema in `architecture.md`:
   - Stable `id` from normalized name and address.
   - Trimmed `name` and `address`, with obvious encoding repair.
   - `locality` from `location` (Bangalore neighborhood).
   - `listed_city` from `listed_in(city)`.
   - `cuisines` and `rest_type` as lists split on commas. Cuisine tags are lowercased.
   - `cost_for_two` as an integer, commas removed. Unparseable cost becomes null.
   - `rating` as a float parsed from values such as `4.1/5`. Unparseable rating becomes null.
   - `votes` as an integer.
   - `online_order` and `book_table` as booleans.
   - `dish_liked` as a short capped list.
   - `review_excerpt` as one plain-text excerpt of at most 400 characters, preferring a review that has a numeric rating.
   - `url` retained for display and excluded from model profiles.
3. Drop rows with no restaurant name.
4. Deduplicate on normalized name plus address. When duplicates disagree, keep the higher vote count, then the higher rating.
5. Omit `phone`, full `reviews_list`, and `menu_item` from the request-time catalog.
6. Write `data/catalog.parquet` and `data/facets.json` (sorted unique localities and cuisines).
7. Add `tests/test_normalize.py` with fixtures, not the full download:
   - `4.1/5` becomes `4.1`.
   - `1,000` becomes `1000`.
   - `"North Indian, Chinese"` becomes a two-item list.
   - Two rows with the same name and address collapse to one, keeping the higher vote count.
   - A missing name is dropped.
   - The excerpt is at most 400 characters.

**Exit checks**

- `pytest tests/test_normalize.py` passes.
- Running the script once produces `data/catalog.parquet` and `data/facets.json`.
- The catalog row count is lower than 51,717 because duplicates are collapsed.
- `facets.json` includes Bangalore localities such as Banashankari.
- A spot check shows rating and cost as numbers, and no full review blob stored on a row.

## Phase 2 — Candidate filter

**Goal.** Select a small, ordered pool from the catalog using deterministic rules.

**Satisfies.** The structured half of the integration layer: location, budget, cuisine (when given), and minimum rating narrow the catalog before any prompt is built.

**Tasks**

1. Implement catalog loading in `app/catalog.py`. Load the Parquet file once at process start and keep it in memory.
2. Put budget bands next to the filter so tests can pin them:
   - low: cost for two up to 400
   - medium: 401 to 800
   - high: above 800
3. Implement the filter in this order:
   1. Locality equality, case-insensitive, against known localities.
   2. Cuisine substring match against any cuisine tag. Cuisine is optional: when it is `None` (all cuisines), this rule removes nothing but still appears in the filter stats, so the stats always list the same four rules.
   3. Cost inside the budget band. Null cost fails the budget rule.
   4. Rating present and greater than or equal to `min_rating`. Null rating fails this rule.
   5. Sort by rating descending, then votes descending.
   6. Keep the top `CANDIDATE_POOL` rows (default 20).
4. Return filter stats: how many rows entered each rule and how many each rule removed, so an empty result can explain itself.
5. Add `tests/test_filter.py` on a fixture of a handful of restaurants covering:
   - locality match and mismatch
   - cuisine substring match
   - no cuisine (all cuisines) keeps every cuisine and reports 0 removed for the cuisine rule
   - each budget band
   - minimum rating
   - null cost excluded by a budget filter
   - null rating excluded by a minimum-rating filter
   - sort order of rating, then votes
   - pool cap

**Exit checks**

- `pytest tests/test_filter.py` passes.
- A fixture query for a medium-budget Italian restaurant in Banashankari at rating 4.0 returns only rows that satisfy every rule, best rating first.

## Phase 3 — Recommendation API without the model

**Goal.** Serve facets and a deterministic shortlist over HTTP. Explanations are placeholders so the contract is real before a model key exists.

**Satisfies.** User-input validation, and a display payload of name, cuisine, rating, and estimated cost.

**Tasks**

1. Define request and response models in `app/schemas.py`.
   - Request: `locality`, `budget` (`low` | `medium` | `high`), `min_rating` (0 to 5), optional `cuisine`, optional `preferences` capped at 300 characters, optional `limit` defaulting to 5 and capped at 8.
   - `cuisine` omitted, blank, or one of `all`, `all cuisines`, `any` (any case) means all cuisines and is passed to the filter as `None`.
   - Response: `summary`, `recommendations` (id, rank, name, cuisines, rating, cost for two, explanation, url), and `filter_stats`.
2. Implement `app/main.py`:
   - `GET /facets` reads `data/facets.json` and returns sorted localities and cuisines.
   - `POST /recommendations` validates input, runs the Phase 2 filter, and returns the top `limit` rows from the pool.
   - Placeholder explanation text states that ranking is by rating and votes until the model is connected.
   - Unknown locality, a given cuisine that matches no tag, or budget or rating outside range: HTTP 400 with field errors. A missing cuisine is not an error.
   - Missing catalog file: HTTP 503 telling the operator to run the ingestion job.
   - Zero matches: HTTP 200 with an empty list and `filter_stats`.
3. Read `CATALOG_PATH`, `CANDIDATE_POOL`, and `DEFAULT_LIMIT` from the environment, with the defaults from the architecture.
4. Add API tests with the catalog fixture from Phase 2. Cover 400, 200-empty, a successful shortlist whose rating and cost match the fixture, and a request without a cuisine (and with `"all"`) that returns restaurants of several cuisines.

**Exit checks**

- `GET /facets` lists Banashankari after ingestion.
- `POST /recommendations` with locality Banashankari, budget medium, a common cuisine, and minimum rating 4 returns cards whose numbers match the catalog.
- The same request without `cuisine` returns 200 and the cuisine rule reports 0 removed.
- An impossible filter returns an empty list and stats, and does not error.
- Pytest for the API passes without a network call.

## Phase 4 — LLM ranking and grounding

**Goal.** Replace placeholder explanations with model rank, explanation, and summary, while every displayed fact still comes from the catalog.

**Satisfies.** The integration layer’s prompt handoff, and the recommendation engine: rank restaurants, explain why each fits, and optionally summarize the set.

**Provider: Groq.** The model runs on [Groq](https://console.groq.com) through its OpenAI-compatible chat completions API. The client stays provider-neutral (`LLM_*` variables, `complete(system, user)`), so switching provider later means changing `.env`, not code.

| Setting | Value |
| --- | --- |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` (the client appends `/chat/completions`) |
| `LLM_API_KEY` | A Groq API key from console.groq.com/keys, stored only in `.env` |
| `LLM_MODEL` | `openai/gpt-oss-120b` (default). Production model; supports strict JSON Schema output |
| `LLM_RESPONSE_FORMAT` | `json_schema` (default) or `json_object` |

Fallback model: `openai/gpt-oss-20b`. It is faster and supports strict JSON Schema; the exit check also runs it with `LLM_RESPONSE_FORMAT=json_object` to exercise the non-schema path. `llama-3.3-70b-versatile` appears in Groq's public model list but returned `model_not_found` for this project's key (checked 2026-10-14), so it is not the fallback. If an account does have it, pair it with `json_object`, because it does not support strict JSON Schema. Preview models are not used because Groq can retire them at short notice. Check the active model list (`GET /openai/v1/models`) when choosing a model, because availability differs by account and Groq deprecates models over time.

**Tasks**

1. Implement `app/llm.py` with `complete(system, user) -> str`. Use an OpenAI-compatible chat completion via HTTPX against Groq. Read `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_RESPONSE_FORMAT` from the environment. Set temperature around 0.2.
   - With `json_schema`, send `response_format` as `{"type": "json_schema", "json_schema": {"name": "recommendations", "strict": true, "schema": ...}}`, with the schema matching the reply shape below (all fields required, `additionalProperties: false`). Groq constrains decoding to the schema, so a malformed reply should be rare.
   - With `json_object`, send `{"type": "json_object"}`. This guarantees valid JSON syntax but not the shape. The system prompt must say to reply in JSON, which Groq requires for this mode.
   - Groq returns HTTP 400 with error code `json_validate_failed` when the model cannot produce valid JSON. Treat that like an unparseable reply, so it goes to the repair retry below rather than straight to 502. Every other 4xx or 5xx is a provider error.
   - HTTP 429 means a Groq rate limit, which is common on the free tier. Return 502 without an automatic retry, and log the `retry-after` header if present.
   - Never log or return the API key.
2. Implement `app/recommend.py`:
   - Build a system prompt that ranks only supplied restaurants, uses catalog facts for rating, cost, and cuisine, judges free-text preferences only from `rest_type`, `dish_liked`, and `review_excerpt`, and returns JSON only.
   - Build a user message with the request (locality, cuisine, budget band with its ₹ range, minimum rating), normalized preferences, and a JSON array of candidate profiles. When no cuisine was chosen, send the cuisine as “any (no cuisine filter)” so the model does not favour one. Profile fields: `id`, `name`, `locality`, `cuisines`, `rest_type`, `cost_for_two`, `rating`, `votes`, `online_order`, `book_table`, `dish_liked`, `review_excerpt`. Leave `url` out of the profile.
   - Ask for at most `limit` items, best first, in this shape:

```json
{
  "summary": "Short paragraph comparing the set.",
  "recommendations": [
    { "id": "catalog-id", "rank": 1, "explanation": "Two or three sentences tied to the user's preferences." }
  ]
}
```

   - Parse JSON. If the text is wrapped in one markdown fence, strip it and parse again. Keep this and the repair retry even with strict schema output: they cover `json_object` mode and a model switch.
   - On parse failure, retry once with a short repair prompt that includes the invalid text.
   - Drop ids that are not in the candidate pool. Sort remaining items by `rank`. Join each id to catalog fields so name, cuisines, rating, and cost on the response come from the catalog.
   - If the pool is empty, skip the model call and return the Phase 3 empty response.
   - If the pool is non-empty and every returned id is unknown, or JSON fails twice, or the provider times out or returns an HTTP error: HTTP 502 and no fabricated list.
3. Point `POST /recommendations` at this assembler. Remove the placeholder explanation path.
4. Add `tests/test_grounding.py` with a fake `complete` function:
   - Fenced JSON with one known id and one unknown id keeps the known id and fills rating and cost from the fixture.
   - A payload of only unknown ids is treated as a grounding failure.
   - Invalid JSON once, then valid JSON, succeeds via the repair retry.
   - Invalid JSON twice becomes a failure result the route maps to 502.
   - With a mock HTTP transport (no network): the request goes to `https://api.groq.com/openai/v1/chat/completions` with the Bearer key, model, temperature, and the configured `response_format`; a Groq 400 `json_validate_failed` leads to the repair retry; a 429 maps to 502.

**Exit checks**

- `pytest tests/test_grounding.py` passes with no live model call.
- A manual call with a real Groq key and `openai/gpt-oss-120b` returns explanations, and the rating and cost on each card still match the catalog row for that id.
- The same manual call with `openai/gpt-oss-20b` and `LLM_RESPONSE_FORMAT=json_object` also returns a grounded list.
- A query that matches nothing does not call the provider.

## Phase 5 — Single-page UI

**Goal.** Let a diner submit the preferences from the problem statement and read the shortlist, on a page that makes eating feel fun.

**Satisfies.** User input and output display: restaurant name, cuisine, rating, estimated cost, and AI-generated explanation.

**Files.** `app/static/index.html`, `app/static/styles.css`, `app/static/app.js`. FastAPI serves the page at `/` and the assets under `/static`. No build step, framework, or external images. The only external asset is the Quicksand and Inter fonts from Google Fonts, with system-font fallbacks so the page still works if they fail to load.

**Tasks**

1. Serve one page from FastAPI. A separate React app is unnecessary for this version.
2. Header: the heading **“Recommendation engine”** with the tagline **“Let's make eating fun.”** and one line on what the page does.
3. On load, call `GET /facets` and fill the locality and cuisine inputs as searchable inputs (`<input list>` with a `<datalist>`). If facets fail to load, say so and keep submit disabled.
4. Locality is required and must be a facet value, matched case-insensitively and snapped to the catalog spelling before submit.
5. Cuisine is optional (“Craving”, marked optional). The list starts with **“All cuisines”**. A blank field, “All cuisines”, “all”, or “any” sends no `cuisine` field. Any other value must be a facet value.
6. Offer budget as three choices with their ranges: low (up to ₹400), medium (₹401–800), high (above ₹800).
7. Offer minimum rating as a slider from 0 to 5 with step 0.1, showing the current value.
8. Offer an optional preferences field with placeholder “family-friendly, quick service” and a 300-character counter.
9. On submit, call `POST /recommendations`, disable the button, and show a loading state for the duration of the model call. A newer search replaces one still running; give up after 60 seconds with an error sentence.
10. Render a summary paragraph when one is present, then one card per recommendation in this order: name, cuisine, rating, estimated cost for two, explanation. Show a “View on Zomato” link only for `http`/`https` URLs, plus a note on how many matches the ranking drew from.
11. Empty state: show the filter stats in a sentence that names the rule that removed everything (for example “We found 294 restaurants in Banashankari, but none serve Afghan.”) and invite the diner to widen locality, cuisine, budget, or rating. With all cuisines, the sentence says “restaurants” rather than naming a cuisine.
12. Show validation errors next to their fields and model or server failures as plain sentences. Clear earlier cards on failure.
13. Insert all server text (names, cuisines, explanations, summary) with `textContent`, never as HTML: it comes from scraped listings and a language model.

**Visual design**

- **Pastel palette:** cream background with a faint dot pattern; pink, mint, butter yellow, lavender, peach, and sky accents. Text stays deep plum on every pastel so contrast holds. Thick dark outlines and hard pastel offset shadows give a playful, sticker-like look.
- **Food illustrations:** inline SVG symbols with small faces, drawn once and reused with `<use>`: burger and nigiri sushi above the heading; donut, pizza slice, boba, and maki floating in the margins on wide screens; a rolling maki as the loading spinner (“Rolling up your picks…”); a donut in the empty state; pizza, sushi, and burger in the initial placeholder.
- **Cards:** each card takes a different pastel shadow and rank colour; rating and cost appear as coloured pills; cards pop in one after another.
- **Budget choices** are pill buttons tinted mint, butter, and pink when selected; the submit button reads “Find my food”.
- **Dark mode** follows the system setting with a matching muted palette. Animations stop under `prefers-reduced-motion`.
- **Responsive:** one column below 780px, no horizontal scroll at 400px, floating side illustrations hidden on narrow screens.

**Exit checks**

- The form cannot submit a locality absent from `facets.json`, or a typed cuisine that is neither a facet value nor “All cuisines”. No request is sent in that case.
- A successful query shows the five display fields from the problem statement on every card.
- Choosing “All cuisines” (or leaving cuisine blank) sends no `cuisine` field and returns restaurants of more than one cuisine.
- An over-constrained query shows the empty state with the filter-stats sentence and stays on the page.
- A stopped model or a 502 shows an error sentence and does not show a partial ranking.
- At 400px wide the page has no horizontal scroll, and the browser console shows no errors.

## Phase 6 — End-to-end check

**Goal.** Confirm the success criteria on the real catalog and a live model.

**Tasks**

1. Run ingestion if `data/catalog.parquet` is missing.
2. Start the API with a configured `.env` (Groq settings from Phase 4).
3. In the browser, submit a sample a diner would actually use:
   - Locality: Banashankari
   - Budget: medium
   - Cuisine: Italian (or another cuisine present in that locality)
   - Minimum rating: 4
   - Preferences: family-friendly, quick service
4. Confirm each card’s rating and cost exist on the matching catalog row.
5. Confirm explanations refer to the submitted cuisine, budget, rating, or the optional preferences, and that unsupported traits are described as not shown in the catalog.
6. Repeat with a filter that should match nothing, with a rating of 0 so the pool is large and the candidate cap is doing work, and with “All cuisines” so the ranking spans several cuisines.
7. Record anything that should change the budget thresholds or the prompt, in the README, only after the check above.

**Exit checks**

- The sample query returns a ranked shortlist grounded in the local catalog.
- Each suggestion has a plain-language explanation.
- The empty-filter and error paths from Phase 5 still behave the same with the live model connected.
- The full offline test suite passes: normalization, filter, API, and grounding.

## Phase map

| Phase | Produces | Depends on |
| --- | --- | --- |
| 0 | Installable repo and config names | — |
| 1 | `catalog.parquet`, `facets.json`, normalization tests | Phase 0 |
| 2 | In-memory filter and filter tests | Phase 1 schema |
| 3 | `GET /facets`, deterministic `POST /recommendations` | Phase 2 |
| 4 | Groq-backed rank, explanation, summary, grounding tests | Phase 3, a Groq API key for the manual check |
| 5 | Pastel single page for the diner flow, with optional cuisine | Phase 3 endpoints; explanations appear once Phase 4 is done |
| 6 | Manual confirmation of the success criteria | Phases 1 through 5 |

Phase 5 can be built against Phase 3 and will show placeholder explanations until Phase 4 is merged. Phase 6 waits until both are done.
