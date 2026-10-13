import copy

import pytest

from app.catalog import (
    BUDGET_BANDS,
    Catalog,
    CatalogNotFoundError,
    filter_candidates,
    in_budget,
)
from tests.conftest import restaurant


def ids(result):
    return [row["id"] for row in result.candidates]


def run(rows, **overrides):
    query = {"locality": "Banashankari", "cuisine": "italian", "budget": "medium", "min_rating": 0.0}
    query.update(overrides)
    return filter_candidates(rows, **query)


# --- locality ---------------------------------------------------------------

def test_locality_match_is_case_insensitive(rows):
    result = run(rows, locality="  banaSHANKARI ")
    assert "it-best" in ids(result)
    assert "jn-it" not in ids(result)


def test_locality_mismatch_removes_everything(rows):
    result = run(rows, locality="Indiranagar")
    assert result.candidates == []
    assert result.stats()["rules"][0] == {"rule": "locality", "in": len(rows), "removed": len(rows), "out": 0}


def test_locality_is_not_a_substring_match(rows):
    assert run(rows, locality="Bana").candidates == []


# --- cuisine ----------------------------------------------------------------

def test_cuisine_substring_matches_any_tag(rows):
    result = run(rows, cuisine="Indian", budget="low")
    assert ids(result) == ["si"]
    result = run(rows, cuisine="indian", budget="medium")
    assert ids(result) == ["ni"]


def test_cuisine_matches_tag_other_than_first(rows):
    assert "it-best" in ids(run(rows, cuisine="Italian"))
    assert ids(run(rows, cuisine="chinese")) == ["ni"]


# --- budget -----------------------------------------------------------------

def test_budget_band_values_are_pinned():
    assert BUDGET_BANDS == {"low": (None, 400), "medium": (401, 800), "high": (801, None)}


@pytest.mark.parametrize(
    "cost, band",
    [(1, "low"), (400, "low"), (401, "medium"), (800, "medium"), (801, "high"), (6000, "high")],
)
def test_each_cost_lands_in_one_band(cost, band):
    assert [name for name in BUDGET_BANDS if in_budget(cost, name)] == [band]


def test_low_band(rows):
    assert ids(run(rows, budget="low")) == ["it-cost-400"]


def test_medium_band_includes_401_and_800(rows):
    result = ids(run(rows, budget="medium"))
    assert "it-cost-401" in result and "it-cost-800" in result
    assert "it-cost-400" not in result and "it-cost-801" not in result


def test_high_band(rows):
    assert ids(run(rows, budget="high")) == ["it-cost-801"]


def test_null_cost_fails_every_budget(rows):
    for band in BUDGET_BANDS:
        assert "it-null-cost" not in ids(run(rows, budget=band))


def test_unknown_budget_is_rejected(rows):
    with pytest.raises(ValueError):
        run(rows, budget="mid")


# --- rating -----------------------------------------------------------------

def test_min_rating_is_inclusive(rows):
    result = ids(run(rows, min_rating=4.0))
    assert "it-exact-min" in result
    assert "it-below-min" not in result


def test_null_rating_fails_even_at_zero(rows):
    assert "it-null-rating" not in ids(run(rows, min_rating=0.0))


def test_float_noise_does_not_drop_a_row():
    rows = [restaurant("a", "A", rating=3.9999999999)]
    assert ids(run(rows, min_rating=4.0)) == ["a"]


def test_min_rating_five_keeps_only_perfect_scores(rows):
    assert run(rows, min_rating=5.0).candidates == []


# --- sort and cap ------------------------------------------------------------

def test_sorted_by_rating_then_votes(rows):
    result = ids(run(rows, min_rating=4.0))
    assert result == [
        "it-best",             # 4.6
        "it-tie-more-votes",   # 4.3, 900 votes
        "it-tie-fewer-votes",  # 4.3, 150 votes
        "it-cost-401",         # 4.1 ties broken by id
        "it-cost-800",
        "it-exact-min",        # 4.0
    ]


def test_full_tie_is_ordered_by_id():
    rows = [restaurant("b", "B"), restaurant("a", "A"), restaurant("c", "C")]
    assert ids(run(rows)) == ["a", "b", "c"]


def test_pool_is_capped():
    rows = [restaurant(f"r{i:02d}", f"R{i}", rating=4.0 + i / 100, votes=i) for i in range(30)]
    result = run(rows, pool_size=20)
    assert len(result.candidates) == 20
    assert result.matched == 30
    assert result.candidates[0]["id"] == "r29"


def test_default_pool_is_20():
    rows = [restaurant(f"r{i:02d}", f"R{i}") for i in range(25)]
    assert len(run(rows).candidates) == 20


# --- stats -------------------------------------------------------------------

def test_stats_count_each_rule(rows):
    stats = run(rows, min_rating=4.0).stats()
    assert [r["rule"] for r in stats["rules"]] == ["locality", "cuisine", "budget", "min_rating"]
    for before, after in zip(stats["rules"], stats["rules"][1:]):
        assert before["out"] == after["in"]
    assert stats["rules"][0]["in"] == len(rows)
    assert stats["rules"][0]["removed"] == 1        # Jayanagar
    assert stats["rules"][1]["removed"] == 2        # north and south indian
    assert stats["rules"][2]["removed"] == 3        # 400, 801, null cost
    assert stats["rules"][3]["removed"] == 2        # 3.9 and null rating
    assert stats["matched"] == stats["pool"] == 6


def test_stats_show_which_rule_emptied_the_result(rows):
    stats = run(rows, budget="high", min_rating=4.5).stats()
    assert stats["pool"] == 0
    assert stats["rules"][3] == {"rule": "min_rating", "in": 1, "removed": 1, "out": 0}


def test_filter_does_not_modify_rows(rows):
    before = copy.deepcopy(rows)
    run(rows, min_rating=4.0)
    assert rows == before


# --- exit check: medium Italian in Banashankari at 4.0 ----------------------------

def test_sample_query_returns_only_matching_rows_best_first(rows):
    result = run(rows, locality="Banashankari", cuisine="Italian", budget="medium", min_rating=4.0)
    assert result.candidates
    for row in result.candidates:
        assert row["locality"] == "Banashankari"
        assert any("italian" in tag for tag in row["cuisines"])
        assert 401 <= row["cost_for_two"] <= 800
        assert row["rating"] >= 4.0
    ratings = [row["rating"] for row in result.candidates]
    assert ratings == sorted(ratings, reverse=True)


# --- catalog lookups ---------------------------------------------------------------

def test_catalog_lookups(catalog):
    assert catalog.canonical_locality("jayanagar") == "Jayanagar"
    assert catalog.canonical_locality("Nowhere") is None
    assert catalog.localities == ["Banashankari", "Jayanagar"]
    assert catalog.has_cuisine("Indian")
    assert not catalog.has_cuisine("sushi")
    assert not catalog.has_cuisine("  ")
    assert catalog.by_id["it-best"]["name"] == "Onesta"


def test_missing_catalog_file_raises(tmp_path):
    with pytest.raises(CatalogNotFoundError, match="ingest.build_catalog"):
        Catalog.from_parquet(tmp_path / "missing.parquet")
