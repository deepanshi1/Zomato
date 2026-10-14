"""HTTP routes: GET /facets and POST /recommendations."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.catalog import (
    DEFAULT_CANDIDATE_POOL,
    DEFAULT_CATALOG_PATH,
    CatalogNotFoundError,
    filter_candidates,
    get_catalog,
)
from app.schemas import (
    MAX_LIMIT,
    ErrorResponse,
    Facets,
    FieldError,
    Recommendation,
    RecommendationRequest,
    RecommendationResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
PLACEHOLDER_EXPLANATION = (
    "Ranked by rating, then number of votes. "
    "Personalized explanations appear once the language model is connected."
)


@dataclass(frozen=True)
class Settings:
    catalog_path: Path
    candidate_pool: int
    default_limit: int

    @property
    def facets_path(self) -> Path:
        return self.catalog_path.parent / "facets.json"


def get_settings() -> Settings:
    """Read configuration from the environment. Raises ValueError on bad values."""
    pool = _int_env("CANDIDATE_POOL", DEFAULT_CANDIDATE_POOL)
    limit = _int_env("DEFAULT_LIMIT", DEFAULT_LIMIT)
    if pool < 1:
        raise ValueError(f"CANDIDATE_POOL must be at least 1, got {pool}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"DEFAULT_LIMIT must be between 1 and {MAX_LIMIT}, got {limit}")
    return Settings(
        catalog_path=Path(os.environ.get("CATALOG_PATH", DEFAULT_CATALOG_PATH)),
        candidate_pool=pool,
        default_limit=limit,
    )


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fail fast on bad configuration
    try:
        catalog = get_catalog()
        logger.info("Loaded catalog with %d restaurants", len(catalog.rows))
    except CatalogNotFoundError as exc:
        logger.warning("%s Requests will return 503 until it exists.", exc)
    yield


app = FastAPI(title="ZomatoReco", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CatalogUnavailable(Exception):
    pass


def _error(status: int, detail: str, errors: list[FieldError] | None = None) -> JSONResponse:
    body = ErrorResponse(detail=detail, errors=errors or [])
    return JSONResponse(status_code=status, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        path = [str(part) for part in err.get("loc", ()) if part != "body"]
        errors.append(FieldError(field=".".join(path) or "body", message=err.get("msg", "Invalid value")))
    return _error(400, "Invalid request.", errors)


@app.exception_handler(CatalogUnavailable)
async def _catalog_unavailable(request: Request, exc: CatalogUnavailable) -> JSONResponse:
    return _error(503, str(exc))


def _load_catalog():
    try:
        return get_catalog()
    except CatalogNotFoundError as exc:
        raise CatalogUnavailable(
            "The restaurant catalog is not available. "
            "Run `python -m ingest.build_catalog` to build it, then retry."
        ) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/facets", response_model=Facets, responses={503: {"model": ErrorResponse}})
def facets() -> Facets:
    path = get_settings().facets_path
    if not path.is_file():
        raise CatalogUnavailable(
            f"Facets file not found at {path}. "
            "Run `python -m ingest.build_catalog` to build it, then retry."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return Facets(
        localities=sorted(data.get("localities", []), key=str.casefold),
        cuisines=sorted(data.get("cuisines", [])),
    )


@app.post(
    "/recommendations",
    response_model=RecommendationResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def recommendations(body: RecommendationRequest):
    settings = get_settings()
    catalog = _load_catalog()

    locality = catalog.canonical_locality(body.locality)
    errors = []
    if locality is None:
        errors.append(FieldError(field="locality", message=f"'{body.locality}' is not a known locality."))
    if not catalog.has_cuisine(body.cuisine):
        errors.append(FieldError(field="cuisine", message=f"'{body.cuisine}' does not match any cuisine in the catalog."))
    if errors:
        return _error(400, "Invalid request.", errors)

    result = filter_candidates(
        catalog.rows,
        locality=locality,
        cuisine=body.cuisine,
        budget=body.budget,
        min_rating=body.min_rating,
        pool_size=settings.candidate_pool,
    )
    limit = body.limit or settings.default_limit
    shortlist = result.candidates[:limit]

    cards = [
        Recommendation(
            id=row["id"],
            rank=rank,
            name=row["name"],
            cuisines=row["cuisines"],
            rating=row["rating"],
            cost_for_two=row["cost_for_two"],
            explanation=PLACEHOLDER_EXPLANATION,
            url=row.get("url"),
        )
        for rank, row in enumerate(shortlist, start=1)
    ]
    summary = None
    if cards:
        summary = (
            f"Top {len(cards)} of {result.matched} matching restaurants in {locality}, "
            "ordered by rating and then votes."
        )
    return RecommendationResponse(summary=summary, recommendations=cards, filter_stats=result.stats())
