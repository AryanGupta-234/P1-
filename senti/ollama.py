"""Direct Ollama HTTP client. SENTI never shells out to the Ollama CLI."""
from __future__ import annotations

import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from senti.contracts import ModelRequest, ModelResponse, ToolCall


class OllamaError(RuntimeError):
    """Base class for local model transport failures."""


class OllamaUnavailable(OllamaError):
    """The configured local Ollama API is unavailable or invalid."""


class OllamaClient:
    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(self, base_url: str = "http://127.0.0.1:11434", *, default_timeout: float = 90.0):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("SENTI Ollama must use a local loopback HTTP endpoint")
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

    def _stream_chat(self, body: dict, *, timeout: float, on_delta) -> dict:
        """Consume Ollama's NDJSON stream, forwarding content deltas; returns a merged payload."""
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(f"{self.base_url}/api/chat", data=data, method="POST",
                          headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"})
        content: list[str] = []
        thinking: list[str] = []
        calls: list = []
        final: dict = {}
        received = 0
        try:
            with urlopen(request, timeout=timeout) as response:
                for raw in response:
                    received += len(raw)
                    if received > self.MAX_RESPONSE_BYTES:
                        raise OllamaUnavailable("Ollama response exceeded the 8 MiB limit")
                    line = raw.strip()
                    if not line:
                        continue
                    chunk = json.loads(line.decode("utf-8"))
                    if not isinstance(chunk, dict):
                        continue
                    if chunk.get("error"):
                        raise OllamaUnavailable(f"Ollama error: {str(chunk['error'])[:300]}")
                    message = chunk.get("message") or {}
                    if isinstance(message, dict):
                        piece = message.get("content") or ""
                        if isinstance(piece, str) and piece:
                            content.append(piece)
                            try:
                                on_delta(piece)
                            except Exception:  # noqa: BLE001 - presentation never breaks inference
                                pass
                        reasoning = message.get("thinking") or ""
                        if isinstance(reasoning, str) and reasoning:
                            thinking.append(reasoning)
                        if isinstance(message.get("tool_calls"), list):
                            calls.extend(message["tool_calls"])
                    if chunk.get("done"):
                        final = chunk
                        break
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise OllamaUnavailable(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama API request failed: {type(exc).__name__}") from exc
        merged = dict(final)
        merged["message"] = {"role": "assistant", "content": "".join(content),
                             "thinking": "".join(thinking), "tool_calls": calls}
        return merged

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

    def show_model(self, model: str, *, timeout: float = 5.0) -> dict:
        """Read local Ollama model metadata; do not expose or persist the full Modelfile."""
        installed = set(self.list_models(timeout=min(5.0, timeout)))
        resolved = self.resolve_installed_tag(model, installed)
        if resolved is None:
            raise OllamaUnavailable(f"Model '{model}' is not installed.")
        payload = self._request("/api/show", payload={"model": resolved, "verbose": False},
                                timeout=min(timeout, self.default_timeout))
        details = payload.get("details", {})
        if not isinstance(details, dict):
            details = {}
        raw_families = details.get("families", [])
        return {
            "resolved_tag": resolved,
            "family": str(details.get("family") or "unknown")[:100],
            "families": [str(x)[:100] for x in raw_families[:8]] if isinstance(raw_families, list) else [],
            "parameter_size": str(details.get("parameter_size") or "unknown")[:60],
            "quantization_level": str(details.get("quantization_level") or "unknown")[:40],
            "format": str(details.get("format") or "unknown")[:40],
        }

    def model_system_prompt(self, model: str, *, timeout: float = 5.0) -> str:
        """Return the private SYSTEM block of a local model (kept in memory only, never persisted).

        SENTI's identity framework lives in its hidden local Modelfile. Because Ollama only applies
        the Modelfile SYSTEM when a request has no system message, the host reads it here and
        composes it with live context instead of duplicating identity text in public source.
        """
        installed = set(self.list_models(timeout=min(5.0, timeout)))
        resolved = self.resolve_installed_tag(model, installed)
        if resolved is None:
            raise OllamaUnavailable(f"Model '{model}' is not installed.")
        payload = self._request("/api/show", payload={"model": resolved, "verbose": False},
                                timeout=min(timeout, self.default_timeout))
        system = payload.get("system", "")
        return system[:20_000] if isinstance(system, str) else ""

    def embed(self, texts: list[str], *, model: str = "nomic-embed-text",
              timeout: float = 30.0) -> list[list[float]]:
        """Embed texts with a local embedding model. Never downloads a model."""
        if not isinstance(texts, list) or not texts or len(texts) > 256:
            raise ValueError("embed expects 1 to 256 texts")
        clean = [str(text)[:4_000] for text in texts]
        payload = self._request("/api/embed", payload={"model": model, "input": clean, "keep_alive": "30m"},
                                timeout=min(timeout, self.default_timeout))
        vectors = payload.get("embeddings")
        if (not isinstance(vectors, list) or len(vectors) != len(clean)
                or not all(isinstance(v, list) and v for v in vectors)):
            raise OllamaUnavailable("Ollama returned malformed embeddings")
        return [[float(x) for x in vector] for vector in vectors]

    def chat(self, request: ModelRequest, *, model: str, on_delta=None) -> ModelResponse:
        """Run one chat request. With ``on_delta`` the reply is streamed token by token."""
        installed = set(self.list_models(timeout=min(5.0, request.timeout_seconds)))
        resolved_model = self.resolve_installed_tag(model, installed)
        if resolved_model is None:
            raise OllamaUnavailable(f"Model '{model}' is not installed; SENTI will not download or switch models.")
        messages: list[dict] = []
        for message in request.messages:
            item: dict = {"role": message.role, "content": message.content}
            # Ollama's tool-result message is role=tool plus content; tool identity is
            # retained in the host's local contract and adjacent assistant tool-call turn.
            if message.role == "assistant" and message.thinking:
                # Re-send reasoning exactly as generated so the cached transcript stays valid.
                item["thinking"] = message.thinking
            if message.role == "assistant" and message.tool_calls:
                item["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call in message.tool_calls
                ]
            messages.append(item)
        body: dict = {
            "model": resolved_model,
            "messages": messages,
            "stream": on_delta is not None,
            "think": bool(request.think),
            "keep_alive": "15m",
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
                **({"num_ctx": request.context_tokens} if request.context_tokens else {}),
            },
        }
        if request.tools:
            body["tools"] = request.tools
        if not self._inference_slot.acquire(timeout=request.timeout_seconds):
            raise OllamaUnavailable("Another local inference request is still active")
        started = time.perf_counter()
        try:
            timeout = min(request.timeout_seconds, self.default_timeout)
            if on_delta is None:
                payload = self._request("/api/chat", payload=body, timeout=timeout)
            else:
                payload = self._stream_chat(body, timeout=timeout, on_delta=on_delta)
        finally:
            self._inference_slot.release()
        elapsed = max(0.0, time.perf_counter() - started)
        message = payload.get("message")
        if not isinstance(message, dict):
            raise OllamaUnavailable("Ollama chat response is missing message metadata")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise OllamaUnavailable("Ollama message.content is malformed")
        thinking = message.get("thinking", "")
        if not isinstance(thinking, str):
            thinking = ""
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            raise OllamaUnavailable("Ollama returned an invalid tool-call list")
        raw_calls = raw_calls[:4]  # bounded: extra proposals in one turn are dropped, not executed
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
            model=str(payload.get("model") or resolved_model), content=content[:40_000], tool_calls=calls,
            thinking=thinking[:20_000],
            elapsed_seconds=elapsed, prompt_tokens=count("prompt_eval_count"),
            completion_tokens=count("eval_count"),
            prompt_eval_seconds=(count("prompt_eval_duration") or 0) / 1e9 if count("prompt_eval_duration") is not None else None,
            generation_seconds=(count("eval_duration") or 0) / 1e9 if count("eval_duration") is not None else None,
        )
