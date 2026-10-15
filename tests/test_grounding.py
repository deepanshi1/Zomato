import json

import httpx
import pytest

from app import llm
from app.recommend import (
    PROFILE_FIELDS,
    REPLY_SCHEMA,
    SYSTEM_PROMPT,
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

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
JSON_VALIDATE_FAILED = {
    "error": {
        "message": "Failed to generate JSON. Please adjust your prompt.",
        "type": "invalid_request_error",
        "code": "json_validate_failed",
        "failed_generation": '{"summary": "x", "recommendations": [',
    }
}


@pytest.fixture
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1/")
    monkeypatch.setenv("LLM_API_KEY", "gsk-test-secret")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.delenv("LLM_RESPONSE_FORMAT", raising=False)


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def capture(seen, content="hello"):
    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    return handler


def test_complete_posts_groq_chat_completion_with_strict_schema(llm_env):
    seen = {}
    assert llm.complete("sys", "usr", schema=REPLY_SCHEMA, client=mock_client(capture(seen))) == "hello"
    assert seen["url"] == GROQ_URL
    assert seen["auth"] == "Bearer gsk-test-secret"
    body = seen["body"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["temperature"] == 0.2
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "recommendations", "strict": True, "schema": REPLY_SCHEMA},
    }


def test_json_object_mode(llm_env, monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "json_object")
    monkeypatch.setenv("LLM_MODEL", "llama-3.3-70b-versatile")
    seen = {}
    llm.complete("sys", "usr", schema=REPLY_SCHEMA, client=mock_client(capture(seen)))
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "llama-3.3-70b-versatile"


def test_off_mode_sends_no_response_format(llm_env, monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "off")
    seen = {}
    llm.complete("sys", "usr", schema=REPLY_SCHEMA, client=mock_client(capture(seen)))
    assert "response_format" not in seen["body"]


def test_unknown_response_format_is_rejected(llm_env, monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT", "yaml")
    with pytest.raises(llm.LLMError, match="LLM_RESPONSE_FORMAT"):
        llm.complete("sys", "usr", client=mock_client(capture({})))


def test_system_prompt_mentions_json_for_json_object_mode():
    assert "JSON" in SYSTEM_PROMPT


def test_system_prompt_forbids_category_inference_and_budget_misstatements():
    # Added after the Phase 6 review: the model inferred "family-friendly" from
    # "Casual Dining" and called an in-band cost "above the budget threshold".
    assert "Do not infer a trait from a broad category" in SYSTEM_PROMPT
    assert '"Casual Dining"' in SYSTEM_PROMPT
    assert "Never describe a candidate's cost as above or below the budget" in SYSTEM_PROMPT
    # The stricter evidence rule made the model return one pick out of twenty;
    # the prompt now asks for a full list with weaker fits ranked lower.
    assert 'Return exactly "max_recommendations" items' in SYSTEM_PROMPT
    assert "Do not drop them" in SYSTEM_PROMPT


def test_default_model_path_sends_the_reply_schema(pool, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr("app.llm.complete", model)
    run(pool, None)
    assert model.kwargs[0] == {"schema": REPLY_SCHEMA}


def test_reply_schema_is_strict_compatible():
    def check(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])
    check(REPLY_SCHEMA)


def test_json_validate_failed_raises_invalid_json_with_failed_text(llm_env):
    client = mock_client(lambda request: httpx.Response(400, json=JSON_VALIDATE_FAILED))
    with pytest.raises(llm.LLMInvalidJSON) as exc:
        llm.complete("sys", "usr", client=client)
    assert exc.value.failed_generation == '{"summary": "x", "recommendations": ['


def test_json_validate_failed_goes_to_repair_retry(pool):
    rejected = llm.LLMInvalidJSON("bad json", failed_generation='{"recommendations": [')
    model = FakeModel(replies=[rejected, reply(item("it-best", 1))])
    result = run(pool, model)
    assert [p.row["id"] for p in result.picks] == ["it-best"]
    assert len(model.calls) == 2
    assert '{"recommendations": [' in model.calls[1][1]


def test_json_validate_failed_twice_fails(pool):
    model = FakeModel(replies=[llm.LLMInvalidJSON("bad"), llm.LLMInvalidJSON("bad again")])
    with pytest.raises(RecommendationError):
        run(pool, model)


def test_other_400_is_a_provider_error(llm_env):
    body = {"error": {"message": "model not found", "code": "model_not_found"}}
    client = mock_client(lambda request: httpx.Response(400, json=body))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("sys", "usr", client=client)
    assert not isinstance(exc.value, llm.LLMInvalidJSON)


def test_rate_limit_logs_retry_after(llm_env, caplog):
    client = mock_client(lambda request: httpx.Response(429, headers={"retry-after": "7"}, json={}))
    with pytest.raises(llm.LLMError, match="rate limit"):
        llm.complete("sys", "usr", client=client)
    assert "retry-after: 7" in caplog.text


def test_rate_limit_is_not_retried(pool):
    model = FakeModel(replies=[llm.LLMError("Language model rate limit reached."), reply(item("it-best", 1))])
    with pytest.raises(RecommendationError):
        run(pool, model)
    assert len(model.calls) == 1


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_http_errors_raise_without_leaking_key(llm_env, status):
    client = mock_client(lambda request: httpx.Response(status, text="gsk-test-secret is bad"))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete("sys", "usr", client=client)
    assert "gsk-test-secret" not in str(exc.value)


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
