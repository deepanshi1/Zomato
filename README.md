# ZomatoReco

Restaurant recommendations for Bangalore. The service filters a local Zomato catalog by locality, budget, cuisine, and minimum rating, then asks a language model to rank and explain the matches.

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

## Tests

```bash
pytest
```

Tests run offline. They use small fixtures and a fake model client.
