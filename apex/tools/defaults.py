"""Default APEX tools backed by independent Windows providers."""
from __future__ import annotations

import os
from typing import Any

from apex.tools.registry import CapabilityRegistry, ToolDefinition
from apex.windows import (app_catalog, audio, clipboard, desktop, display, files, host_details, inventory,
                          launch, network, scheduled_tasks, services, settings as settings_provider, uia, window_ops)


def _object(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _window_properties() -> dict[str, Any]:
    return {"hwnd": {"type": "integer", "minimum": 1}}


def _control_properties() -> dict[str, Any]:
    return {"hwnd": {"type": "integer", "minimum": 1},
            "automation_id": {"type": "string", "maxLength": 120},
            "name": {"type": "string", "maxLength": 160}}


def build_default_registry(store=None, runtime_settings=None) -> CapabilityRegistry:
    registry = CapabilityRegistry()

    def persist_apps(rows):
        if store is not None:
            for row in rows:
                store.upsert_app(display_name=row.display_name, executable_path=row.executable_path,
                                 aliases=list(row.aliases), metadata={"publisher": row.publisher, "version": row.version},
                                 trust_state=row.trust_state, source=row.source, available=row.available)
        return rows
    windows = lambda: os.name == "nt"

    registry.register(ToolDefinition(
        name="apex_get_system_summary", description="Read a basic Windows and hardware summary.",
        parameters=_object(), risk="read_only", handler=lambda _args: inventory.system_summary(), available=windows))
    registry.register(ToolDefinition(
        name="apex_list_processes", description="List a bounded set of live processes and basic resource metadata.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
        risk="read_only", handler=lambda args: inventory.list_processes(args.get("limit", 100)), available=windows))
    registry.register(ToolDefinition(
        name="apex_get_network_summary", description="Inspect Windows network adapters, addresses, link state and traffic counters.",
        parameters=_object(), risk="read_only", handler=lambda _args: host_details.network_summary(),
        available=host_details.provider_available))
    registry.register(ToolDefinition(
        name="apex_get_storage_summary", description="Inspect mounted volume capacity and disk I/O counters.",
        parameters=_object(), risk="read_only", handler=lambda _args: host_details.storage_summary(),
        available=host_details.provider_available))
    registry.register(ToolDefinition(
        name="apex_list_network_configurations", description="Inspect active network adapter IP, gateway, DNS and DHCP configuration.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 300}}),
        risk="read_only", handler=lambda args: network.list_configurations(args.get("limit", 100)),
        available=network.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_dns_servers", description="Set and verify DNS servers for one exact IP-enabled adapter index; previous values are captured for recovery.",
        parameters=_object({"adapter_index": {"type": "integer", "minimum": 0},
                            "dns_servers": {"type": "array", "minItems": 1, "maxItems": 4,
                                            "items": {"type": "string", "maxLength": 64}}},
                           ["adapter_index", "dns_servers"]), risk="controlled",
        handler=lambda args: network.set_dns_servers(args["adapter_index"], args["dns_servers"]),
        available=network.provider_available))
    registry.register(ToolDefinition(
        name="apex_get_brightness", description="Read WMI-supported display brightness levels.",
        parameters=_object(), risk="read_only", handler=lambda _args: display.get_brightness(),
        available=display.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_brightness", description="Set supported monitor brightness and verify the read-back value.",
        parameters=_object({"percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["percent"]),
        risk="low", handler=lambda args: display.set_brightness(args["percent"]), available=display.provider_available))
    registry.register(ToolDefinition(
        name="apex_list_scheduled_tasks", description="Inspect a bounded Task Scheduler catalogue including enabled state and recent result.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        risk="read_only", handler=lambda args: scheduled_tasks.list_tasks(args.get("limit", 300)),
        available=scheduled_tasks.provider_available))
    registry.register(ToolDefinition(
        name="apex_run_scheduled_task", description="Run one exact non-Microsoft Task Scheduler path after host approval.",
        parameters=_object({"path": {"type": "string", "minLength": 2, "maxLength": 500}}, ["path"]),
        risk="controlled", handler=lambda args: scheduled_tasks.run_task(args["path"]),
        available=scheduled_tasks.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_scheduled_task_enabled", description="Enable or disable one exact non-Microsoft Task Scheduler task after host approval.",
        parameters=_object({"path": {"type": "string", "minLength": 2, "maxLength": 500},
                            "enabled": {"type": "boolean"}}, ["path", "enabled"]), risk="controlled",
        handler=lambda args: scheduled_tasks.set_task_enabled(args["path"], args["enabled"]),
        available=scheduled_tasks.provider_available))
    registry.register(ToolDefinition(
        name="apex_list_services", description="List a bounded inventory of Windows services and states.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        risk="read_only", handler=lambda args: services.list_services(args.get("limit", 300)),
        available=services.provider_available))
    registry.register(ToolDefinition(
        name="apex_list_startup_entries", description="Inspect allowlisted Run and RunOnce startup registry metadata.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        risk="read_only", handler=lambda args: host_details.startup_entries(args.get("limit", 200)),
        available=windows))
    registry.register(ToolDefinition(
        name="apex_list_pnp_devices", description="Inspect Plug and Play device names, status and problem codes.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 1000}}),
        risk="read_only", handler=lambda args: host_details.pnp_devices(args.get("limit", 300)),
        available=lambda: windows() and host_details.provider_available()))
    registry.register(ToolDefinition(
        name="apex_get_recent_events", description="Read metadata from the System or Application event log; event message text is excluded.",
        parameters=_object({"log_name": {"type": "string", "enum": ["System", "Application"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
        risk="read_only", handler=lambda args: host_details.recent_events(args.get("log_name", "System"), args.get("limit", 50)),
        available=windows))
    registry.register(ToolDefinition(
        name="apex_list_windows", description="List visible top-level Windows and their process IDs.",
        parameters=_object({"limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
        risk="read_only", handler=lambda args: inventory.list_windows(args.get("limit", 100),
                include_titles=bool(getattr(runtime_settings, "include_window_titles", False))), available=windows))
    registry.register(ToolDefinition(
        name="apex_activate_window", description="Activate a specific visible user window by its current HWND.",
        parameters=_object(_window_properties(), ["hwnd"]), risk="low",
        handler=lambda args: window_ops.activate(args["hwnd"]), available=window_ops.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_window_state", description="Minimize, maximize or restore a visible user window by HWND.",
        parameters=_object({**_window_properties(), "command": {"type": "string", "enum": ["minimize", "maximize", "restore"]}},
                           ["hwnd", "command"]), risk="low",
        handler=lambda args: window_ops.show(args["hwnd"], args["command"]), available=window_ops.provider_available))
    registry.register(ToolDefinition(
        name="apex_move_resize_window", description="Move and resize a user window to bounded screen coordinates.",
        parameters=_object({**_window_properties(), "x": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "y": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "width": {"type": "integer", "minimum": 100, "maximum": 16384},
                            "height": {"type": "integer", "minimum": 100, "maximum": 16384}},
                           ["hwnd", "x", "y", "width", "height"]), risk="controlled",
        handler=lambda args: window_ops.move_resize(args["hwnd"], args["x"], args["y"], args["width"], args["height"]),
        available=window_ops.provider_available))
    registry.register(ToolDefinition(
        name="apex_close_window", description="Request a graceful close for a user-owned window; never force-terminates the process.",
        parameters=_object(_window_properties(), ["hwnd"]), risk="controlled",
        handler=lambda args: window_ops.close(args["hwnd"]), available=window_ops.provider_available))
    registry.register(ToolDefinition(
        name="apex_open_settings", description="Open one allowlisted Windows Settings page by key.",
        parameters=_object({"target": {"type": "string", "enum": sorted(settings_provider.SETTINGS_URIS)}}, ["target"]),
        risk="low", handler=lambda args: settings_provider.open_settings(args["target"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_open_management_console", description="Open one allowlisted Windows MMC console.",
        parameters=_object({"target": {"type": "string", "enum": sorted(settings_provider.CONSOLE_TARGETS)}}, ["target"]),
        risk="low", handler=lambda args: settings_provider.open_console(args["target"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_list_directory", description="List direct metadata for a directory inside an approved user file root.",
        parameters=_object({"path": {"type": "string", "minLength": 3, "maxLength": 500},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 300}}, ["path"]),
        risk="read_only", handler=lambda args: files.list_directory(args["path"], args.get("limit", 100)),
        available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_create_folder", description="Create one folder beneath an approved user file root.",
        parameters=_object({"path": {"type": "string", "minLength": 3, "maxLength": 500}}, ["path"]),
        risk="controlled", handler=lambda args: files.create_folder(args["path"]), available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_copy_file", description="Copy one regular file between approved user file roots.",
        parameters=_object({"source": {"type": "string", "minLength": 3, "maxLength": 500},
                            "destination": {"type": "string", "minLength": 3, "maxLength": 500}}, ["source", "destination"]),
        risk="controlled", handler=lambda args: files.copy_file(args["source"], args["destination"]),
        available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_move_file", description="Move one regular file between approved user file roots.",
        parameters=_object({"source": {"type": "string", "minLength": 3, "maxLength": 500},
                            "destination": {"type": "string", "minLength": 3, "maxLength": 500}}, ["source", "destination"]),
        risk="controlled", handler=lambda args: files.move_file(args["source"], args["destination"]),
        available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_rename_file", description="Rename one regular file within an approved user file root.",
        parameters=_object({"source": {"type": "string", "minLength": 3, "maxLength": 500},
                            "new_name": {"type": "string", "minLength": 1, "maxLength": 240}}, ["source", "new_name"]),
        risk="controlled", handler=lambda args: files.rename_file(args["source"], args["new_name"]),
        available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_recycle_bin_delete", description="Move one approved file or directory to the Windows Recycle Bin; permanent deletion is unavailable.",
        parameters=_object({"path": {"type": "string", "minLength": 3, "maxLength": 500}}, ["path"]),
        risk="controlled", handler=lambda args: files.move_to_recycle_bin(args["path"]), available=files.provider_available))
    registry.register(ToolDefinition(
        name="apex_service_control", description="Start or stop an approved noncritical Windows service by exact service name.",
        parameters=_object({"service_name": {"type": "string", "minLength": 1, "maxLength": 256},
                            "action": {"type": "string", "enum": ["start", "stop"]}}, ["service_name", "action"]),
        risk="controlled", handler=lambda args: services.change_service(args["service_name"], args["action"]),
        available=services.provider_available))
    registry.register(ToolDefinition(
        name="apex_discover_applications", description="Read application names and launch candidates from Windows registration metadata.",
        parameters=_object(), risk="read_only", handler=lambda _args: launch.discover_applications(store=store), available=windows))

    def _scan_volume(args):
        rows = list(app_catalog.AppDiscovery().scan_volume(
            args["root"], max_files=args.get("max_files", 20000),
            max_seconds=args.get("max_seconds", 60.0)))
        persist_apps(rows)
        return {"summary": f"Discovered {len(rows)} executable metadata records.", "count": len(rows),
                "applications": [{"display_name": row.display_name, "executable_path": row.executable_path,
                                  "source": row.source} for row in rows[:500]], "verified": True}

    registry.register(ToolDefinition(
        name="apex_scan_application_volume", description="Cancellably scan one selected fixed local volume for executable metadata only.",
        parameters=_object({"root": {"type": "string", "minLength": 3, "maxLength": 260},
                            "max_files": {"type": "integer", "minimum": 1, "maximum": 50000},
                            "max_seconds": {"type": "number", "minimum": 1, "maximum": 300}}, ["root"]),
        risk="controlled", handler=lambda args: _scan_volume(args), available=windows))
    registry.register(ToolDefinition(
        name="apex_launch_application", description="Launch an installed application only after unambiguous registry-based resolution and host approval.",
        parameters=_object({"application": {"type": "string", "minLength": 1, "maxLength": 120}}, ["application"]),
        risk="controlled", handler=lambda args: launch.launch_application(args["application"], store=store), available=windows))
    registry.register(ToolDefinition(
        name="apex_get_master_volume", description="Read Windows master output volume and mute state.",
        parameters=_object(), risk="read_only", handler=lambda _args: audio.get_master_volume(), available=windows))
    registry.register(ToolDefinition(
        name="apex_set_master_volume", description="Set Windows master output volume to an exact 0–100 percentage and verify it.",
        parameters=_object({"volume_percent": {"type": "integer", "minimum": 0, "maximum": 100}}, ["volume_percent"]),
        risk="low", handler=lambda args: audio.set_master_volume(args["volume_percent"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_set_master_mute", description="Set Windows master output mute state and verify it.",
        parameters=_object({"muted": {"type": "boolean"}}, ["muted"]),
        risk="low", handler=lambda args: audio.set_master_mute(args["muted"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_get_application_audio_sessions", description="List running application audio sessions and their current volume/mute state.",
        parameters=_object(), risk="read_only", handler=lambda _args: audio.list_application_sessions(),
        available=audio.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_application_audio_volume", description="Set one unambiguous Windows audio session identified by PID and process name.",
        parameters=_object({"pid": {"type": "integer", "minimum": 1},
                            "process_name": {"type": "string", "minLength": 1, "maxLength": 180},
                            "volume_percent": {"type": "integer", "minimum": 0, "maximum": 100}},
                           ["pid", "process_name", "volume_percent"]), risk="controlled",
        handler=lambda args: audio.set_application_session_volume(args["pid"], args["process_name"], args["volume_percent"]),
        available=audio.provider_available))
    registry.register(ToolDefinition(
        name="apex_get_clipboard_text", description="Read clipboard text only in response to an explicit user request and host approval.",
        parameters=_object(), risk="controlled", handler=lambda _args: clipboard.get_text(),
        available=clipboard.provider_available))
    registry.register(ToolDefinition(
        name="apex_set_clipboard_text", description="Set clipboard text only in response to an explicit user request and host approval.",
        parameters=_object({"text": {"type": "string", "maxLength": 20000}}, ["text"]), risk="controlled",
        handler=lambda args: clipboard.set_text(args["text"]), available=clipboard.provider_available))
    registry.register(ToolDefinition(
        name="apex_mouse_move", description="Move the pointer within a freshly verified foreground window.",
        parameters=_object({**_window_properties(), "x": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "y": {"type": "integer", "minimum": -32768, "maximum": 32767}}, ["hwnd", "x", "y"]),
        risk="controlled", handler=lambda args: desktop.move_pointer(args["hwnd"], args["x"], args["y"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_mouse_click", description="Click or double-click within an exact foreground window; coordinates must be inside its bounds.",
        parameters=_object({**_window_properties(), "x": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "y": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "button": {"type": "string", "enum": ["left", "right", "middle"]},
                            "count": {"type": "integer", "enum": [1, 2]}}, ["hwnd", "x", "y"]),
        risk="controlled", handler=lambda args: desktop.click(args["hwnd"], args["x"], args["y"],
                                                                args.get("button", "left"), count=args.get("count", 1)),
        available=windows))
    registry.register(ToolDefinition(
        name="apex_scroll", description="Scroll the verified foreground window vertically or horizontally.",
        parameters=_object({**_window_properties(), "amount": {"type": "integer", "minimum": -20, "maximum": 20},
                            "axis": {"type": "string", "enum": ["vertical", "horizontal"]},
                            "x": {"type": "integer", "minimum": -32768, "maximum": 32767},
                            "y": {"type": "integer", "minimum": -32768, "maximum": 32767}}, ["hwnd", "amount", "x", "y"]),
        risk="controlled", handler=lambda args: desktop.scroll(args["hwnd"], args["amount"], args.get("axis", "vertical"),
                                                                x=args["x"], y=args["y"]),
        available=windows))
    registry.register(ToolDefinition(
        name="apex_press_hotkey", description="Send a bounded named-key combination to the verified foreground window.",
        parameters=_object({**_window_properties(), "keys": {"type": "array", "minItems": 1, "maxItems": 4,
                                                                "items": {"type": "string"}}}, ["hwnd", "keys"]),
        risk="controlled", handler=lambda args: desktop.press_hotkey(args["hwnd"], args["keys"]), available=windows))
    registry.register(ToolDefinition(
        name="apex_inspect_uia", description="Inspect a bounded semantic UI Automation tree for an exact window handle.",
        parameters=_object({**_window_properties(), "limit": {"type": "integer", "minimum": 1, "maximum": 300}}, ["hwnd"]),
        risk="read_only", handler=lambda args: uia.inspect_tree(args["hwnd"], args.get("limit", 100)), available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_invoke", description="Invoke one uniquely identified non-password UI Automation control.",
        parameters=_object(_control_properties(), ["hwnd"]), risk="controlled",
        handler=lambda args: uia.invoke(args["hwnd"], automation_id=args.get("automation_id"), name=args.get("name")), available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_set_value", description="Set and verify a value on one uniquely identified non-password UI Automation control.",
        parameters=_object({**_control_properties(), "value": {"type": "string", "maxLength": 2000}}, ["hwnd", "value"]),
        risk="controlled", handler=lambda args: uia.set_value(args["hwnd"], args["value"],
                                                               automation_id=args.get("automation_id"), name=args.get("name")),
        available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_select", description="Select one uniquely identified non-password UI Automation control.",
        parameters=_object(_control_properties(), ["hwnd"]), risk="controlled",
        handler=lambda args: uia.select(args["hwnd"], automation_id=args.get("automation_id"), name=args.get("name")),
        available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_expand_collapse", description="Expand or collapse one uniquely identified UI Automation control.",
        parameters=_object({**_control_properties(), "expanded": {"type": "boolean"}}, ["hwnd", "expanded"]),
        risk="controlled", handler=lambda args: uia.expand_collapse(args["hwnd"], args["expanded"],
                    automation_id=args.get("automation_id"), name=args.get("name")), available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_scroll_container", description="Scroll a specific semantic UI Automation container.",
        parameters=_object({**_control_properties(), "axis": {"type": "string", "enum": ["horizontal", "vertical"]},
                            "direction": {"type": "string", "enum": ["forward", "backward"]}},
                           ["hwnd", "axis", "direction"]), risk="controlled",
        handler=lambda args: uia.scroll_container(args["hwnd"], args["axis"], args["direction"],
                    automation_id=args.get("automation_id"), name=args.get("name")), available=uia.provider_available))
    registry.register(ToolDefinition(
        name="apex_uia_toggle", description="Toggle one uniquely identified non-password UI Automation control.",
        parameters=_object(_control_properties(), ["hwnd"]), risk="controlled",
        handler=lambda args: uia.toggle(args["hwnd"], automation_id=args.get("automation_id"), name=args.get("name")), available=uia.provider_available))
    return registry
