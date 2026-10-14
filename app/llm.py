"""Thin client for an OpenAI-compatible chat completion endpoint (Groq by default)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TEMPERATURE = 0.2
DEFAULT_TIMEOUT_SECONDS = 30.0
RESPONSE_FORMATS = ("json_schema", "json_object", "off")
DEFAULT_RESPONSE_FORMAT = "json_schema"


class LLMError(Exception):
    """The provider could not be reached, refused the request, or is not configured."""


class LLMInvalidJSON(LLMError):
    """The provider rejected its own output as invalid JSON (Groq `json_validate_failed`).

    `failed_generation` holds the rejected text when the provider returns it,
    so the caller can include it in a repair prompt.
    """

    def __init__(self, message: str, failed_generation: str = ""):
        super().__init__(message)
        self.failed_generation = failed_generation


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def response_format_mode() -> str:
    mode = os.environ.get("LLM_RESPONSE_FORMAT", "").strip().lower() or DEFAULT_RESPONSE_FORMAT
    if mode not in RESPONSE_FORMATS:
        raise LLMError(f"LLM_RESPONSE_FORMAT must be one of {', '.join(RESPONSE_FORMATS)}, got {mode!r}.")
    return mode


def _response_format(mode: str, schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if mode == "json_schema" and schema is not None:
        return {
            "type": "json_schema",
            "json_schema": {"name": "recommendations", "strict": True, "schema": schema},
        }
    if mode in ("json_schema", "json_object"):
        return {"type": "json_object"}
    return None


def _error_body(response: httpx.Response) -> dict[str, Any]:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return {}
    return error if isinstance(error, dict) else {}


def complete(
    system: str,
    user: str,
    *,
    schema: dict[str, Any] | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Send one system + user message pair and return the reply text.

    Reads LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, and LLM_RESPONSE_FORMAT from the
    environment. With `schema` and the default json_schema mode, the provider is
    asked for strict schema-constrained output.

    Raises LLMInvalidJSON when the provider reports it could not produce valid
    JSON, and LLMError on missing configuration, timeouts, rate limits, and other
    HTTP errors. Error messages never include the API key.
    """
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    missing = [name for name, value in
               (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key), ("LLM_MODEL", model)) if not value]
    if missing:
        raise LLMError(f"Language model is not configured; set {', '.join(missing)}.")

    payload: dict[str, Any] = {
        "model": model,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    response_format = _response_format(response_format_mode(), schema)
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {api_key}"}
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))

    owns_client = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        response = client.post(_endpoint(base_url), json=payload, headers=headers)
    except httpx.TimeoutException:
        raise LLMError("Language model timed out.") from None
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the language model ({type(exc).__name__}).") from None
    finally:
        if owns_client:
            client.close()

    if response.status_code == 400:
        error = _error_body(response)
        if error.get("code") == "json_validate_failed":
            failed = error.get("failed_generation")
            raise LLMInvalidJSON(
                "Language model could not produce valid JSON.",
                failed_generation=failed if isinstance(failed, str) else "",
            )
    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        logger.warning("Language model rate limited (retry-after: %s)", retry_after or "not given")
        raise LLMError("Language model rate limit reached.")
    if response.status_code >= 400:
        raise LLMError(f"Language model returned HTTP {response.status_code}.")

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""
