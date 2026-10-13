# ZomatoReco Architecture

This document describes how to build the restaurant recommendation service defined in `problemStatement.md`: collect diner preferences, narrow a real Zomato catalog with structured filters, ask a large language model to rank and explain the remaining options, and show a short list the user can act on.

The catalog is the Hugging Face dataset [ManikaSaini/zomato-restaurant-recommendation](https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation): about 51,700 rows and 574 MB, covering Bangalore restaurants. The same restaurant often appears more than once because it is listed under several meal types and neighborhoods.

## Design principles

1. **Filter before the model.** Location, cuisine, budget, and minimum rating are deterministic. The LLM ranks and explains a small candidate set. It does not search the full catalog.
2. **Ground every recommendation.** Each result must refer to a restaurant id that survived filtering. Names, ratings, cuisines, and costs shown in the UI come from the catalog, and the model supplies rank and explanation only.
3. **Keep prompts small.** Full `reviews_list` values can be over a megabyte. The prompt receives a compact profile: identity, rating, votes, cost, cuisines, restaurant type, liked dishes, and at most one short review excerpt.
4. **Prepare data once.** Download, clean, and deduplicate offline. A recommendation request reads a local catalog and does not hit Hugging Face.
5. **Treat soft preferences as language.** “Family-friendly” and “quick service” are not columns. The model uses restaurant type, liked dishes, and a review excerpt to judge them, and says when the catalog does not support a claim.

## System context

```mermaid
flowchart LR
    User[Diner] --> UI[Web UI]
    UI --> API[Recommendation API]
    API --> Filter[Candidate filter]
    Filter --> Catalog[(Local catalog)]
    API --> LLM[LLM provider]
    LLM --> API
    API --> UI
    Prep[Ingestion job] --> HF[Hugging Face dataset]
    Prep --> Catalog
```

| Actor | Responsibility |
| --- | --- |
| Diner | Chooses locality, budget, cuisine, minimum rating, and optional free-text preferences |
| Web UI | Collects input, calls the API, and renders the ranked shortlist |
| Recommendation API | Validates input, runs the filter, builds the prompt, calls the model, and returns grounded results |
| Local catalog | Cleaned, deduplicated restaurants ready for filtering |
| Ingestion job | Downloads the dataset, normalizes fields, and writes the catalog |
| LLM provider | Ranks the candidates and writes explanations from the supplied profiles only |

## Runtime request flow

```mermaid
sequenceDiagram
    participant U as Web UI
    participant A as Recommendation API
    participant C as Local catalog
    participant L as LLM provider

    U->>A: POST /recommendations
    A->>A: Validate preferences
    A->>C: Filter by locality, cuisine, budget, rating
    C-->>A: Matching restaurants
    A->>A: Rank by rating and votes, keep top N profiles
    alt No candidates
        A-->>U: Empty result with the filters that eliminated everything
    else Candidates exist
        A->>L: Prompt with preferences and candidate profiles
        L-->>A: JSON ranks, explanations, optional summary
        A->>A: Drop unknown ids, attach catalog fields
        A-->>U: Top recommendations
    end
```

Target latency for a warm catalog is a filter under a few hundred milliseconds plus one model call. The candidate cap is what keeps that call predictable.

## Components

### 1. Ingestion job

A one-shot script, re-run when the dataset should be refreshed.

Steps:

1. Load `ManikaSaini/zomato-restaurant-recommendation` with the Hugging Face `datasets` library.
2. Normalize each row into the catalog schema below.
3. Drop rows with no restaurant name.
4. Deduplicate on normalized name plus address. When duplicates disagree, keep the row with the higher vote count, then the higher rating.
5. Build lookup lists for localities and cuisines so the UI can offer real choices.
6. Write `data/catalog.parquet` (or SQLite if Parquet tooling is inconvenient) and `data/facets.json`.

Raw review blobs stay out of the catalog used at request time. Store a single excerpt of at most 400 characters, preferring a review whose numeric rating is present, so soft-preference reasoning has some text without dominating the prompt.

### 2. Catalog

One row per restaurant.

| Field | Source | Normalization |
| --- | --- | --- |
| `id` | Generated | Stable hash of normalized name and address |
| `name` | `name` | Trimmed, encoding repaired where obvious |
| `address` | `address` | Trimmed |
| `locality` | `location` | Trimmed; this is a Bangalore neighborhood such as Banashankari, not a city |
| `listed_city` | `listed_in(city)` | Kept for display context |
| `cuisines` | `cuisines` | Lowercased list split on commas |
| `rest_type` | `rest_type` | List split on commas, for example Cafe, Quick Bites, Casual Dining |
| `cost_for_two` | `approx_cost(for two people)` | Integer rupees; commas removed |
| `rating` | `rate` | Float from values like `4.1/5`; unparseable values become null |
| `votes` | `votes` | Integer |
| `online_order` | `online_order` | Boolean |
| `book_table` | `book_table` | Boolean |
| `dish_liked` | `dish_liked` | Short list, capped |
| `review_excerpt` | `reviews_list` | One short plain-text excerpt |
| `url` | `url` | Original Zomato link, shown as a reference and never sent as a ranking signal |

`phone` and full `menu_item` / `reviews_list` payloads are omitted from the request-time catalog. They are large, uneven, and unused by the recommendation contract.

**Budget bands** are applied to `cost_for_two` and kept in configuration so they can be tuned:

| Band | Cost for two (INR) |
| --- | --- |
| low | up to 400 |
| medium | 401 to 800 |
| high | above 800 |

Rows with a null cost fail a budget filter. Rows with a null rating fail a minimum-rating filter. The API reports how many rows each rule removed so an empty screen is explainable.

**Locality scope.** The problem statement lists Delhi and Bangalore as examples. This dataset’s `location` values are Bangalore neighborhoods (about 93). The UI asks for a locality from `facets.json`. A later catalog of other cities can reuse the same field without changing the request contract: `locality` remains the filter key.

### 3. Recommendation API

A small HTTP service. FastAPI is a good fit because the ingestion code, filtering, and model client are all Python.

`POST /recommendations`

```json
{
  "locality": "Banashankari",
  "budget": "medium",
  "cuisine": "Italian",
  "min_rating": 4.0,
  "preferences": "family-friendly, quick service",
  "limit": 5
}
```

| Field | Rule |
| --- | --- |
| `locality` | Required. Case-insensitive match against known localities |
| `budget` | Required. One of `low`, `medium`, `high` |
| `cuisine` | Required. Case-insensitive substring match against any cuisine tag |
| `min_rating` | Required. Number from 0 to 5 |
| `preferences` | Optional free text, length-capped (for example 300 characters) |
| `limit` | Optional. Default 5, maximum 8 |

`GET /facets` returns sorted localities and cuisines from `facets.json` so the form does not invent values the catalog cannot match.

Validation failures return HTTP 400 with field errors. A valid query that matches nothing returns HTTP 200 with an empty list and a `filter_stats` object.

### 4. Candidate filter

Pure functions over the in-memory catalog (loaded once at process start). Order of operations:

1. Locality equality on the normalized locality.
2. Cuisine tag contains the requested cuisine.
3. Cost falls inside the budget band.
4. Rating is present and greater than or equal to `min_rating`.
5. Sort the survivors by rating descending, then votes descending.
6. Keep the top `candidate_pool` rows (default 20) as model input.

If fewer than `limit` restaurants survive, the API still calls the model on whatever remains, down to one row. Zero rows skip the model call.

The pre-sort is a recall aid. The model may reorder the pool using cuisine fit, restaurant type, liked dishes, and the free-text preferences. It may not add restaurants from outside the pool.

### 5. Prompt and model client

One chat completion per request. The provider sits behind a thin interface (`complete(system, user) -> str`) so the HTTP and parsing code stay the same for OpenAI-compatible APIs, Groq, Gemini, or a local model. The model name, base URL, and API key come from environment variables.

**System prompt duties**

- Rank only the supplied restaurants.
- Use catalog facts for rating, cost, and cuisine. Do not invent dishes, awards, or ambience.
- Use `preferences` only when `rest_type`, `dish_liked`, or `review_excerpt` supports the claim. Otherwise say the catalog does not show that trait.
- Return JSON only, matching the schema below.
- Produce at most `limit` items, best first.

**User message contents**

- The normalized preferences.
- A JSON array of candidate profiles: `id`, `name`, `locality`, `cuisines`, `rest_type`, `cost_for_two`, `rating`, `votes`, `online_order`, `book_table`, `dish_liked`, `review_excerpt`.

**Expected model JSON**

```json
{
  "summary": "Short paragraph comparing the set.",
  "recommendations": [
    {
      "id": "catalog-id",
      "rank": 1,
      "explanation": "Two or three sentences tied to the user's preferences."
    }
  ]
}
```

**Response assembly**

1. Parse JSON. If the model wraps it in markdown fences, strip one fence pair and parse again.
2. On parse failure, retry once with a shorter repair prompt that includes the invalid text. A second failure returns HTTP 502 and does not show partial prose as if it were a ranking.
3. Drop recommendation objects whose `id` is not in the candidate pool.
4. Sort by `rank`.
5. Join each surviving id to catalog fields. The UI-bound rating, cost, cuisine, and name always come from the catalog.
6. If every id was dropped, return HTTP 502 rather than an empty success, because the filter did find restaurants and the model failed to ground them.

Temperature stays low (around 0.2) so rankings are stable across repeated clicks.

### 6. Web UI

A single page is enough for the success criteria.

- Locality and cuisine are select or searchable inputs fed by `GET /facets`.
- Budget is three options. Minimum rating is a numeric input or slider from 0 to 5, step 0.1.
- Additional preferences are an optional text field with the examples from the problem statement (family-friendly, quick service).
- Submit calls `POST /recommendations` and shows a loading state for the model call.
- Each card shows restaurant name, cuisine, rating, estimated cost for two, and the AI explanation, in that order.
- A summary paragraph sits above the cards when the model returns one.
- An empty state lists which filters removed all rows and invites the user to widen locality, cuisine, budget, or rating.
- Errors from validation and from the model are shown as plain sentences.

Streamlit or a minimal FastAPI-served page both satisfy this. A separate React app is optional and does not change the API.

## Suggested repository layout

```text
ZomatoReco/
  architecture.md
  problemStatement.md
  README.md
  requirements.txt
  .env.example
  app/
    main.py              # HTTP routes
    schemas.py           # request and response models
    catalog.py           # load catalog, facets, filters
    recommend.py         # pool selection, prompt, grounding
    llm.py               # provider client
  ingest/
    build_catalog.py     # Hugging Face download and normalization
  data/                  # generated, gitignored
    catalog.parquet
    facets.json
  tests/
    test_normalize.py
    test_filter.py
    test_grounding.py
```

`data/` is generated and stays out of git. `.env` holds the model API key and stays out of git. `.env.example` lists the variable names without secrets.

## Configuration

| Variable | Purpose |
| --- | --- |
| `LLM_BASE_URL` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | Secret for that endpoint |
| `LLM_MODEL` | Model name |
| `CATALOG_PATH` | Path to the local catalog |
| `CANDIDATE_POOL` | Max restaurants sent to the model (default 20) |
| `DEFAULT_LIMIT` | Recommendations returned (default 5) |

Budget thresholds live in code next to the filter so tests can pin them.

## Failure behavior

| Situation | Behavior |
| --- | --- |
| Unknown locality or cuisine | 400 with the closest message that the value is not in the catalog facets |
| Budget or rating out of range | 400 |
| Catalog file missing | 503 asking the operator to run the ingestion job |
| Zero restaurants after filters | 200, empty list, filter stats |
| Model timeout or HTTP error | 502, no fabricated list |
| Model JSON invalid twice | 502 |
| Model cites ids outside the pool | Those items are removed; remaining items are returned |

## Testing

Tests stay offline. They do not call Hugging Face or a live model.

- **Normalization:** `4.1/5` becomes `4.1`; `1,000` cost becomes `1000`; comma-separated cuisines become a list; duplicate name-and-address rows collapse.
- **Filter:** a fixture of a few restaurants checks locality, cuisine substring, each budget band, minimum rating, null rating, and null cost.
- **Grounding:** a fake model client returns one known id, one unknown id, and fenced JSON. The assembler keeps the known id, fills rating and cost from the fixture, and rejects an all-unknown payload.

A manual check after ingestion confirms `GET /facets` lists Bangalore localities such as Banashankari, and a sample query (medium budget, a common cuisine, minimum rating 4) returns cards whose numbers match the catalog.

## Build order

1. Ingestion script and catalog schema, including deduplication and facet files.
2. Filter functions and their tests.
3. API schemas, `GET /facets`, and `POST /recommendations` returning the deterministic top restaurants with a placeholder explanation.
4. Model client, prompt, JSON parsing, and id grounding.
5. Single-page UI wired to both endpoints, including the empty state.
6. Manual pass against a live model key with the sample preferences from the problem statement.

Step 3 is intentionally useful before any API key exists: the page can already show name, cuisine, rating, and cost. Step 4 replaces the placeholder explanation with the model text.

## Out of scope for the first version

Accounts, saved preferences, live Zomato search, maps, booking, and multi-turn chat. Those can sit on the same catalog and API later. The first version is complete when a diner submits the preferences in the problem statement and sees a ranked, explained shortlist whose facts come from the local catalog.
