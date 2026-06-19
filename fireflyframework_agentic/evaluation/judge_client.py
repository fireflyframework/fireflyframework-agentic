# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provider-agnostic LLM-as-a-Judge client for the G4 advisory gate.

Zero new dependencies: stdlib (urllib.request, json, os, time, re) + numpy.
The client is a thin POST wrapper over four chat providers (Anthropic, OpenAI,
Azure OpenAI, Ollama) plus an Ollama embedder.  It is deliberately tolerant:
chat_json extracts the FIRST JSON object from the model text (models wrap JSON
in prose / code fences), and retries transient HTTP errors with backoff.

This module is import-safe: importing it touches NO network and reads NO API
key.  Keys are read lazily, per-call, only when a real request is made — so the
judge tests can import and inject stubs without any secret present.

Provider/model spec format: "<provider>:<model>", e.g. "anthropic:claude-sonnet-4-6",
"openai:gpt-4o", "azure:gpt-4o", "ollama:llama3".  A bare model with no prefix is
treated as provider "unknown" (see parse_model / same_provider).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

import numpy as np

# Transient HTTP status codes worth retrying (rate limit + 5xx).
_RETRY_STATUS = (429, 500, 502, 503, 504)

# Hard cap on a honoured Retry-After sleep (a hostile header should not stall us).
_MAX_RETRY_AFTER = 30.0


def _env(name, default=None):
    """Read an env var, stripping surrounding whitespace; empty-after-strip -> default.

    Defensive against a ``.env`` value that arrives with a trailing ``\\r`` /
    whitespace (CRLF), which would otherwise corrupt a request URL or header.
    An unset OR blank value falls back to ``default`` so the existing
    missing-key -> RuntimeError behaviour is preserved.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to sleep before retrying an HTTPError.

    On 429 honour the ``Retry-After`` header (capped at 30s) when it is present
    and numeric; otherwise fall back to exponential backoff (2 ** attempt).
    """
    if exc.code == 429:
        headers = getattr(exc, "headers", None)
        retry_after = headers.get("retry-after") if headers is not None else None
        if retry_after is not None:
            try:
                return min(float(retry_after), _MAX_RETRY_AFTER)
            except (TypeError, ValueError):
                pass
    return 2.0**attempt


def parse_model(spec: str) -> tuple[str, str]:
    """Split a "provider:model" spec into (provider, model).

    A bare spec with no ':' is returned as provider "unknown" with the whole
    string as the model, e.g. "claude-sonnet-4-6" -> ("unknown", "claude-sonnet-4-6").
    The provider is lower-cased; the model keeps its original case.
    """
    spec = (spec or "").strip()
    if ":" not in spec:
        return "unknown", spec
    provider, model = spec.split(":", 1)
    return provider.strip().lower(), model.strip()


def same_provider(pipeline_model: str, judge_model: str) -> bool:
    """True iff both specs name the SAME known provider prefix.

    A missing or "unknown" provider on either side -> not-same (False).  This is
    the same-provider caveat signal: when the judge and the pipeline share a
    provider the judged metrics are advisory (no cross-provider isolation).
    """
    p_provider, _ = parse_model(pipeline_model)
    j_provider, _ = parse_model(judge_model)
    if p_provider == "unknown" or j_provider == "unknown":
        return False
    return p_provider == j_provider


def _first_json_object(text: str) -> dict:
    """Extract and parse the FIRST balanced JSON object embedded in text.

    Models wrap JSON in prose, preambles, or ```json code fences.  This scans
    for the first '{' and walks the string tracking brace depth (string-aware,
    so braces inside quoted values do not confuse the matcher) to find its
    matching '}'.  Falls back to a greedy regex span if no balanced object is
    found.  Raises ValueError when nothing parses.
    """
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


def _http_post_json(url: str, headers: dict, body: dict, timeout: int) -> dict:
    """POST a JSON body and return the parsed JSON response (single attempt)."""
    data = json.dumps(body).encode("utf-8")
    req_headers = {"content-type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_openai_text(resp: dict) -> str:
    """Pull the assistant text from an OpenAI/Azure chat-completions response.

    Guards an empty ``choices`` list and a null ``message.content`` and raises a
    descriptive RuntimeError (not a KeyError) when no text is present, so the
    judge layer records a clean dropped-vote reason instead of a stack trace.
    """
    choices = resp.get("choices") or []
    if choices:
        text = (choices[0].get("message") or {}).get("content")
        if text:
            return text
    raise RuntimeError(f"judge returned no text: {resp}")


class JudgeClient:
    """Minimal multi-provider chat client returning parsed JSON dicts.

    Dispatch is by the provider prefix of the model spec.  temperature is pinned
    to 0.0 for deterministic verdicts.  Transient HTTP errors (429/5xx) and URL
    errors are retried up to max_retries: a 429 honours the ``Retry-After``
    header (capped at 30s) when present, otherwise backoff is exponential
    (2 ** attempt seconds).

    The API key / endpoint env vars are read lazily inside chat_json, so
    constructing a JudgeClient never requires a secret.
    """

    def __init__(self, model: str, timeout: int = 120, max_retries: int = 3) -> None:
        self.model_spec = model
        self.provider, self.model = parse_model(model)
        self.timeout = timeout
        self.max_retries = max_retries

    def chat_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Send (system, user) to the provider and parse the first JSON object.

        Raises on exhausted retries / unknown provider / unparseable output.
        The judge module wraps every call in try/except, so a raise here becomes
        a dropped vote rather than a crash.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                text = self._dispatch(system, user, max_tokens)
                return _first_json_object(text)
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code not in _RETRY_STATUS or attempt == self.max_retries - 1:
                    raise
                time.sleep(_retry_delay(exc, attempt))
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_exc = exc
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2**attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("chat_json exhausted retries without a response")

    def _dispatch(self, system: str, user: str, max_tokens: int) -> str:
        """Route to the per-provider call and return the raw model text."""
        if self.provider == "anthropic":
            return self._anthropic(system, user, max_tokens)
        if self.provider == "openai":
            return self._openai(system, user, max_tokens)
        if self.provider == "azure":
            return self._azure(system, user, max_tokens)
        if self.provider == "ollama":
            return self._ollama(system, user, max_tokens)
        raise ValueError(
            f"unknown judge provider {self.provider!r} in {self.model_spec!r}; use anthropic:/openai:/azure:/ollama:"
        )

    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
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
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        resp = _http_post_json("https://api.anthropic.com/v1/messages", headers, body, self.timeout)
        text = next((b.get("text") for b in resp.get("content", []) if b.get("type") == "text"), None)
        if not text:
            raise RuntimeError(f"judge returned no text: {resp}")
        return text

    def _openai(self, system: str, user: str, max_tokens: int) -> str:
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
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = _http_post_json("https://api.openai.com/v1/chat/completions", headers, body, self.timeout)
        return _extract_openai_text(resp)

    def _azure(self, system: str, user: str, max_tokens: int) -> str:
        endpoint = _env("AZURE_OPENAI_ENDPOINT")
        api_key = _env("AZURE_OPENAI_API_KEY")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT not set")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY not set")
        api_version = _env("AZURE_OPENAI_API_VERSION") or "2024-06-01"
        # Azure deployment lives in the URL path, not the JSON body.
        url = f"{endpoint.rstrip('/')}/openai/deployments/{self.model}/chat/completions?api-version={api_version}"
        body = {
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"api-key": api_key}
        resp = _http_post_json(url, headers, body, self.timeout)
        return _extract_openai_text(resp)

    def _ollama(self, system: str, user: str, max_tokens: int) -> str:
        host = _env("OLLAMA_HOST") or "http://localhost:11434"
        body = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": max_tokens},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        resp = _http_post_json(f"{host.rstrip('/')}/api/chat", {}, body, self.timeout)
        text = (resp.get("message") or {}).get("content")
        if not text:
            raise RuntimeError(f"judge returned no text: {resp}")
        return text


class OpenAIEmbedder:
    """OpenAI embeddings client over /v1/embeddings.

    Reads OPENAI_API_KEY from the environment.  Default model: text-embedding-3-small.
    """

    def __init__(self, model: str = "text-embedding-3-small", timeout: int = 60) -> None:
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> np.ndarray:
        api_key = _env("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        headers = {"Authorization": f"Bearer {api_key}"}
        body = {"model": self.model, "input": texts}
        resp = _http_post_json("https://api.openai.com/v1/embeddings", headers, body, self.timeout)
        data = resp.get("data", [])
        vectors = [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
        return np.asarray(vectors, dtype=np.float32)


class AzureOpenAIEmbedder:
    """Azure OpenAI embeddings client.

    Reads AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and optionally
    AZURE_OPENAI_API_VERSION from the environment.  The model name is the
    deployment name.  Default model: text-embedding-3-small.
    """

    def __init__(self, model: str = "text-embedding-3-small", timeout: int = 60) -> None:
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> np.ndarray:
        endpoint = _env("AZURE_OPENAI_ENDPOINT")
        api_key = _env("AZURE_OPENAI_API_KEY")
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT not set")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY not set")
        api_version = _env("AZURE_OPENAI_API_VERSION") or "2024-06-01"
        url = f"{endpoint.rstrip('/')}/openai/deployments/{self.model}/embeddings?api-version={api_version}"
        headers = {"api-key": api_key}
        vectors = self._embed_with_split(texts, url, headers)
        return np.asarray(vectors, dtype=np.float32)

    def _embed_with_split(self, texts: list[str], url: str, headers: dict) -> list[list[float]]:
        """Send texts in one request; on HTTP 400 split in half and retry each half."""
        try:
            resp = _http_post_json(url, headers, {"input": texts}, self.timeout)
            data = resp.get("data", [])
            return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
        except urllib.error.HTTPError as exc:
            if exc.code == 400 and len(texts) > 1:
                mid = len(texts) // 2
                left = self._embed_with_split(texts[:mid], url, headers)
                right = self._embed_with_split(texts[mid:], url, headers)
                return left + right
            raise


class OllamaEmbedder:
    """Local Ollama embedding client (default model bge-m3) over /api/embeddings.

    Posts one prompt per call (the stable single-prompt form) and stacks the
    returned vectors into a 2-D numpy array.  Constructing it touches no network;
    the host is resolved from $OLLAMA_HOST at call time.
    """

    def __init__(self, model: str = "bge-m3", host: str | None = None, timeout: int = 60) -> None:
        self.model = model
        self.host = (host or _env("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a list of strings -> float32 ndarray of shape (len(texts), dim)."""
        vectors: list[list[float]] = []
        for text in texts:
            body = {"model": self.model, "prompt": text}
            resp = _http_post_json(f"{self.host}/api/embeddings", {}, body, self.timeout)
            vectors.append(resp["embedding"])
        return np.asarray(vectors, dtype=np.float32)


def build_embedder(spec: str):
    """Return an ``embed_fn(list[str]) -> np.ndarray`` for an embedder spec.

    Dispatch is on the provider prefix of a "<provider>:<model>" spec:
    - "ollama" / "ollama:<model>" -> OllamaEmbedder(model or "bge-m3").embed.
    - a bare "<model>" with no ':' -> treated as an Ollama model.
    - any other provider -> NotImplementedError (the extension point).

    Add a new backend by adding a branch here.
    """
    if (spec or "").strip() == "ollama":  # bare provider, no model -> default model
        return OllamaEmbedder("bge-m3").embed
    provider, model = parse_model(spec)
    if provider in ("unknown", "ollama"):  # bare "<model>" or "ollama:<model>"
        return OllamaEmbedder(model or "bge-m3").embed
    if provider == "openai":
        return OpenAIEmbedder(model or "text-embedding-3-small").embed
    if provider == "azure":
        return AzureOpenAIEmbedder(model or "text-embedding-3-small").embed
    raise NotImplementedError(f"embedder backend {provider!r} not implemented yet; add it in build_embedder()")


def cosine(a, b) -> float:
    """Cosine similarity between two 1-D vectors; 0.0 if either is the zero vector."""
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))
