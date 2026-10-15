"""Bounded local-only Ollama chat and embedding adapters."""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from aie.model_policy import ollama_base_url

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_ALLOWED_ROLES = {"system", "user", "assistant"}


class OllamaError(RuntimeError):
    """A local Ollama request failed or returned an invalid response."""


class OllamaCancelled(OllamaError):
    """The caller cancelled a local inference request."""


@dataclass(frozen=True)
class ChatResult:
    model: str
    content: str
    done: bool
    total_duration_ns: int | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    embeddings: list[list[float]]
    dimensions: int


class OllamaClient:
    """Small synchronous adapter; no tool execution, model pulls or cloud fallback."""

    def __init__(self, *, base_url: str | None = None, timeout: float = 60.0,
                 opener=None) -> None:
        if isinstance(timeout, bool) or not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise ValueError("timeout must be finite and between 0 and 600 seconds")
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Ollama adapter requires a loopback URL without credentials")
        self.timeout = timeout
        self._opener = opener or urlopen

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        format: str | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ChatResult:
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if not messages:
            raise ValueError("at least one message is required")
        normalized: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("messages must be dictionaries")
            role, content = message.get("role"), message.get("content")
            if role not in _ALLOWED_ROLES or not isinstance(content, str):
                raise ValueError("messages require system/user/assistant role and string content")
            normalized.append({"role": role, "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": normalized,
            "stream": False,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        result = self._post("/api/chat", payload, cancel_event=cancel_event)
        message = result.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaError("Ollama chat response did not contain message.content")
        return ChatResult(
            model=str(result.get("model") or model),
            content=message["content"],
            done=bool(result.get("done", False)),
            total_duration_ns=_optional_int(result.get("total_duration")),
            prompt_tokens=_optional_int(result.get("prompt_eval_count")),
            output_tokens=_optional_int(result.get("eval_count")),
        )

    def embed(
        self,
        model: str,
        inputs: str | list[str],
        *,
        expected_dimensions: int | None = None,
        cancel_event: threading.Event | None = None,
    ) -> EmbeddingResult:
        if not model or not model.strip():
            raise ValueError("model must be non-empty")
        if isinstance(inputs, str):
            texts = [inputs]
        elif isinstance(inputs, list):
            texts = inputs
        else:
            raise ValueError("embedding input must be a string or list of strings")
        if not texts or any(not isinstance(item, str) or not item for item in texts):
            raise ValueError("embedding input must contain non-empty strings")
        if isinstance(expected_dimensions, bool):
            raise ValueError("expected_dimensions must be a positive integer")
        if expected_dimensions is not None and expected_dimensions < 1:
            raise ValueError("expected_dimensions must be positive")
        result = self._post(
            "/api/embed",
            {"model": model, "input": texts},
            cancel_event=cancel_event,
        )
        vectors = result.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise OllamaError("Ollama embedding response count did not match input count")
        parsed: list[list[float]] = []
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise OllamaError("Ollama returned an empty or invalid embedding")
            values: list[float] = []
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise OllamaError("Ollama embedding contained a non-numeric value")
                number = float(value)
                if not math.isfinite(number):
                    raise OllamaError("Ollama embedding contained a non-finite value")
                values.append(number)
            parsed.append(values)
        dimensions = len(parsed[0])
        if any(len(vector) != dimensions for vector in parsed):
            raise OllamaError("Ollama returned inconsistent embedding dimensions")
        if expected_dimensions is not None and dimensions != expected_dimensions:
            raise OllamaError(
                f"embedding dimension mismatch: expected {expected_dimensions}, got {dimensions}"
            )
        return EmbeddingResult(
            model=str(result.get("model") or model),
            embeddings=parsed,
            dimensions=dimensions,
        )

    def _post(
        self, path: str, payload: dict[str, Any], *,
        cancel_event: threading.Event | None,
    ) -> dict[str, Any]:
        if cancel_event is not None and cancel_event.is_set():
            raise OllamaCancelled("inference cancelled before request")
        request = Request(
            self.base_url + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise OllamaError(f"Ollama returned HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise OllamaError(f"Ollama request failed: {type(exc).__name__}") from exc
        if cancel_event is not None and cancel_event.is_set():
            raise OllamaCancelled("inference cancelled while request was in flight")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise OllamaError("Ollama response exceeded the 4 MiB safety limit")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise OllamaError("Ollama response must be a JSON object")
        if result.get("error"):
            raise OllamaError("Ollama reported an inference error")
        return result


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
