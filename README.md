# ZomatoReco

Restaurant recommendations for Bangalore. The service filters a local Zomato catalog by locality, budget, minimum rating, and an optional cuisine, then asks a language model to rank and explain the matches.

Design: `architecture.md`. Build steps: `implementation-plan.md`.

## Run order

1. Create a virtualenv:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install requirements:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure the environment:

   ```bash
   cp .env.example .env   # then fill in LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
   ```

4. Build the catalog (downloads the Hugging Face dataset once, writes `data/catalog.parquet` and `data/facets.json`):

   ```bash
   python -m ingest.build_catalog
   ```

5. Start the API:

   ```bash
   uvicorn app.main:app --reload --env-file .env
   ```

   `--env-file` loads the model settings. Without them, queries that match restaurants return HTTP 502; queries that match nothing still return an empty list.

   The model runs on Groq: `LLM_BASE_URL=https://api.groq.com/openai/v1`, a key from console.groq.com/keys, and `LLM_MODEL=openai/gpt-oss-120b` with `LLM_RESPONSE_FORMAT=json_schema` (see `.env.example`). The client appends `/chat/completions`. Groq's free tier rate-limits requests; a limited request returns 502 and can be retried after a few seconds.

6. Open **http://localhost:8000** and pick a locality, a budget, a minimum rating, and optionally a cuisine (“All cuisines” is the default). The API docs are at http://localhost:8000/docs.

## Tests

```bash
pytest
```

Tests run offline. They use small fixtures and a fake model client.

## End-to-end check findings (Phase 6, 2026-10-15)

Run against the real catalog (12,492 restaurants) and live Groq (`openai/gpt-oss-120b`), driven through the page in Chrome.

| Scenario | Result |
| --- | --- |
| Banashankari, medium, Italian, 4.0, “family-friendly, quick service” | 5 cards from 7 matches; every name, rating, cost, and cuisine matches its catalog row |
| Banashankari, high, Afghan, 4.9 | Empty state: “We found 294 restaurants in Banashankari, but none serve Afghan.” No model call |
| Koramangala 5th Block, high, North Indian, rating 0, “good for a date” | 23 matches capped to a pool of 20; 5 grounded cards |
| Jayanagar, low, all cuisines, 4.3, “quick breakfast” | 5 grounded cards across 5 different cuisine mixes |
| Model unreachable | Error sentence, no cards |
| Unknown locality | Blocked in the form, no request sent |

**Prompt changes made after the check**

1. The first run inferred traits from broad restaurant types (“Casual Dining, which often suits families”, “Delivery suggests quick service”), and the summary called a restaurant family-friendly without evidence. One explanation also called a ₹2,100 cost “well above the budget threshold” although it sits inside the high band. The system prompt now says a trait counts only when `rest_type`, `dish_liked`, or the review states or directly names it, forbids hedges such as “often suits” or “may be”, and says every candidate already fits the budget.
2. That stricter rule made the model return a single pick when few candidates showed the requested trait (1 of 20, 1 of 13). The prompt now asks for exactly the requested number of picks, ranking weaker fits lower and stating what the catalog does not show.

After both changes, all 15 automated checks passed, and a read-through found no unsupported trait claims and no misquoted numbers.

**No change to the budget bands.** The low (≤ ₹400), medium (₹401–800), and high (> ₹800) bands each returned useful pools in the check.

**Known issues**

- **Groq free-tier rate limits.** A request with a full pool of 20 profiles can use up the per-minute token allowance; the next request then returns 502 (“could not rank them right now”) until Groq's `retry-after` passes, about 25 seconds in testing. A paid tier or `openai/gpt-oss-20b` would ease this.
- **Leftover encoding damage.** About 9% of review excerpts (889 of 10,014) and 73 restaurant names still contain mojibake such as `cafÃÃÃÃ©`, where the text was mis-encoded more than once. Ingestion repairs only single-layer damage. Names show on cards, so a stronger repair at ingestion would be worth adding.
- **Missing ratings.** 24% of restaurants (mostly `NEW` listings) have no rating, so they never pass a minimum-rating filter, even at 0.
