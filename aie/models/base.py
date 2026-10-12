"""Provider-independent model request and response contracts."""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: Literal["routine", "complex"] = "routine"
    response_format: Literal["text", "json"] = "text"
    messages: list[ChatMessage] = Field(min_length=1, max_length=32)
    max_input_characters: int = Field(default=40_000, ge=512, le=120_000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=512, ge=32, le=4096)
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)

    @model_validator(mode="after")
    def validate_input_budget(self) -> "ModelRequest":
        total_characters = sum(len(message.content) for message in self.messages)
        if total_characters > self.max_input_characters:
            raise ValueError(
                "combined message content exceeds max_input_characters "
                f"({total_characters} > {self.max_input_characters})"
            )
        return self


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    content: str
    elapsed_seconds: float = Field(ge=0.0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    local_inference: bool
    provider: str


class ModelProvider(Protocol):
    def chat(self, request: ModelRequest, *, model: str) -> ModelResponse:
        """Generate a response for a validated model request."""
        ...
