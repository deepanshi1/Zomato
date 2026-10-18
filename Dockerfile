FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Runtime packages only; ingestion (datasets) and tests (pytest) are not needed here.
RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" \
    "pyarrow>=16.0" "pandas>=2.2" "httpx>=0.27"

COPY app ./app
COPY data/catalog.parquet data/facets.json ./data/

ENV CATALOG_PATH=data/catalog.parquet
EXPOSE 8000

# Railway sets PORT; default to 8000 elsewhere.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
