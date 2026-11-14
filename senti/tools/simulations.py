"""Dry-run previews for SENTI's common state-changing capabilities.

Each simulator reads the *current* state through the same read-only provider APIs and
describes the intended change, so the approval card shows "current -> intended" and how
to recover. Simulators never call a setter.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from senti.tools.registry import CapabilityRegistry
from senti.windows import audio, bluetooth, display, network, power, services, wireless


def _safe(read: Callable[[], Any]) -> Any:
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - a preview must never fail the request
        return {"unavailable": type(exc).__name__}


def _volume(args: dict) -> dict:
    current = _safe(audio.get_master_volume)
    return {"current_state": current, "intended_state": {"volume_percent": args["volume_percent"]},
            "effect": f"Sets the master output volume to {args['volume_percent']}%.",
            "recovery": "Set the previous volume again."}


def _mute(args: dict) -> dict:
    current = _safe(audio.get_master_volume)
    return {"current_state": current, "intended_state": {"muted": args["muted"]},
            "effect": ("Mutes" if args["muted"] else "Unmutes") + " the master output.",
            "recovery": "Toggle mute back."}


def _brightness(args: dict) -> dict:
    return {"current_state": _safe(display.get_brightness), "intended_state": {"percent": args["percent"]},
            "effect": f"Sets display brightness to {args['percent']}%.",
            "recovery": "Set the previous brightness again."}


def _dns(args: dict) -> dict:
    configs = _safe(lambda: network.list_configurations(50))
    adapter = None
    if isinstance(configs, dict):
        for row in configs.get("configurations", configs.get("adapters", [])) or []:
            if isinstance(row, dict) and row.get("index", row.get("adapter_index")) == args["adapter_index"]:
                adapter = row
                break
    return {"current_state": adapter or {"adapter_index": args["adapter_index"], "found": adapter is not None},
            "intended_state": {"dns_servers": args["dns_servers"]},
            "effect": "Changes name resolution for this adapter; a wrong server can break browsing.",
            "recovery": "Previous DNS servers are captured and can be restored."}


def _power_plan(args: dict) -> dict:
    plans = _safe(power.list_power_plans)
    target = None
    if isinstance(plans, dict):
        target = next((p for p in plans.get("plans", []) if str(p.get("guid", "")).lower() == args["guid"].lower()),
                      None)
    return {"current_state": _safe(power.get_active_power_plan),
            "intended_state": target or {"guid": args["guid"], "installed": False},
            "effect": "Switches the active power plan." if target else "This plan GUID is not installed.",
            "recovery": "Re-select the previous plan GUID."}


def _service(args: dict) -> dict:
    listing = _safe(lambda: services.list_services(400))
    current = None
    if isinstance(listing, dict):
        current = next((s for s in listing.get("services", [])
                        if str(s.get("name", "")).casefold() == args["service_name"].casefold()), None)
    intended = {k: v for k, v in args.items() if k != "service_name"}
    return {"current_state": current or {"service_name": args["service_name"], "found": False},
            "intended_state": intended,
            "effect": f"Changes the Windows service '{args['service_name']}': {intended}.",
            "recovery": "Apply the previous state/start type shown above."}


def _wifi(args: dict) -> dict:
    return {"current_state": _safe(wireless.list_wireless_radios), "intended_state": {"enabled": args["enabled"]},
            "effect": "Turns the Wi-Fi radio " + ("on." if args["enabled"] else "off; Wi-Fi connections will drop."),
            "recovery": "Turn the radio back " + ("off." if args["enabled"] else "on.")}


def _bluetooth(args: dict) -> dict:
    return {"current_state": _safe(bluetooth.list_bluetooth_radios), "intended_state": {"enabled": args["enabled"]},
            "effect": "Turns Bluetooth " + ("on." if args["enabled"] else "off; connected devices disconnect."),
            "recovery": "Turn Bluetooth back " + ("off." if args["enabled"] else "on.")}


SIMULATORS: dict[str, Callable[[dict], dict]] = {
    "senti_set_master_volume": _volume,
    "senti_set_master_mute": _mute,
    "senti_set_brightness": _brightness,
    "senti_set_dns_servers": _dns,
    "senti_set_power_plan": _power_plan,
    "senti_service_control": _service,
    "senti_set_service_start_type": _service,
    "senti_set_wifi_radio": _wifi,
    "senti_set_bluetooth_radio": _bluetooth,
}


def attach_simulations(registry: CapabilityRegistry) -> int:
    """Attach previews to registered tools that do not already provide one."""
    attached = 0
    for name, simulator in SIMULATORS.items():
        tool = registry.tool(name)
        if tool is not None and tool.simulate is None:
            registry.replace(replace(tool, simulate=simulator))
            attached += 1
    return attached
