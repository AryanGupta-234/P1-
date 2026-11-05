"""Direct Ollama HTTP client. APEX never shells out to the Ollama CLI."""
from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from apex.contracts import ModelRequest, ModelResponse, ToolCall


class OllamaError(RuntimeError):
    """Base class for local model transport failures."""


class OllamaUnavailable(OllamaError):
    """The configured local Ollama API is unavailable or invalid."""


class OllamaClient:
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self, base_url: str = "http://127.0.0.1:11434", *, default_timeout: float = 90.0):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("APEX Ollama must use a local loopback HTTP endpoint")
        if parsed.username or parsed.password:
            raise ValueError("credentials are not permitted in the Ollama URL")
        if not 1 <= default_timeout <= 300:
            raise ValueError("default_timeout must be between 1 and 300 seconds")
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout
        self._inference_slot = threading.BoundedSemaphore(1)

    def _request(self, path: str, *, payload: dict | None, timeout: float) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})},
            method="POST" if data else "GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(raw) > self.MAX_RESPONSE_BYTES:
                raise OllamaUnavailable("Ollama response exceeded the 8 MiB limit")
            result = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise OllamaUnavailable(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama API request failed: {type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise OllamaUnavailable("Ollama returned a non-object JSON response")
        return result

    def list_models(self, *, timeout: float = 3.0) -> list[str]:
        result = self._request("/api/tags", payload=None, timeout=timeout)
        models = result.get("models")
        if not isinstance(models, list):
            raise OllamaUnavailable("Ollama model catalogue is malformed")
        return sorted({
            item["name"] for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]
        })

    @staticmethod
    def resolve_installed_tag(model: str, installed: list[str] | set[str]) -> str | None:
        """Resolve only the exact tag or its implicit :latest spelling; never fuzzy-switch."""
        if model in installed:
            return model
        latest = f"{model}:latest"
        if ":" not in model and latest in installed:
            return latest
        return None

    def chat(self, request: ModelRequest, *, model: str) -> ModelResponse:
        installed = set(self.list_models(timeout=min(5.0, request.timeout_seconds)))
        resolved_model = self.resolve_installed_tag(model, installed)
        if resolved_model is None:
            raise OllamaUnavailable(f"Model '{model}' is not installed; APEX will not download or switch models.")
        messages: list[dict] = []
        for message in request.messages:
            item: dict = {"role": message.role, "content": message.content}
            # Ollama's tool-result message is role=tool plus content; tool identity is
            # retained in the host's local contract and adjacent assistant tool-call turn.
            if message.role == "assistant" and message.tool_calls:
                item["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call in message.tool_calls
                ]
            messages.append(item)
        body: dict = {
            "model": resolved_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        if request.tools:
            body["tools"] = request.tools
        if not self._inference_slot.acquire(timeout=request.timeout_seconds):
            raise OllamaUnavailable("Another local inference request is still active")
        started = time.perf_counter()
        try:
            payload = self._request("/api/chat", payload=body, timeout=min(request.timeout_seconds, self.default_timeout))
        finally:
            self._inference_slot.release()
        elapsed = max(0.0, time.perf_counter() - started)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise OllamaUnavailable("Ollama chat response is missing message metadata")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise OllamaUnavailable("Ollama message.content is malformed")
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list) or len(raw_calls) > 8:
            raise OllamaUnavailable("Ollama returned an invalid or excessive tool-call list")
        calls: list[ToolCall] = []
        for raw in raw_calls:
            function = raw.get("function") if isinstance(raw, dict) else None
            if not isinstance(function, dict):
                raise OllamaUnavailable("Ollama returned a malformed tool call")
            name = function.get("name")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise OllamaUnavailable("Ollama returned invalid tool-call JSON") from exc
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise OllamaUnavailable("Ollama returned invalid tool-call fields")
            calls.append(ToolCall(name=name, arguments=arguments))
        def count(key: str) -> int | None:
            value = payload.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        return ModelResponse(
            model=str(payload.get("model") or resolved_model), content=content, tool_calls=calls,
            elapsed_seconds=elapsed, prompt_tokens=count("prompt_eval_count"),
            completion_tokens=count("eval_count"),
        )
