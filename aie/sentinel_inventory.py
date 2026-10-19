"""Periodic, read-only Windows system inventory for Sentinel."""
from __future__ import annotations

from typing import Any

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import WindowsProvider, host_id


def _bounded_records(
    values: object,
    *,
    limit: int,
    fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(values, list):
        return [], 0
    records: list[dict[str, Any]] = []
    for value in values[:limit]:
        if not isinstance(value, dict):
            continue
        records.append({key: value.get(key) for key in fields if value.get(key) is not None})
    return records, max(0, len(values) - len(records))


def collect_system_inventory() -> AIEEvent:
    """Collect bounded application, service, task and process metadata."""
    inventory = WindowsProvider().inventory()
    processes, processes_truncated = _bounded_records(
        inventory.get("processes"),
        limit=512,
        fields=("pid", "name", "create_time"),
    )
    applications, applications_truncated = _bounded_records(
        inventory.get("applications"),
        limit=1500,
        fields=("name", "version", "publisher"),
    )
    services, services_truncated = _bounded_records(
        inventory.get("services"),
        limit=1500,
        fields=("name", "display_name", "status", "start_type"),
    )
    scheduled = inventory.get("scheduled_tasks", {})
    tasks, tasks_truncated = _bounded_records(
        scheduled.get("tasks") if isinstance(scheduled, dict) else None,
        limit=2000,
        fields=("task_name", "next_run", "status"),
    )
    interfaces, interfaces_truncated = _bounded_records(
        inventory.get("network_interfaces"),
        limit=128,
        fields=("name", "is_up", "speed_mbps", "mtu", "duplex"),
    )

    data = {
        "host": inventory.get("host"),
        "platform": inventory.get("platform"),
        "cpu_logical": inventory.get("cpu_logical"),
        "cpu_physical": inventory.get("cpu_physical"),
        "memory_total_bytes": (
            inventory.get("memory", {}).get("total")
            if isinstance(inventory.get("memory"), dict)
            else None
        ),
        "process_count": inventory.get("process_count", len(processes)),
        "processes": processes,
        "installed_application_count": len(inventory.get("applications", []))
        if isinstance(inventory.get("applications"), list) else 0,
        "installed_applications": applications,
        "service_count": len(inventory.get("services", []))
        if isinstance(inventory.get("services"), list) else 0,
        "services": services,
        "scheduled_task_count": len(tasks),
        "scheduled_tasks_available": bool(
            scheduled.get("available")
        ) if isinstance(scheduled, dict) else False,
        "scheduled_tasks": tasks,
        "network_interfaces": interfaces,
        "truncated": {
            "processes": processes_truncated,
            "applications": applications_truncated,
            "services": services_truncated,
            "scheduled_tasks": tasks_truncated,
            "network_interfaces": interfaces_truncated,
        },
        "privacy": {
            "command_lines_collected": False,
            "executable_paths_collected": False,
            "environment_variables_collected": False,
            "ip_and_mac_addresses_collected": False,
            "uninstall_commands_collected": False,
            "scheduled_task_xml_collected": False,
        },
    }
    return AIEEvent(
        host_id=host_id(),
        source="windows.inventory",
        event_type="windows.system_inventory",
        entity=EntityRef(type="windows_host", name=str(inventory.get("host") or "local-host")),
        data=data,
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    )
