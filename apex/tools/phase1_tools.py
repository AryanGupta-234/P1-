"""Additional Phase 1 capabilities registered by the standalone APEX host."""
from __future__ import annotations

from typing import Any

from apex.tools.registry import CapabilityRegistry, ToolDefinition
from apex.windows import power, security, updates, uia, wireless, bluetooth


def _object(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _forget_memory(store, memory_id: str) -> dict[str, Any]:
    deleted = store.forget_memory(memory_id)
    return {
        "summary": "Memory deleted." if deleted else "No memory matched that identifier.",
        "deleted": deleted,
        "verified": deleted,
    }


def register_phase1_tools(registry: CapabilityRegistry, store) -> None:
    """Register native diagnostics, power control and explicit user-directed memory tools."""
    registry.register(ToolDefinition(
        name="apex_list_power_plans",
        description="List installed Windows power plans and identify the current active plan.",
        parameters=_object(),
        risk="read_only",
        handler=lambda _args: power.list_power_plans(),
        available=power.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_set_power_plan",
        description="Select one exact installed Windows power-plan GUID; host approval is required and the previous GUID is returned for manual recovery.",
        parameters=_object({"guid": {"type": "string", "minLength": 36, "maxLength": 36}}, ["guid"]),
        risk="controlled",
        handler=lambda args: power.set_active_power_plan(args["guid"]),
        available=power.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_get_windows_security_status",
        description="Read Microsoft Defender protection and signature status through WMI. This tool never changes Defender settings.",
        parameters=_object(),
        risk="read_only",
        handler=lambda _args: security.defender_status(),
        available=security.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_get_windows_update_status",
        description="Read Windows Update service posture, installed hotfix metadata and reboot indicators; does not search online or install updates.",
        parameters=_object({"hotfix_limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
        risk="read_only",
        handler=lambda args: updates.update_status(args.get("hotfix_limit", 100)),
        available=updates.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_search_memory",
        description="Search normal-sensitivity APEX memories in the selected namespace. Sensitive memories are never included.",
        parameters=_object({
            "query": {"type": "string", "maxLength": 500},
            "namespace": {"type": "string", "enum": ["personal", "project", "preferences", "technical"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        }, ["query"]),
        risk="read_only",
        handler=lambda args: {
            "summary": "Retrieved matching APEX memories.",
            "memories": store.search_memories(
                args["query"], namespace=args.get("namespace", "personal"),
                limit=args.get("limit", 10), include_sensitive=False,
            ),
            "verified": True,
        },
        available=lambda: store.integrity_check(),
    ))
    registry.register(ToolDefinition(
        name="apex_save_memory",
        description="Save a user-explicit, non-credential memory into APEX's unified database after host approval.",
        parameters=_object({
            "namespace": {"type": "string", "enum": ["personal", "project", "preferences", "technical"]},
            "memory_type": {"type": "string", "enum": ["preference", "fact", "project_context", "workflow", "device", "other"]},
            "payload": {"type": "object"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, ["namespace", "memory_type", "payload"]),
        risk="controlled",
        handler=lambda args: {
            "summary": "Saved the explicitly requested memory.",
            "memory_id": store.add_memory(
                namespace=args["namespace"], memory_type=args["memory_type"],
                payload=args["payload"], source="explicit_user_request",
                sensitivity="normal", confidence=args.get("confidence"),
            ),
            "verified": True,
        },
        available=lambda: store.integrity_check(),
    ))
    registry.register(ToolDefinition(
        name="apex_forget_memory",
        description="Delete one exact APEX memory identifier after host approval.",
        parameters=_object({"memory_id": {"type": "string", "minLength": 1, "maxLength": 64}}, ["memory_id"]),
        risk="controlled",
        handler=lambda args: _forget_memory(store, args["memory_id"]),
        available=lambda: store.integrity_check(),
    ))


    registry.register(ToolDefinition(
        name="apex_uia_wait_for",
        description="Wait up to ten seconds for one uniquely identified, visible and enabled UI Automation control without reading its value.",
        parameters=_object({
            "hwnd": {"type": "integer", "minimum": 1},
            "automation_id": {"type": "string", "maxLength": 120},
            "name": {"type": "string", "maxLength": 160},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 10.0},
        }, ["hwnd"]),
        risk="read_only",
        handler=lambda args: uia.wait_for_control(
            args["hwnd"], args.get("timeout_seconds", 5.0),
            automation_id=args.get("automation_id"), name=args.get("name"),
        ),
        available=uia.provider_available,
    ))


    registry.register(ToolDefinition(
        name="apex_list_wireless_radios",
        description="Inspect the software and hardware radio state for each Windows WLAN interface. Hardware state is read-only.",
        parameters=_object(),
        risk="read_only",
        handler=lambda _args: wireless.list_wireless_radios(),
        available=wireless.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_set_wifi_radio",
        description="Enable or disable the software Wi-Fi radio for one exact interface GUID. This may disconnect Wi-Fi. Hardware switches cannot be overridden; host approval is required.",
        parameters=_object({
            "interface_guid": {"type": "string", "minLength": 36, "maxLength": 36},
            "enabled": {"type": "boolean"},
        }, ["interface_guid", "enabled"]),
        risk="controlled",
        handler=lambda args: wireless.set_wireless_software_radio(
            args["interface_guid"], args["enabled"],
        ),
        available=wireless.provider_available,
        compensation="previous_radios in the execution receipt contain the prior software radio states",
    ))


    registry.register(ToolDefinition(
        name="apex_list_bluetooth_radios",
        description="Inspect available Windows Bluetooth radio names and their effective states.",
        parameters=_object(),
        risk="read_only",
        handler=lambda _args: bluetooth.list_bluetooth_radios(),
        available=bluetooth.provider_available,
    ))
    registry.register(ToolDefinition(
        name="apex_set_bluetooth_radio",
        description="Enable or disable one uniquely named Windows Bluetooth radio through the WinRT radio API. Windows permission and hardware policy are respected; host approval is required.",
        parameters=_object({
            "radio_name": {"type": "string", "minLength": 1, "maxLength": 160},
            "enabled": {"type": "boolean"},
        }, ["radio_name", "enabled"]),
        risk="controlled",
        handler=lambda args: bluetooth.set_bluetooth_radio(args["radio_name"], args["enabled"]),
        available=bluetooth.provider_available,
        compensation="successful execution receipt includes the previous Bluetooth radio state",
    ))
