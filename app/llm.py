"""Thin client for an OpenAI-compatible chat completion endpoint."""

from __future__ import annotations

import os

import httpx

TEMPERATURE = 0.2
DEFAULT_TIMEOUT_SECONDS = 30.0


class LLMError(Exception):
    """The provider could not be reached, refused the request, or is not configured."""


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def complete(system: str, user: str, *, client: httpx.Client | None = None) -> str:
    """Send one system + user message pair and return the reply text.

    Reads LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL from the environment.
    Raises LLMError on missing configuration, timeouts, and HTTP errors.
    Error messages never include the API key.
    """
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()
    missing = [name for name, value in
               (("LLM_BASE_URL", base_url), ("LLM_API_KEY", api_key), ("LLM_MODEL", model)) if not value]
    if missing:
        raise LLMError(f"Language model is not configured; set {', '.join(missing)}.")

    payload = {
        "model": model,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
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

    if response.status_code >= 400:
        raise LLMError(f"Language model returned HTTP {response.status_code}.")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""
