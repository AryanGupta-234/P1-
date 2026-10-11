"""Local-first Ollama chat adapter with strict egress and model-download policy."""
from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from aie.model_policy import ollama_base_url
from aie.models.base import ModelRequest, ModelResponse


class OllamaError(RuntimeError):
    """Base error for local Ollama integration."""


class OllamaUnavailable(OllamaError):
    """Ollama is unreachable or returned an invalid response."""


class OllamaRemoteEndpointDenied(OllamaError):
    """A non-loopback Ollama URL was configured without explicit permission."""


def _is_loopback_host(host: str | None) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


class OllamaClient:
    """Talk to Ollama without pulling models or silently sending data remotely."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        allow_remote: bool = False,
        default_timeout: float = 60.0,
    ) -> None:
        if not 1.0 <= default_timeout <= 300.0:
            raise ValueError("default_timeout must be between 1 and 300 seconds")
        self.base_url = (base_url or ollama_base_url()).rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Ollama URL must be a valid HTTP(S) endpoint")
        if parsed.username or parsed.password:
            raise ValueError("Credentials must not be embedded in the Ollama URL")
        if not _is_loopback_host(parsed.hostname):
            if not allow_remote:
                raise OllamaRemoteEndpointDenied(
                    "Remote Ollama is disabled. Pass explicit remote permission to enable egress."
                )
            if parsed.scheme != "https":
                raise OllamaRemoteEndpointDenied(
                    "Remote Ollama endpoints must use HTTPS."
                )
        self.default_timeout = default_timeout

    def _request(self, path: str, *, payload: dict | None, timeout: float) -> dict:
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise OllamaUnavailable(
                f"Ollama returned HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama request failed: {type(exc).__name__}") from exc
        if not isinstance(parsed, dict):
            raise OllamaUnavailable("Ollama response must be a JSON object")
        return parsed

    def list_models(self, *, timeout: float = 2.0) -> list[str]:
        """List already-installed models. This method never triggers a pull."""
        payload = self._request("/api/tags", payload=None, timeout=timeout)
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            raise OllamaUnavailable("Ollama model-list response is malformed")
        return sorted({
            item["name"]
            for item in raw_models
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and item["name"]
        })

    def chat(
        self,
        request: ModelRequest,
        *,
        model: str,
        installed_models: list[str] | set[str] | None = None,
    ) -> ModelResponse:
        """Run a non-streaming chat request against an installed model only."""
        if not model or not isinstance(model, str):
            raise ValueError("model must be a non-empty installed model name")
        installed = (
            set(installed_models)
            if installed_models is not None
            else set(self.list_models(timeout=min(5.0, request.timeout_seconds)))
        )
        if model not in installed:
            raise OllamaUnavailable(
                f"Model '{model}' is not installed. AIE never downloads models automatically."
            )

        body = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        started = time.perf_counter()
        payload = self._request(
            "/api/chat",
            payload=body,
            timeout=min(request.timeout_seconds, self.default_timeout),
        )
        elapsed = max(0.0, time.perf_counter() - started)

        message = payload.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise OllamaUnavailable("Ollama chat response has no message.content string")

        def optional_count(key: str) -> int | None:
            value = payload.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        return ModelResponse(
            model=str(payload.get("model") or model),
            content=content,
            elapsed_seconds=elapsed,
            prompt_tokens=optional_count("prompt_eval_count"),
            completion_tokens=optional_count("eval_count"),
            local_inference=_is_loopback_host(urlparse(self.base_url).hostname),
            provider="ollama",
        )
