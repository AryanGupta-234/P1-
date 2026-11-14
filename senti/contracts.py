"""Validated model and tool contracts used by the SENTI host."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_bounded_arguments(self) -> "ToolCall":
        import json
        encoded = json.dumps(self.arguments, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 8192:
            raise ValueError("tool arguments exceed 8 KiB")
        if len(self.arguments) > 20:
            raise ValueError("tool calls may contain at most 20 top-level arguments")
        return self


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(default="", max_length=40_000)
    tool_name: str | None = Field(default=None, max_length=100)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=4)
    thinking: str = Field(default="", max_length=20_000)

    @model_validator(mode="after")
    def validate_tool_message(self) -> "ChatMessage":
        if self.role == "tool" and not self.tool_name:
            raise ValueError("tool messages require tool_name")
        if self.role != "assistant" and self.tool_calls:
            raise ValueError("only assistant messages may contain tool calls")
        if not self.content and not self.tool_calls:
            raise ValueError("messages must contain text or tool calls")
        return self


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=400)
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=80)
    timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    max_output_tokens: int = Field(default=700, ge=32, le=4096)
    temperature: float = Field(default=0.25, ge=0.0, le=2.0)
    think: bool = False
    context_tokens: int | None = Field(default=None, ge=2048, le=131072)


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    content: str = Field(default="", max_length=40_000)
    tool_calls: list[ToolCall] = Field(default_factory=list, max_length=4)
    thinking: str = Field(default="", max_length=20_000)
    elapsed_seconds: float = Field(ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    prompt_eval_seconds: float | None = Field(default=None, ge=0)
    generation_seconds: float | None = Field(default=None, ge=0)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    status: Literal["succeeded", "failed", "approval_required", "unavailable", "denied", "interrupted"]
    summary: str = Field(min_length=1, max_length=500)
    data: dict[str, Any] = Field(default_factory=dict)
    verified: bool = False
