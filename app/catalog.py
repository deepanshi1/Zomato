"""In-memory restaurant catalog and the deterministic candidate filter."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CATALOG_PATH = "data/catalog.parquet"
DEFAULT_CANDIDATE_POOL = 20

# Cost for two in INR, inclusive bounds. None means unbounded.
BUDGET_BANDS: dict[str, tuple[int | None, int | None]] = {
    "low": (None, 400),
    "medium": (401, 800),
    "high": (801, None),
}

# Allow for float noise such as 3.9999999 against a minimum of 4.0.
_RATING_EPSILON = 1e-9


class CatalogNotFoundError(FileNotFoundError):
    """The catalog file is missing; the ingestion job has not been run."""


class Catalog:
    """Read-only restaurant rows plus lookups for validation."""

    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.by_id = {row["id"]: row for row in rows}
        self._localities: dict[str, str] = {}
        cuisines: set[str] = set()
        for row in rows:
            if row.get("locality"):
                self._localities.setdefault(_fold(row["locality"]), row["locality"])
            cuisines.update(row.get("cuisines") or [])
        self.cuisines = sorted(cuisines)

    @classmethod
    def from_parquet(cls, path: str | Path) -> Catalog:
        path = Path(path)
        if not path.is_file():
            raise CatalogNotFoundError(
                f"Catalog not found at {path}. Run `python -m ingest.build_catalog` first."
            )
        import pyarrow.parquet as pq

        return cls(pq.read_table(path).to_pylist())

    @property
    def localities(self) -> list[str]:
        return sorted(self._localities.values(), key=str.casefold)

    def canonical_locality(self, value: str) -> str | None:
        """The catalog's spelling of a locality, matched case-insensitively."""
        return self._localities.get(_fold(value))

    def has_cuisine(self, value: str) -> bool:
        """True when any cuisine tag contains the value."""
        needle = _fold(value)
        return bool(needle) and any(needle in tag for tag in self.cuisines)


_catalog: Catalog | None = None


def get_catalog() -> Catalog:
    """The process-wide catalog, loaded from CATALOG_PATH on first use."""
    global _catalog
    if _catalog is None:
        _catalog = Catalog.from_parquet(os.environ.get("CATALOG_PATH", DEFAULT_CATALOG_PATH))
    return _catalog


def set_catalog(catalog: Catalog | None) -> None:
    """Replace the process-wide catalog (tests, reloads)."""
    global _catalog
    _catalog = catalog


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

@dataclass
class RuleStats:
    rule: str
    entered: int
    removed: int

    @property
    def remaining(self) -> int:
        return self.entered - self.removed


@dataclass
class FilterResult:
    candidates: list[dict[str, Any]]
    rules: list[RuleStats] = field(default_factory=list)
    matched: int = 0  # rows that passed every rule, before the pool cap

    def stats(self) -> dict[str, Any]:
        return {
            "rules": [
                {"rule": r.rule, "in": r.entered, "removed": r.removed, "out": r.remaining}
                for r in self.rules
            ],
            "matched": self.matched,
            "pool": len(self.candidates),
        }


def in_budget(cost: int | None, budget: str) -> bool:
    if cost is None:
        return False
    low, high = BUDGET_BANDS[budget]
    return (low is None or cost >= low) and (high is None or cost <= high)


def filter_candidates(
    rows: list[dict[str, Any]],
    *,
    locality: str,
    cuisine: str | None,
    budget: str,
    min_rating: float,
    pool_size: int = DEFAULT_CANDIDATE_POOL,
) -> FilterResult:
    """Apply locality, cuisine, budget, and rating rules in order, then sort and cap.

    A cuisine of None means all cuisines: the cuisine rule still reports its
    stats but removes nothing. Survivors are sorted by rating, then votes (both
    descending), then id so ties come out in the same order on every request.
    Input rows are not modified.
    """
    if budget not in BUDGET_BANDS:
        raise ValueError(f"Unknown budget {budget!r}; expected one of {sorted(BUDGET_BANDS)}")
    locality_key = _fold(locality)
    if not locality_key:
        raise ValueError("locality must be non-empty")
    cuisine_key = _fold(cuisine) if cuisine is not None else None
    if cuisine_key == "":
        raise ValueError("cuisine must be non-empty, or None for all cuisines")

    rules = [
        ("locality", lambda r: _fold(r.get("locality")) == locality_key),
        ("cuisine", lambda r: cuisine_key is None
            or any(cuisine_key in tag for tag in r.get("cuisines") or [])),
        ("budget", lambda r: in_budget(r.get("cost_for_two"), budget)),
        ("min_rating", lambda r: r.get("rating") is not None
            and r["rating"] + _RATING_EPSILON >= min_rating),
    ]

    survivors = rows
    stats: list[RuleStats] = []
    for name, keep in rules:
        entered = len(survivors)
        survivors = [row for row in survivors if keep(row)]
        stats.append(RuleStats(name, entered, entered - len(survivors)))

    survivors = sorted(survivors, key=lambda r: (-r["rating"], -(r.get("votes") or 0), r["id"]))
    return FilterResult(candidates=survivors[:pool_size], rules=stats, matched=len(survivors))


def _fold(value: Any) -> str:
    return " ".join(str(value).split()).casefold() if value else ""
