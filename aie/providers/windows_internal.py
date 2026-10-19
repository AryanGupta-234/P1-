"""Deeper read-only Windows CIM inventory, bounded to diagnostic metadata."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


# Static PowerShell. No caller text or configuration is interpolated into commands.
_CIM_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$progressPreference = 'SilentlyContinue'
function Safe-Query([scriptblock]$block) {
    try { & $block } catch { $null }
}
$result = [ordered]@{}
$result.os = Safe-Query { Get-CimInstance -ClassName Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber, OSArchitecture, LastBootUpTime,
                  FreePhysicalMemory, TotalVisibleMemorySize }
$result.computer = Safe-Query { Get-CimInstance -ClassName Win32_ComputerSystem |
    Select-Object Manufacturer, Model, NumberOfProcessors,
                  NumberOfLogicalProcessors, TotalPhysicalMemory, HypervisorPresent }
$result.processors = Safe-Query { Get-CimInstance -ClassName Win32_Processor |
    Select-Object -First 8 Name, Manufacturer, NumberOfCores,
                  NumberOfLogicalProcessors, MaxClockSpeed }
$result.system_drivers = Safe-Query { Get-CimInstance -ClassName Win32_SystemDriver |
    Select-Object -First 700 Name, DisplayName, State, Started, StartMode, ServiceType }
$result.signed_drivers = Safe-Query { Get-CimInstance -ClassName Win32_PnPSignedDriver |
    Select-Object -First 350 DeviceName, DriverProviderName, DriverVersion,
                  IsSigned, DriverDate, InfName }
$result.disks = Safe-Query { Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType=3' |
    Select-Object -First 32 DeviceID, FileSystem, Size, FreeSpace }
$result.defender = Safe-Query { Get-MpComputerStatus |
    Select-Object AMServiceEnabled, AntivirusEnabled, RealTimeProtectionEnabled,
                  BehaviorMonitorEnabled, IoavProtectionEnabled, NISEnabled,
                  AntivirusSignatureVersion, AMProductVersion }
$result.firewall = Safe-Query { Get-NetFirewallProfile |
    Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction,
                  AllowInboundRules, AllowLocalFirewallRules }
$result.pnp_status = Safe-Query {
    $items = @(Get-PnpDevice -PresentOnly -ErrorAction Stop)
    $groups = $items | Group-Object -Property Status | ForEach-Object {
        [pscustomobject]@{ status = [string]$_.Name; count = [int]$_.Count }
    }
    [pscustomobject]@{ present_device_count = [int]$items.Count; status_counts = @($groups) }
}
$result.physical_disks = Safe-Query { Get-PhysicalDisk |
    Select-Object -First 32 FriendlyName, MediaType, BusType, HealthStatus,
                  OperationalStatus, Size }
$result.bitlocker = Safe-Query { Get-BitLockerVolume |
    Select-Object -First 32 MountPoint, VolumeStatus, ProtectionStatus,
                  EncryptionPercentage, EncryptionMethod }
$result.batteries = Safe-Query { Get-CimInstance -ClassName Win32_Battery |
    Select-Object -First 8 Name, BatteryStatus, EstimatedChargeRemaining,
                  EstimatedRunTime, Status, Chemistry }
$result | ConvertTo-Json -Depth 6 -Compress
"""


def _run_cim_snapshot(timeout_seconds: int = 45) -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("Windows CIM inventory requires native Windows.")
    executable = os.path.join(
        os.environ.get("WINDIR", r"C:\Windows"),
        "System32",
        "WindowsPowerShell",
        "v1.0",
        "powershell.exe",
    )
    completed = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _CIM_SCRIPT,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError("Windows CIM query failed.")
    if len(completed.stdout.encode("utf-8", errors="replace")) > 2_000_000:
        raise ValueError("Windows CIM response exceeded its size budget.")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Windows CIM returned malformed JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Windows CIM returned an invalid object.")
    return payload


def _as_objects(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    output: list[dict[str, Any]] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            output.append(item)
    return output


def _pick(
    item: dict[str, Any],
    fields: tuple[str, ...],
    *,
    string_limit: int = 180,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = item.get(field)
        if value is None or isinstance(value, (dict, list)):
            continue
        if isinstance(value, bool):
            result[field] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if 0 <= value < 2**63:
                result[field] = value
        elif isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                result[field] = cleaned[:string_limit]
    return result


def _clean_section(payload: dict[str, Any], section: str, fields: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
    return [_pick(item, fields) for item in _as_objects(payload.get(section), limit=limit)]


def collect_windows_deep_inventory() -> AIEEvent:
    """Return an evidence event with OS, driver, disk, security and PnP metadata."""
    raw = _run_cim_snapshot()
    os_info = _pick(
        next(iter(_as_objects(raw.get("os"), limit=1)), {}),
        (
            "Caption", "Version", "BuildNumber", "OSArchitecture", "LastBootUpTime",
            "FreePhysicalMemory", "TotalVisibleMemorySize",
        ),
    )
    computer = _pick(
        next(iter(_as_objects(raw.get("computer"), limit=1)), {}),
        (
            "Manufacturer", "Model", "NumberOfProcessors",
            "NumberOfLogicalProcessors", "TotalPhysicalMemory", "HypervisorPresent",
        ),
    )
    processors = _clean_section(
        raw, "processors",
        ("Name", "Manufacturer", "NumberOfCores", "NumberOfLogicalProcessors", "MaxClockSpeed"),
        8,
    )
    drivers = _clean_section(
        raw, "system_drivers",
        ("Name", "DisplayName", "State", "Started", "StartMode", "ServiceType"),
        700,
    )
    signed_drivers = _clean_section(
        raw, "signed_drivers",
        ("DeviceName", "DriverProviderName", "DriverVersion", "IsSigned", "DriverDate", "InfName"),
        350,
    )
    disks = _clean_section(
        raw, "disks",
        ("DeviceID", "FileSystem", "Size", "FreeSpace"),
        32,
    )
    defender = _pick(
        next(iter(_as_objects(raw.get("defender"), limit=1)), {}),
        (
            "AMServiceEnabled", "AntivirusEnabled", "RealTimeProtectionEnabled",
            "BehaviorMonitorEnabled", "IoavProtectionEnabled", "NISEnabled",
            "AntivirusSignatureVersion", "AMProductVersion",
        ),
    )
    firewall = _clean_section(
        raw, "firewall",
        ("Name", "Enabled", "DefaultInboundAction", "DefaultOutboundAction",
         "AllowInboundRules", "AllowLocalFirewallRules"),
        8,
    )
    pnp = next(iter(_as_objects(raw.get("pnp_status"), limit=1)), {})
    pnp_status_counts = _clean_section(
        pnp, "status_counts", ("status", "count"), 16
    )
    physical_disks = _clean_section(
        raw, "physical_disks",
        ("FriendlyName", "MediaType", "BusType", "HealthStatus", "OperationalStatus", "Size"),
        32,
    )
    bitlocker = _clean_section(
        raw, "bitlocker",
        ("MountPoint", "VolumeStatus", "ProtectionStatus", "EncryptionPercentage", "EncryptionMethod"),
        32,
    )
    batteries = _clean_section(
        raw, "batteries",
        ("Name", "BatteryStatus", "EstimatedChargeRemaining", "EstimatedRunTime", "Status", "Chemistry"),
        8,
    )

    data = {
        "operating_system": os_info,
        "computer": computer,
        "processors": processors,
        "system_driver_count": len(drivers),
        "system_drivers": drivers,
        "signed_pnp_driver_count": len(signed_drivers),
        "signed_pnp_drivers": signed_drivers,
        "fixed_disks": disks,
        "defender_status": defender,
        "firewall_profiles": firewall,
        "pnp_device_count": pnp.get("present_device_count"),
        "pnp_status_counts": pnp_status_counts,
        "physical_disks": physical_disks,
        "bitlocker_volumes": bitlocker,
        "batteries": batteries,
        "scope": {
            "wmi_classes": [
                "Win32_OperatingSystem", "Win32_ComputerSystem", "Win32_Processor",
                "Win32_SystemDriver", "Win32_PnPSignedDriver", "Win32_LogicalDisk",
            ],
            "additional_surfaces": [
                "Microsoft Defender status", "Windows Firewall profile status",
                "present PnP device status counts",
                "physical disk health metadata (where the Storage module is available)",
                "BitLocker volume encryption status (where the module is available; no recovery keys)",
                "battery charge/status metadata",
            ],
            "command_lines_collected": False,
            "executable_paths_collected": False,
            "serial_numbers_collected": False,
            "device_instance_ids_collected": False,
            "event_log_messages_collected": False,
            "credentials_or_protected_memory_collected": False,
            "system_configuration_modified": False,
        },
    }
    return AIEEvent(
        timestamp=datetime.now(timezone.utc),
        host_id=host_id(),
        source="windows.cim.deep_inventory",
        event_type="windows.deep_inventory",
        entity=EntityRef(type="windows_host", name="local_windows_system"),
        data=data,
        sensitivity="internal",
        confidence=1.0,
        evidence_kind="observed",
    )
