"""Explicit-egress OpenAI-compatible chat adapter.

This adapter is never selected as an automatic fallback. Callers must explicitly
construct it with allow_cloud_egress=True for each application process.
"""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from aie.models.base import ModelRequest, ModelResponse


class CloudModelError(RuntimeError):
    """Base error for remote model requests."""


class CloudEgressDenied(CloudModelError):
    """Raised when remote egress has not been explicitly authorized."""


class CloudModelUnavailable(CloudModelError):
    """Raised when cloud credentials, provider or response are unavailable."""


class OpenAICompatibleClient:
    """OpenAI-compatible API client with explicit opt-in and bounded payloads."""

    MAX_RESPONSE_BYTES = 8 * 1024 * 1024

    def __init__(
        self,
        *,
        allow_cloud_egress: bool = False,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        if not allow_cloud_egress:
            raise CloudEgressDenied(
                "Cloud egress is disabled. Pass --allow-cloud-egress for this request."
            )

        self.base_url = (
            base_url or os.environ.get("AIE_CLOUD_BASE_URL", "")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("AIE_CLOUD_API_KEY", "")
        self.model = model or os.environ.get("AIE_CLOUD_MODEL", "")

        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise CloudModelUnavailable(
                "AIE_CLOUD_BASE_URL must be an HTTPS OpenAI-compatible endpoint."
            )
        if parsed.username or parsed.password:
            raise CloudModelUnavailable(
                "Credentials must not be embedded in AIE_CLOUD_BASE_URL."
            )
        if not self.api_key:
            raise CloudModelUnavailable("AIE_CLOUD_API_KEY is not configured.")
        if not self.model:
            raise CloudModelUnavailable("AIE_CLOUD_MODEL is not configured.")

    def chat(self, request: ModelRequest) -> ModelResponse:
        body = {
            "model": self.model,
            "messages": [
                {"role": item.role, "content": item.content}
                for item in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.response_format == "json":
            body["response_format"] = {"type": "json_object"}
        encoded = json.dumps(body).encode("utf-8")
        http_request = Request(
            f"{self.base_url}/chat/completions",
            data=encoded,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        started = time.perf_counter()
        try:
            with urlopen(http_request, timeout=request.timeout_seconds) as response:
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(raw) > self.MAX_RESPONSE_BYTES:
                raise CloudModelUnavailable("Cloud model response exceeds the 8 MiB limit.")
            payload = json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read(1024).decode("utf-8", errors="replace")
            raise CloudModelUnavailable(
                f"Cloud model returned HTTP {exc.code}: {detail}"
            ) from exc
        except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise CloudModelUnavailable(
                f"Cloud model request failed: {type(exc).__name__}"
            ) from exc

        elapsed = max(0.0, time.perf_counter() - started)
        choices = payload.get("choices") if isinstance(payload, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise CloudModelUnavailable("Cloud response has no choices[0].message.content.")

        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None

        def token_count(value) -> int | None:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            return value

        return ModelResponse(
            model=str(payload.get("model") or self.model),
            content=content,
            elapsed_seconds=elapsed,
            prompt_tokens=token_count(prompt_tokens),
            completion_tokens=token_count(completion_tokens),
            local_inference=False,
            provider="openai-compatible",
        )


class GroqClient(OpenAICompatibleClient):
    """Groq's OpenAI-compatible API with a known model and explicit egress opt-in."""

    def __init__(self, *, allow_cloud_egress: bool = False) -> None:
        super().__init__(
            allow_cloud_egress=allow_cloud_egress,
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ.get("GROQ_API_KEY", ""),
            model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )

    def chat(self, request: ModelRequest) -> ModelResponse:
        response = super().chat(request)
        return response.model_copy(update={"provider": "groq"})
