import json

import pytest
from fastapi.testclient import TestClient

from app import catalog as catalog_module
from app.llm import LLMError
from app.llm import complete as REAL_COMPLETE  # captured before any fixture patches it
from app.main import MODEL_FAILURE_MESSAGE, app
from tests.conftest import FIXTURE_ROWS, FakeModel, restaurant

SAMPLE = {"locality": "Banashankari", "budget": "medium", "cuisine": "Italian", "min_rating": 4.0}


@pytest.fixture
def client(catalog, fake_model, tmp_path, monkeypatch):
    facets = {"localities": catalog.localities, "cuisines": catalog.cuisines}
    (tmp_path / "facets.json").write_text(json.dumps(facets))
    monkeypatch.setenv("CATALOG_PATH", str(tmp_path / "catalog.parquet"))
    monkeypatch.delenv("CANDIDATE_POOL", raising=False)
    monkeypatch.delenv("DEFAULT_LIMIT", raising=False)
    catalog_module.set_catalog(catalog)
    with TestClient(app) as test_client:
        yield test_client
    catalog_module.set_catalog(None)


@pytest.fixture
def no_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_PATH", str(tmp_path / "missing.parquet"))
    catalog_module.set_catalog(None)
    with TestClient(app) as test_client:
        yield test_client


def post(client, **overrides):
    return client.post("/recommendations", json={**SAMPLE, **overrides})


def field_errors(response):
    return {err["field"] for err in response.json()["errors"]}


# --- facets -----------------------------------------------------------------

def test_facets_lists_localities_and_cuisines(client):
    response = client.get("/facets")
    assert response.status_code == 200
    body = response.json()
    assert "Banashankari" in body["localities"]
    assert body["cuisines"] == sorted(body["cuisines"])
    assert "italian" in body["cuisines"]


def test_facets_missing_returns_503(no_catalog):
    response = no_catalog.get("/facets")
    assert response.status_code == 503
    assert "ingest.build_catalog" in response.json()["detail"]


# --- successful shortlist ------------------------------------------------------

def test_shortlist_numbers_match_catalog(client):
    response = post(client)
    assert response.status_code == 200
    body = response.json()
    cards = body["recommendations"]
    assert [card["id"] for card in cards] == [
        "it-best", "it-tie-more-votes", "it-tie-fewer-votes", "it-cost-401", "it-cost-800",
    ]
    by_id = {row["id"]: row for row in FIXTURE_ROWS}
    for rank, card in enumerate(cards, start=1):
        row = by_id[card["id"]]
        assert card["rank"] == rank
        assert card["name"] == row["name"]
        assert card["cuisines"] == row["cuisines"]
        assert card["rating"] == row["rating"]
        assert card["cost_for_two"] == row["cost_for_two"]
        assert card["url"] == row["url"]
        assert card["explanation"] == f"{row['name']} fits the request."
    assert body["summary"] == "5 picks."
    assert body["filter_stats"]["matched"] == 6
    assert body["filter_stats"]["rules"][0]["in"] == len(FIXTURE_ROWS)


def test_default_limit_is_5(client):
    assert len(post(client).json()["recommendations"]) == 5


def test_limit_is_respected(client):
    assert len(post(client, limit=2).json()["recommendations"]) == 2


def test_default_limit_comes_from_env(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_LIMIT", "3")
    assert len(post(client).json()["recommendations"]) == 3


def test_candidate_pool_comes_from_env(client, monkeypatch):
    monkeypatch.setenv("CANDIDATE_POOL", "2")
    body = post(client, limit=8).json()
    assert len(body["recommendations"]) == 2
    assert body["filter_stats"]["pool"] == 2
    assert body["filter_stats"]["matched"] == 6


def test_locality_and_budget_are_case_insensitive(client):
    response = post(client, locality="  banashankari ", budget="MEDIUM", cuisine="ITALIAN")
    assert response.status_code == 200
    assert response.json()["recommendations"]


def test_preferences_are_accepted(client):
    assert post(client, preferences="family-friendly, quick service").status_code == 200
    assert post(client, preferences="   ").status_code == 200


def test_unknown_extra_fields_are_ignored(client):
    assert post(client, city="Delhi").status_code == 200


# --- empty result ---------------------------------------------------------------

def test_impossible_filter_returns_200_empty_with_stats(client, fake_model):
    response = post(client, budget="high", min_rating=5.0)
    assert fake_model.calls == []
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert body["summary"] is None
    rules = body["filter_stats"]["rules"]
    assert [r["rule"] for r in rules] == ["locality", "cuisine", "budget", "min_rating"]
    assert rules[-1]["out"] == 0
    assert body["filter_stats"]["pool"] == 0


# --- validation: 400 ----------------------------------------------------------------

def test_unknown_locality_is_400(client):
    response = post(client, locality="Connaught Place")
    assert response.status_code == 400
    assert field_errors(response) == {"locality"}


def test_unknown_cuisine_is_400(client):
    response = post(client, cuisine="sushi")
    assert response.status_code == 400
    assert field_errors(response) == {"cuisine"}


def test_unknown_locality_and_cuisine_report_both(client):
    response = post(client, locality="Nowhere", cuisine="sushi")
    assert field_errors(response) == {"locality", "cuisine"}


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"budget": "mid"}, "budget"),
        ({"min_rating": -0.1}, "min_rating"),
        ({"min_rating": 5.1}, "min_rating"),
        ({"min_rating": "four"}, "min_rating"),
        ({"limit": 0}, "limit"),
        ({"limit": 9}, "limit"),
        ({"preferences": "x" * 301}, "preferences"),
        ({"locality": ""}, "locality"),
        ({"cuisine": "   "}, "cuisine"),
    ],
)
def test_out_of_range_values_are_400(client, overrides, field):
    response = post(client, **overrides)
    assert response.status_code == 400
    assert field in field_errors(response)


def test_preferences_at_cap_are_accepted(client):
    assert post(client, preferences="x" * 300).status_code == 200


def test_missing_required_field_is_400(client):
    body = {k: v for k, v in SAMPLE.items() if k != "budget"}
    response = client.post("/recommendations", json=body)
    assert response.status_code == 400
    assert "budget" in field_errors(response)


def test_invalid_json_body_is_400(client):
    response = client.post(
        "/recommendations", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


# --- model failures: 502 ----------------------------------------------------------------

@pytest.mark.parametrize(
    "model",
    [
        FakeModel(error=LLMError("Language model timed out.")),
        FakeModel(error=LLMError("Language model returned HTTP 500.")),
        FakeModel(replies=["not json", "still not json"]),
        FakeModel(replies=['{"summary": "x", "recommendations": [{"id": "ghost", "rank": 1, "explanation": "x"}]}']),
    ],
    ids=["timeout", "http-error", "invalid-json-twice", "only-unknown-ids"],
)
def test_model_failures_return_502_without_a_list(client, monkeypatch, model):
    monkeypatch.setattr("app.llm.complete", model)
    response = post(client)
    assert response.status_code == 502
    body = response.json()
    assert body["detail"] == MODEL_FAILURE_MESSAGE
    assert "recommendations" not in body


def test_unconfigured_model_returns_502_but_empty_pool_still_works(client, monkeypatch):
    monkeypatch.setattr("app.llm.complete", REAL_COMPLETE)
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert post(client).status_code == 502
    assert post(client, budget="high", min_rating=5.0).status_code == 200


# --- missing catalog: 503 ---------------------------------------------------------------

def test_missing_catalog_returns_503(no_catalog):
    response = no_catalog.post("/recommendations", json=SAMPLE)
    assert response.status_code == 503
    assert "ingest.build_catalog" in response.json()["detail"]


# --- configuration ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, value",
    [("CANDIDATE_POOL", "0"), ("CANDIDATE_POOL", "many"), ("DEFAULT_LIMIT", "9"), ("DEFAULT_LIMIT", "0")],
)
def test_bad_config_fails_at_startup(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        with TestClient(app):
            pass


def test_null_cost_restaurants_never_appear(catalog, client):
    catalog.rows.append(restaurant("null-cost-2", "No Price", cost=None, rating=5.0))
    ids = [card["id"] for card in post(client, limit=8).json()["recommendations"]]
    assert "null-cost-2" not in ids and "it-null-cost" not in ids
