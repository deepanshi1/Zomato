import json

import httpx
import pytest

from app import llm
from app.recommend import (
    PROFILE_FIELDS,
    RecommendationError,
    parse_model_json,
    rank_with_model,
)
from tests.conftest import FakeModel

QUERY = {"locality": "Banashankari", "cuisine": "Italian", "budget": "medium", "min_rating": 4.0}


@pytest.fixture
def pool(rows):
    by_id = {row["id"]: row for row in rows}
    return [by_id[i] for i in ("it-best", "it-tie-more-votes", "it-tie-fewer-votes", "it-exact-min")]


def run(pool, model, limit=5, preferences="family-friendly, quick service"):
    return rank_with_model(**QUERY, preferences=preferences, limit=limit, candidates=pool, complete=model)


def reply(*items, summary="A short comparison."):
    return json.dumps({"summary": summary, "recommendations": list(items)})


def item(id, rank, explanation="Fits the request.", **extra):
    return {"id": id, "rank": rank, "explanation": explanation, **extra}


# --- plan cases -------------------------------------------------------------------

def test_fenced_json_keeps_known_id_and_uses_catalog_facts(pool):
    fenced = "```json\n" + reply(
        item("it-tie-more-votes", 1, rating=5.0, cost_for_two=99, name="Fake Name"),
        item("ghost-id", 2),
    ) + "\n```"
    result = run(pool, FakeModel(replies=[fenced]))
    assert [pick.row["id"] for pick in result.picks] == ["it-tie-more-votes"]
    row = result.picks[0].row
    assert row["rating"] == 4.3
    assert row["cost_for_two"] == 600
    assert row["name"] == "Pasta Street"
    assert result.summary == "A short comparison."


def test_only_unknown_ids_is_a_grounding_failure(pool):
    model = FakeModel(replies=[reply(item("ghost-1", 1), item("ghost-2", 2))])
    with pytest.raises(RecommendationError):
        run(pool, model)


def test_invalid_json_then_valid_succeeds_via_repair(pool):
    model = FakeModel(replies=["Sure! Here are my picks: Onesta first.", reply(item("it-best", 1))])
    result = run(pool, model)
    assert [pick.row["id"] for pick in result.picks] == ["it-best"]
    assert len(model.calls) == 2
    repair_user = model.calls[1][1]
    assert "Sure! Here are my picks: Onesta first." in repair_user


def test_invalid_json_twice_fails(pool):
    model = FakeModel(replies=["not json", "{still: not json"])
    with pytest.raises(RecommendationError):
        run(pool, model)
    assert len(model.calls) == 2


# --- model call behavior ------------------------------------------------------------

def test_empty_pool_does_not_call_the_model():
    model = FakeModel()
    result = run([], model)
    assert result.picks == [] and result.summary is None
    assert model.calls == []


def test_provider_error_becomes_recommendation_error(pool):
    with pytest.raises(RecommendationError):
        run(pool, FakeModel(error=llm.LLMError("Language model timed out.")))


def test_valid_first_reply_makes_one_call(pool):
    model = FakeModel()
    run(pool, model)
    assert len(model.calls) == 1


# --- prompt ------------------------------------------------------------------------

def test_user_message_carries_profiles_without_url(pool):
    model = FakeModel()
    run(pool, model, limit=3)
    system, user = model.calls[0]
    message = json.loads(user)
    assert message["max_recommendations"] == 3
    assert message["preferences"] == "family-friendly, quick service"
    assert message["request"]["budget"] == "medium (₹401–₹800 for two)"
    assert [c["id"] for c in message["candidates"]] == [row["id"] for row in pool]
    for profile in message["candidates"]:
        assert list(profile) == PROFILE_FIELDS
        assert "url" not in profile
    assert "JSON only" in system
    assert "Rank only the restaurants" in system


def test_missing_preferences_are_stated(pool):
    model = FakeModel()
    run(pool, model, preferences=None)
    assert json.loads(model.calls[0][1])["preferences"] == "none given"


# --- grounding edge cases -------------------------------------------------------------

def test_sorted_by_rank_and_renumbered(pool):
    model = FakeModel(replies=[reply(item("it-exact-min", 7), item("it-best", 3), item("it-tie-more-votes", 5))])
    result = run(pool, model)
    assert [(p.rank, p.row["id"]) for p in result.picks] == [
        (1, "it-best"), (2, "it-tie-more-votes"), (3, "it-exact-min"),
    ]


def test_duplicate_ids_keep_first(pool):
    model = FakeModel(replies=[reply(item("it-best", 1, "First."), item("it-best", 2, "Second."))])
    result = run(pool, model)
    assert len(result.picks) == 1
    assert result.picks[0].explanation == "First."


def test_missing_or_bad_ranks_fall_back_to_position(pool):
    model = FakeModel(replies=[reply(
        {"id": "it-tie-more-votes", "explanation": "No rank."},
        item("it-best", "2"),
        item("it-exact-min", "first"),
    )])
    result = run(pool, model)
    # positions 1, 2 (string "2"), 3 → stable order
    assert [p.row["id"] for p in result.picks] == ["it-tie-more-votes", "it-best", "it-exact-min"]


def test_more_items_than_limit_are_cut(pool):
    model = FakeModel(replies=[reply(*[item(row["id"], i) for i, row in enumerate(pool, start=1)])])
    assert len(run(pool, model, limit=2).picks) == 2


def test_items_without_explanation_are_dropped(pool):
    model = FakeModel(replies=[reply(item("it-best", 1, ""), item("it-exact-min", 2))])
    assert [p.row["id"] for p in run(pool, model).picks] == ["it-exact-min"]


def test_ids_are_trimmed(pool):
    model = FakeModel(replies=[reply(item("  it-best ", 1))])
    assert run(pool, model).picks[0].row["id"] == "it-best"


def test_catalog_id_outside_the_pool_is_dropped(pool, rows):
    outside = "jn-it"  # real catalog row, but not in this request's pool
    model = FakeModel(replies=[reply(item(outside, 1), item("it-best", 2))])
    assert [p.row["id"] for p in run(pool, model).picks] == ["it-best"]


@pytest.mark.parametrize("summary", [None, "", "   ", 42, ["a"]])
def test_unusable_summary_becomes_none(pool, summary):
    model = FakeModel(replies=[json.dumps({"summary": summary, "recommendations": [item("it-best", 1)]})])
    assert run(pool, model).summary is None


def test_long_explanation_is_clipped(pool):
    model = FakeModel(replies=[reply(item("it-best", 1, "word " * 400))])
    assert len(run(pool, model).picks[0].explanation) <= 600


def test_wrong_shape_triggers_repair(pool):
    model = FakeModel(replies=['{"picks": []}', reply(item("it-best", 1))])
    assert run(pool, model).picks[0].row["id"] == "it-best"
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    "text",
    [
        "```json\n{\"recommendations\": []}\n```",
        "```\n{\"recommendations\": []}\n```",
        "Here you go:\n```json\n{\"recommendations\": []}\n```\nEnjoy!",
    ],
)
def test_one_fence_is_stripped(text):
    assert parse_model_json(text) == {"recommendations": []}


def test_two_fences_are_not_guessed():
    text = "```json\n{\"recommendations\": []}\n```\n```json\n{\"recommendations\": []}\n```"
    with pytest.raises(ValueError):
        parse_model_json(text)


# --- HTTP client ------------------------------------------------------------------------

@pytest.fixture
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1/")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_complete_posts_chat_completion(llm_env):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    assert llm.complete("sys", "usr", client=mock_client(handler)) == "hello"
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-secret"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["temperature"] == 0.2
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_errors_raise_without_leaking_key(llm_env, status):
    client = mock_client(lambda request: httpx.Response(status, text="sk-test-secret is bad"))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("sys", "usr", client=client)
    assert str(status) in str(exc.value)
    assert "sk-test-secret" not in str(exc.value)


def test_timeout_raises(llm_env):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(llm.LLMError, match="timed out"):
        llm.complete("sys", "usr", client=mock_client(handler))


def test_missing_config_raises(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(llm.LLMError, match="LLM_API_KEY"):
        llm.complete("sys", "usr")


def test_malformed_provider_body_returns_empty_text(llm_env):
    client = mock_client(lambda request: httpx.Response(200, json={"choices": []}))
    assert llm.complete("sys", "usr", client=client) == ""
