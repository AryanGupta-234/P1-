"""Typed capability registry. Model tool calls are proposals, never executable code."""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from apex.contracts import ToolResult

Risk = Literal["read_only", "low", "controlled", "high"]
ApprovalHandler = Callable[[str, dict[str, Any], Risk], bool]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    available: Callable[[], bool] = lambda: True
    max_per_minute: int = 10

    def ollama_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters,
        }}


class CapabilityRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._calls: dict[str, deque[float]] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate APEX tool: {tool.name}")
        if not tool.name.startswith("apex_"):
            raise ValueError("APEX tool names must use the apex_ prefix")
        self._tools[tool.name] = tool

    def definitions(self, *, available_only: bool = True) -> list[dict[str, Any]]:
        output = []
        for tool in self._tools.values():
            try:
                healthy = bool(tool.available())
            except Exception:
                healthy = False
            if healthy or not available_only:
                output.append(tool.ollama_schema())
        return output

    def manifest(self) -> list[dict[str, Any]]:
        rows = []
        for tool in self._tools.values():
            try:
                healthy = bool(tool.available())
            except Exception:
                healthy = False
            rows.append({"name": tool.name, "description": tool.description,
                         "risk": tool.risk, "available": healthy})
        return rows

    @staticmethod
    def _validate_value(value: Any, schema: dict[str, Any], path: str = "arguments") -> None:
        expected = schema.get("type")
        type_ok = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
        }
        if expected in type_ok and not type_ok[expected](value):
            raise ValueError(f"{path} must be {expected}")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of the allowed values")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1_000_000):
                raise ValueError(f"{path} length is outside the allowed range")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
                raise ValueError(f"{path} is outside the allowed numeric range")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1_000_000):
                raise ValueError(f"{path} item count is outside the allowed range")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    CapabilityRegistry._validate_value(item, item_schema, f"{path}[{index}]")
        if isinstance(value, dict):
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            missing = [key for key in required if key not in value]
            if missing:
                raise ValueError(f"{path} is missing required fields: {', '.join(missing)}")
            if schema.get("additionalProperties", True) is False:
                unknown = set(value) - set(properties)
                if unknown:
                    raise ValueError(f"{path} contains unsupported fields: {', '.join(sorted(unknown))}")
            for key, item in value.items():
                if key in properties:
                    CapabilityRegistry._validate_value(item, properties[key], f"{path}.{key}")

    def dispatch(self, name: str, arguments: dict[str, Any], *, approval: ApprovalHandler | None = None) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(tool_name=name[:100] or "unknown", status="denied", summary="Tool is not registered.")
        try:
            if not tool.available():
                return ToolResult(tool_name=name, status="unavailable", summary="The Windows capability provider is unavailable.")
        except Exception:
            return ToolResult(tool_name=name, status="unavailable", summary="The capability health check failed.")
        if not isinstance(arguments, dict):
            return ToolResult(tool_name=name, status="denied", summary="Tool arguments must be a JSON object.")
        try:
            self._validate_value(arguments, tool.parameters)
        except ValueError as exc:
            return ToolResult(tool_name=name, status="denied", summary=f"Invalid arguments: {str(exc)[:300]}")
        now = time.monotonic()
        calls = self._calls.setdefault(name, deque())
        while calls and now - calls[0] >= 60.0:
            calls.popleft()
        if len(calls) >= tool.max_per_minute:
            return ToolResult(tool_name=name, status="denied", summary="Capability rate limit reached; retry later.")
        # All changes to the desktop/system require a host approval callback.
        if tool.risk != "read_only":
            if approval is None:
                return ToolResult(tool_name=name, status="approval_required", summary="This action requires approval from the APEX host.")
            try:
                approved = approval(name, arguments, tool.risk)
            except Exception:
                approved = False
            if not approved:
                return ToolResult(tool_name=name, status="denied", summary="The APEX host did not approve this exact action.")
        try:
            result = tool.handler(arguments)
            calls.append(now)
            if not isinstance(result, dict):
                raise TypeError("tool handler did not return an object")
            return ToolResult(tool_name=name, status="succeeded", summary=str(result.pop("summary", "Completed."))[:500],
                              data=result, verified=bool(result.pop("verified", False)))
        except (ValueError, ValidationError) as exc:
            return ToolResult(tool_name=name, status="denied", summary=f"Invalid arguments: {str(exc)[:300]}")
        except Exception as exc:  # noqa: BLE001 - tool error is returned as bounded data, not executed again.
            if type(exc).__name__ == "UserInterrupted":
                return ToolResult(tool_name=name, status="interrupted", summary="Desktop interaction stopped because user input or focus changed.")
            return ToolResult(tool_name=name, status="failed", summary=f"Tool failed: {type(exc).__name__}")
