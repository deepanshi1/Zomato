"""Build the request-time catalog from the Hugging Face Zomato dataset.

Usage:
    python -m ingest.build_catalog [--out-dir data]

Writes <out-dir>/catalog.parquet (one row per restaurant) and
<out-dir>/facets.json (sorted localities and cuisines for the form).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

DATASET_NAME = "ManikaSaini/zomato-restaurant-recommendation"

# Source column names in the dataset.
COL_NAME = "name"
COL_ADDRESS = "address"
COL_LOCATION = "location"
COL_LISTED_CITY = "listed_in(city)"
COL_CUISINES = "cuisines"
COL_REST_TYPE = "rest_type"
COL_COST = "approx_cost(for two people)"
COL_RATE = "rate"
COL_VOTES = "votes"
COL_ONLINE_ORDER = "online_order"
COL_BOOK_TABLE = "book_table"
COL_DISH_LIKED = "dish_liked"
COL_REVIEWS = "reviews_list"
COL_URL = "url"

REQUIRED_COLUMNS = [
    COL_NAME, COL_ADDRESS, COL_LOCATION, COL_LISTED_CITY, COL_CUISINES,
    COL_REST_TYPE, COL_COST, COL_RATE, COL_VOTES, COL_ONLINE_ORDER,
    COL_BOOK_TABLE, COL_DISH_LIKED, COL_REVIEWS, COL_URL,
]

EXCERPT_MAX_CHARS = 400
DISH_LIKED_MAX = 8
ID_LENGTH = 16

# Catalog columns, in output order. review_excerpt is filled after dedup.
CATALOG_FIELDS = [
    "id", "name", "address", "locality", "listed_city", "cuisines", "rest_type",
    "cost_for_two", "rating", "votes", "online_order", "book_table",
    "dish_liked", "review_excerpt", "url",
]


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

_MOJIBAKE = re.compile(r"[\xc2-\xf4][\x80-\xbf]|â€")


def repair_text(value: str) -> str:
    """Undo UTF-8 text that was decoded as Latin-1/CP1252, when the fix is clean."""
    if not _MOJIBAKE.search(value):
        return value
    for encoding in ("latin-1", "cp1252"):
        try:
            return value.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def clean_text(value: Any) -> str | None:
    """Trim, repair encoding, and collapse whitespace. Empty becomes None."""
    if value is None:
        return None
    text = repair_text(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_key(value: str | None) -> str:
    """Comparison form for dedup: case, accents, punctuation, and spacing ignored."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_id(name: str, address: str | None) -> str:
    key = f"{normalize_key(name)}|{normalize_key(address)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:ID_LENGTH]


_RATING = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:/\s*5\s*)?$")


def parse_rating(value: Any) -> float | None:
    """'4.1/5' -> 4.1. 'NEW', '-', blanks, and values outside 0-5 become None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        rating = float(value)
    else:
        match = _RATING.match(str(value))
        if not match:
            return None
        rating = float(match.group(1))
    if rating != rating or not 0.0 <= rating <= 5.0:  # NaN or out of range
        return None
    return round(rating, 1)


def parse_cost(value: Any) -> int | None:
    """'1,000' -> 1000. Unparseable, zero, or negative becomes None."""
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    try:
        cost = int(float(text))
    except ValueError:
        return None
    return cost if cost > 0 else None


def parse_votes(value: Any) -> int:
    try:
        votes = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0
    return max(votes, 0)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"yes", "true", "1"}


def split_list(value: Any, *, lower: bool = False, limit: int | None = None) -> list[str]:
    """Comma-separated text to a trimmed list with empty items and repeats removed."""
    text = clean_text(value)
    if not text:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        item = part.strip()
        if lower:
            item = item.lower()
        if not item or item.casefold() in seen:
            continue
        seen.add(item.casefold())
        items.append(item)
        if limit is not None and len(items) >= limit:
            break
    return items


# ---------------------------------------------------------------------------
# Review excerpt
# ---------------------------------------------------------------------------

_REVIEW_RATING = re.compile(r"(\d+(?:\.\d+)?)")
# The dataset prefixes each review body with "RATED\n"; plain "Rated ..." is real text.
_RATED_PREFIX = re.compile(r"^\s*RATED\s*\n")


def parse_reviews(value: Any) -> list[tuple[float | None, str]]:
    """Parse reviews_list, a string like "[('Rated 4.0', 'RATED\\n  Great food'), ...]"."""
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return []
    if not isinstance(value, (list, tuple)):
        return []

    reviews: list[tuple[float | None, str]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        rating_text, body = item[0], item[1]
        match = _REVIEW_RATING.search(str(rating_text or ""))
        rating = float(match.group(1)) if match else None
        reviews.append((rating, str(body or "")))
    return reviews


def truncate(text: str, limit: int = EXCERPT_MAX_CHARS) -> str:
    """Cut on a word boundary and end with an ellipsis. Result is at most `limit` chars."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def pick_excerpt(reviews: Iterable[tuple[float | None, str]]) -> str | None:
    """First review with a numeric rating, else the first with any text."""
    fallback: str | None = None
    for rating, body in reviews:
        text = clean_text(_RATED_PREFIX.sub("", body))
        if not text:
            continue
        if rating is not None:
            return truncate(text)
        if fallback is None:
            fallback = text
    return truncate(fallback) if fallback else None


# ---------------------------------------------------------------------------
# Rows, dedup, facets
# ---------------------------------------------------------------------------

def normalize_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One dataset row to a catalog row, without review_excerpt. None if it has no name."""
    name = clean_text(raw.get(COL_NAME))
    if not name:
        return None
    address = clean_text(raw.get(COL_ADDRESS))
    return {
        "id": make_id(name, address),
        "name": name,
        "address": address,
        "locality": clean_text(raw.get(COL_LOCATION)),
        "listed_city": clean_text(raw.get(COL_LISTED_CITY)),
        "cuisines": split_list(raw.get(COL_CUISINES), lower=True),
        "rest_type": split_list(raw.get(COL_REST_TYPE)),
        "cost_for_two": parse_cost(raw.get(COL_COST)),
        "rating": parse_rating(raw.get(COL_RATE)),
        "votes": parse_votes(raw.get(COL_VOTES)),
        "online_order": parse_bool(raw.get(COL_ONLINE_ORDER)),
        "book_table": parse_bool(raw.get(COL_BOOK_TABLE)),
        "dish_liked": split_list(raw.get(COL_DISH_LIKED), limit=DISH_LIKED_MAX),
        "review_excerpt": None,
        "url": clean_text(raw.get(COL_URL)),
    }


def _rank_key(row: dict[str, Any]) -> tuple[int, float]:
    rating = row["rating"]
    return row["votes"], rating if rating is not None else -1.0


def dedupe(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one row per id: higher votes, then higher rating, then the first seen."""
    best: dict[str, dict[str, Any]] = {}
    keys: dict[str, str] = {}
    for row in rows:
        key = f"{normalize_key(row['name'])}|{normalize_key(row['address'])}"
        current = best.get(row["id"])
        if current is None:
            best[row["id"]] = row
            keys[row["id"]] = key
            continue
        if keys[row["id"]] != key:
            raise ValueError(f"id collision for {row['id']}: {keys[row['id']]!r} vs {key!r}")
        if _rank_key(row) > _rank_key(current):
            best[row["id"]] = row
    return list(best.values())


def build_catalog(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize, drop nameless rows, dedupe, then attach review excerpts.

    Excerpts are parsed only for rows that survive dedup, because reviews_list
    values can be very large. `records` must support indexing (a list or a
    Hugging Face Dataset).
    """
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(records):
        row = normalize_row(raw)
        if row is not None:
            row["_source"] = index
            rows.append(row)

    catalog = dedupe(rows)
    for row in catalog:
        source = records[row.pop("_source")]
        row["review_excerpt"] = pick_excerpt(parse_reviews(source.get(COL_REVIEWS)))
    return catalog


def build_facets(catalog: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    localities: dict[str, str] = {}
    cuisines: set[str] = set()
    for row in catalog:
        if row["locality"]:
            localities.setdefault(row["locality"].casefold(), row["locality"])
        cuisines.update(row["cuisines"])
    return {
        "localities": sorted(localities.values(), key=str.casefold),
        "cuisines": sorted(cuisines),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _catalog_schema():
    import pyarrow as pa

    return pa.schema([
        ("id", pa.string()),
        ("name", pa.string()),
        ("address", pa.string()),
        ("locality", pa.string()),
        ("listed_city", pa.string()),
        ("cuisines", pa.list_(pa.string())),
        ("rest_type", pa.list_(pa.string())),
        ("cost_for_two", pa.int64()),
        ("rating", pa.float64()),
        ("votes", pa.int64()),
        ("online_order", pa.bool_()),
        ("book_table", pa.bool_()),
        ("dish_liked", pa.list_(pa.string())),
        ("review_excerpt", pa.string()),
        ("url", pa.string()),
    ])


def write_outputs(catalog: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path]:
    """Write both files via temp names and rename, so readers never see a partial file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    out_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = out_dir / "catalog.parquet"
    facets_path = out_dir / "facets.json"
    catalog_tmp = out_dir / "catalog.parquet.tmp"
    facets_tmp = out_dir / "facets.json.tmp"

    rows = [{field: row[field] for field in CATALOG_FIELDS} for row in catalog]
    pq.write_table(pa.Table.from_pylist(rows, schema=_catalog_schema()), catalog_tmp)
    facets_tmp.write_text(json.dumps(build_facets(catalog), ensure_ascii=False, indent=2), encoding="utf-8")

    os.replace(catalog_tmp, catalog_path)
    os.replace(facets_tmp, facets_path)
    return catalog_path, facets_path


def print_report(rows_read: int, catalog: list[dict[str, Any]]) -> None:
    facets = build_facets(catalog)
    total = len(catalog) or 1
    null_rating = sum(row["rating"] is None for row in catalog)
    null_cost = sum(row["cost_for_two"] is None for row in catalog)
    print(f"Rows read:            {rows_read}")
    print(f"Catalog rows:         {len(catalog)}")
    print(f"Null rating:          {null_rating} ({null_rating / total:.1%})")
    print(f"Null cost:            {null_cost} ({null_cost / total:.1%})")
    print(f"Localities:           {len(facets['localities'])}")
    print(f"Cuisine tags:         {len(facets['cuisines'])}")


def load_dataset_rows():
    from datasets import load_dataset

    dataset = load_dataset(DATASET_NAME, split="train")
    missing = [col for col in REQUIRED_COLUMNS if col not in dataset.column_names]
    if missing:
        raise SystemExit(f"Dataset is missing expected columns: {', '.join(missing)}")
    return dataset.select_columns(REQUIRED_COLUMNS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    records = load_dataset_rows()
    catalog = build_catalog(records)
    catalog_path, facets_path = write_outputs(catalog, args.out_dir)
    print_report(len(records), catalog)
    print(f"Wrote {catalog_path} and {facets_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
