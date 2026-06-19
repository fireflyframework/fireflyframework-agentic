"""Async LLM scoring client for judge metrics.

Thin httpx-based wrapper over Anthropic / OpenAI / Azure OpenAI / Ollama.
Reads API keys lazily (per-call) from env so importing never requires secrets.
Provider/model spec: "<provider>:<model>", e.g. "anthropic:claude-sonnet-4-6".
"""

from __future__ import annotations

import asyncio
import json
import os
import re

import httpx

_RETRY_STATUS = (429, 500, 502, 503, 504)
_MAX_RETRY_AFTER = 30.0


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def parse_model(spec: str) -> tuple[str, str]:
    """Split "provider:model" -> (provider, model). Bare spec -> ("unknown", spec)."""
    spec = (spec or "").strip()
    if ":" not in spec:
        return "unknown", spec
    provider, model = spec.split(":", 1)
    return provider.strip().lower(), model.strip()


def same_provider(pipeline_model: str, judge_model: str) -> bool:
    """True iff both specs share the same known provider prefix."""
    p, _ = parse_model(pipeline_model)
    j, _ = parse_model(judge_model)
    if p == "unknown" or j == "unknown":
        return False
    return p == j


def _first_json_object(text: str) -> dict:
    """Extract the first balanced JSON object from text (handles prose/code-fence wrapping)."""
    if not text:
        raise ValueError("empty model response")

    # Fast path: a clean JSON object with no surrounding prose.  A non-dict
    # clean parse (e.g. a top-level array) is intentionally ignored so the brace
    # scanner can still find an embedded object rather than returning arr[0].
    try:
        parsed = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # try the next '{'
        start = text.find("{", start + 1)

    # Greedy fallback: first '{' .. last '}' across newlines.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("no JSON object found in model response")


class JudgeClient:
    """Async multi-provider chat client returning parsed JSON dicts.

    Dispatch is by the provider prefix of the model spec.  temperature is pinned
    to 0.0 for deterministic verdicts.  Transient HTTP errors (429/5xx) and network
    errors are retried up to max_retries with backoff.

    The API key / endpoint env vars are read lazily inside chat_json, so
    constructing a JudgeClient never requires a secret.
    """

    def __init__(self, model: str, timeout: int = 120, max_retries: int = 3) -> None:
        self.model_spec = model
        self.provider, self.model = parse_model(model)
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Send (system, user) to the provider and parse the first JSON object.

        Raises on exhausted retries / unknown provider / unparseable output.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                if self.provider == "anthropic":
                    return await self._anthropic(system, user, max_tokens)
                if self.provider == "openai":
                    return await self._openai(system, user, max_tokens)
                if self.provider == "azure":
                    return await self._azure(system, user, max_tokens)
                if self.provider == "ollama":
                    return await self._ollama(system, user, max_tokens)
                raise ValueError(
                    f"unknown judge provider {self.provider!r} in {self.model_spec!r}; "
                    "use anthropic:/openai:/azure:/ollama:"
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in _RETRY_STATUS or attempt == self.max_retries - 1:
                    raise
                retry_after_header = exc.response.headers.get("retry-after")
                if retry_after_header is not None:
                    try:
                        delay = min(float(retry_after_header), _MAX_RETRY_AFTER)
                    except (TypeError, ValueError):
                        delay = 2.0**attempt
                else:
                    delay = 2.0**attempt
                await asyncio.sleep(delay)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == self.max_retries - 1:
                    raise
                await asyncio.sleep(2.0)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("chat_json exhausted retries without a response")

    async def _anthropic(self, system: str, user: str, max_tokens: int) -> dict:
        api_key = _env("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = next((b.get("text") for b in data.get("content", []) if b.get("type") == "text"), None)
        if not text:
            raise RuntimeError(f"judge returned no text: {data}")
        return _first_json_object(text)

    async def _openai(self, system: str, user: str, max_tokens: int) -> dict:
        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post("https://api.openai.com/v1/chat/completions", json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content")
            if text:
                return _first_json_object(text)
        raise RuntimeError(f"judge returned no text: {data}")

    async def _azure(self, system: str, user: str, max_tokens: int) -> dict:
        endpoint = _env("AZURE_OPENAI_ENDPOINT")
        api_key = _env("AZURE_OPENAI_API_KEY")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT not set")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY not set")
        api_version = _env("AZURE_OPENAI_API_VERSION") or "2024-02-01"
        url = f"{endpoint.rstrip('/')}/openai/deployments/{self.model}/chat/completions?api-version={api_version}"
        body = {
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"api-key": api_key, "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content")
            if text:
                return _first_json_object(text)
        raise RuntimeError(f"judge returned no text: {data}")

    async def _ollama(self, system: str, user: str, max_tokens: int) -> dict:  # noqa: ARG002
        host = _env("OLLAMA_HOST") or "http://localhost:11434"
        body = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{host.rstrip('/')}/api/chat", json=body)
            resp.raise_for_status()
            data = resp.json()
        text = (data.get("message") or {}).get("content")
        if not text:
            raise RuntimeError(f"judge returned no text: {data}")
        return _first_json_object(text)
