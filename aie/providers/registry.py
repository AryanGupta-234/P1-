"""Read-only, allowlisted Windows registry intelligence.

The provider intentionally does not walk entire hives. It reads a small set of
configuration locations and service-registration metadata with KEY_READ access,
never reads secret-bearing SAM/SECURITY/LSA credential stores, and emits only
sanitized values or change summaries.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from aie.contracts import AIEEvent, EntityRef
from aie.providers.windows import host_id


_SAFE_VALUE_TARGETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "HKLM",
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        (
            "ProductName", "DisplayVersion", "CurrentBuild", "CurrentBuildNumber",
            "UBR", "EditionID", "InstallationType", "CurrentMajorVersionNumber",
            "CurrentMinorVersionNumber",
        ),
    ),
    (
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard",
        ("EnableVirtualizationBasedSecurity", "RequirePlatformSecurityFeatures", "Locked"),
    ),
    (
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
        ("Enabled", "WasEnabledBy"),
    ),
    (
        "HKLM",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
        (
            "EnableLUA", "ConsentPromptBehaviorAdmin", "PromptOnSecureDesktop",
            "EnableInstallerDetection", "ValidateAdminCodeSignatures",
        ),
    ),
    (
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
        ("UEFISecureBootEnabled", "SetupMode"),
    ),
    (
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\CrashControl",
        ("CrashDumpEnabled", "AutoReboot", "LogEvent", "Overwrite"),
    ),
    (
        "HKLM",
        r"SOFTWARE\Policies\Microsoft\Windows Defender",
        ("DisableAntiSpyware", "PUAProtection", "ServiceKeepAlive"),
    ),
    (
        "HKLM",
        r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection",
        (
            "DisableRealtimeMonitoring", "DisableBehaviorMonitoring",
            "DisableIOAVProtection", "DisableOnAccessProtection",
        ),
    ),
    (
        "HKLM",
        r"SYSTEM\CurrentControlSet\Control\Terminal Server",
        ("fDenyTSConnections", "fSingleSessionPerUser", "fAllowToGetHelp"),
    ),
)

_RUN_TARGETS: tuple[tuple[str, str], ...] = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
)
_EXECUTABLE_BASENAME = re.compile(r"(?i)([A-Za-z0-9_.+-]{1,120}\.(?:exe|sys|dll|com))")


def _safe_scalar(value: Any, value_name: str) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if 0 <= value <= 2**63 - 1 else None
    if isinstance(value, float):
        return value if 0 <= value < 1e18 else None
    if isinstance(value, str):
        if value_name.casefold() in {"productname", "displayversion", "editionid", "installationtype"}:
            return value.strip()[:160]
        if value_name.casefold() in {"currentbuild", "currentbuildnumber"}:
            return value.strip()[:32]
        return value.strip()[:80]
    return None


def _safe_image_basename(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _EXECUTABLE_BASENAME.search(value[:2048])
    return match.group(1).casefold() if match else None


class WindowsRegistryProvider:
    """Emit a baseline and subsequent changes for selected Windows configuration keys."""

    name = "windows.registry"

    def __init__(self, *, max_services: int = 700, max_autoruns_per_key: int = 128) -> None:
        if os.name != "nt":
            raise OSError("Windows registry observation requires native Windows.")
        if not 64 <= max_services <= 1500:
            raise ValueError("max_services must be between 64 and 1500")
        if not 16 <= max_autoruns_per_key <= 512:
            raise ValueError("max_autoruns_per_key must be between 16 and 512")
        self.max_services = max_services
        self.max_autoruns_per_key = max_autoruns_per_key
        self._last_fingerprints: dict[str, str] | None = None
        self._last_section_data: dict[str, dict[str, Any]] | None = None

    @staticmethod
    def _root(winreg: Any, hive_name: str) -> Any:
        return winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM" else winreg.HKEY_CURRENT_USER

    @staticmethod
    def _open(winreg: Any, hive_name: str, path: str) -> Any:
        root = WindowsRegistryProvider._root(winreg, hive_name)
        access = winreg.KEY_READ
        if hive_name == "HKLM":
            access |= getattr(winreg, "KEY_WOW64_64KEY", 0)
        return winreg.OpenKey(root, path, 0, access)

    def _read_policy_values(self, winreg: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for hive, path, names in _SAFE_VALUE_TARGETS:
            key_name = f"{hive}\\{path}"
            values: dict[str, Any] = {}
            try:
                with self._open(winreg, hive, path) as key:
                    for name in names:
                        try:
                            raw, _kind = winreg.QueryValueEx(key, name)
                        except OSError:
                            continue
                        value = _safe_scalar(raw, name)
                        if value is not None:
                            values[name] = value
            except OSError:
                continue
            if values:
                result[key_name] = values
        return result

    def _read_service_catalog(self, winreg: Any) -> dict[str, Any]:
        path = r"SYSTEM\CurrentControlSet\Services"
        services: list[dict[str, Any]] = []
        driver_count = 0
        truncated = False
        try:
            with self._open(winreg, "HKLM", path) as root:
                index = 0
                while len(services) < self.max_services:
                    try:
                        service_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    if not isinstance(service_name, str) or not service_name:
                        continue
                    try:
                        with self._open(winreg, "HKLM", path + "\\" + service_name) as key:
                            values: dict[str, Any] = {}
                            for value_name in ("Start", "Type", "ErrorControl", "ImagePath"):
                                try:
                                    raw, _kind = winreg.QueryValueEx(key, value_name)
                                except OSError:
                                    continue
                                if value_name == "ImagePath":
                                    basename = _safe_image_basename(raw)
                                    if basename:
                                        values["image_basename"] = basename
                                elif isinstance(raw, int) and not isinstance(raw, bool):
                                    values[value_name.casefold()] = int(raw)
                            services.append({
                                "name": service_name[:120],
                                **values,
                            })
                            service_type = values.get("type")
                            if isinstance(service_type, int) and service_type & 0x1:
                                driver_count += 1
                    except OSError:
                        continue
                try:
                    truncated = winreg.QueryInfoKey(root)[0] > len(services)
                except OSError:
                    pass
        except OSError:
            pass
        services.sort(key=lambda item: str(item["name"]).casefold())
        return {
            "service_registry_count_sampled": len(services),
            "driver_service_count_sampled": driver_count,
            "services_truncated": truncated,
            "services": services,
        }

    def _read_autoruns(self, winreg: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for hive, path in _RUN_TARGETS:
            key_name = f"{hive}\\{path}"
            names: list[str] = []
            fingerprints: list[str] = []
            truncated = False
            try:
                with self._open(winreg, hive, path) as key:
                    index = 0
                    while index < self.max_autoruns_per_key:
                        try:
                            name, value, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        if not isinstance(name, str):
                            continue
                        safe_name = name.strip()[:120]
                        if not safe_name:
                            continue
                        names.append(safe_name)
                        # The command is hashed only in memory to detect modifications.
                        # Neither its text nor hash is persisted or sent to a model.
                        raw = value if isinstance(value, str) else repr(type(value).__name__)
                        fingerprints.append(hashlib.sha256(str(raw).encode("utf-8", errors="replace")).hexdigest())
                    try:
                        truncated = winreg.QueryInfoKey(key)[1] > self.max_autoruns_per_key
                    except OSError:
                        pass
            except OSError:
                continue
            result[key_name] = {
                "entry_count_sampled": len(names),
                "entry_names": sorted(names, key=str.casefold),
                "truncated": truncated,
            }
            result[f"{key_name}#fingerprint"] = {
                "fingerprints": sorted(fingerprints),
            }
        return result

    def _snapshot(self) -> dict[str, Any]:
        import winreg

        policy = self._read_policy_values(winreg)
        services = self._read_service_catalog(winreg)
        autoruns = self._read_autoruns(winreg)
        autorun_fingerprints = {
            key: value
            for key, value in autoruns.items()
            if key.endswith("#fingerprint")
        }
        autorun_entries = {
            key: value
            for key, value in autoruns.items()
            if not key.endswith("#fingerprint")
        }
        return {
            "policy_values": policy,
            "service_catalog": services,
            "autorun_entries": autorun_entries,
            "autorun_fingerprints_memory_only": autorun_fingerprints,
            "privacy": {
                "access_mode": "KEY_READ",
                "secret_hives_read": False,
                "command_values_persisted": False,
                "full_binary_paths_persisted": False,
                "registry_writes_performed": False,
            },
        }

    @staticmethod
    def _section_fingerprints(snapshot: dict[str, Any]) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        for section in ("policy_values", "service_catalog", "autorun_entries"):
            value = snapshot[section]
            if section == "autorun_entries":
                value = {
                    key: snapshot["autorun_fingerprints_memory_only"].get(
                        f"{key}#fingerprint", {}
                    )
                    for key in value
                }
            encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            fingerprints[section] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return fingerprints

    def collect_snapshot(self) -> list[AIEEvent]:
        snapshot = self._snapshot()
        fingerprints = self._section_fingerprints(snapshot)
        previous = self._last_fingerprints
        self._last_fingerprints = fingerprints

        safe_snapshot = {
            "policy_values": snapshot["policy_values"],
            "service_catalog": snapshot["service_catalog"],
            "autorun_entries": snapshot["autorun_entries"],
            "privacy": snapshot["privacy"],
        }
        if previous is None:
            event_type = "registry.baseline"
            changed_sections = list(fingerprints)
        else:
            changed_sections = [
                name for name, fingerprint in fingerprints.items()
                if previous.get(name) != fingerprint
            ]
            if not changed_sections:
                return []
            event_type = "registry.configuration_changed"

        if previous is not None and self._last_section_data is not None:
            old_services = {
                str(item.get("name"))
                for item in self._last_section_data.get("service_catalog", {}).get("services", [])
            }
            new_services = {
                str(item.get("name"))
                for item in safe_snapshot.get("service_catalog", {}).get("services", [])
            }
            old_autoruns = {
                key: set(value.get("entry_names", []))
                for key, value in self._last_section_data.get("autorun_entries", {}).items()
            }
            new_autoruns = {
                key: set(value.get("entry_names", []))
                for key, value in safe_snapshot.get("autorun_entries", {}).items()
            }
            change_summary: dict[str, Any] = {
                "services_added": sorted(new_services - old_services)[:50],
                "services_removed": sorted(old_services - new_services)[:50],
                "autorun_name_changes": {},
            }
            for key in set(old_autoruns) | set(new_autoruns):
                added = new_autoruns.get(key, set()) - old_autoruns.get(key, set())
                removed = old_autoruns.get(key, set()) - new_autoruns.get(key, set())
                if added or removed:
                    change_summary["autorun_name_changes"][key] = {
                        "added": sorted(added)[:32],
                        "removed": sorted(removed)[:32],
                    }
        else:
            change_summary = {"baseline": True}

        self._last_section_data = safe_snapshot
        services_data = safe_snapshot.get("service_catalog", {})
        autorun_data = safe_snapshot.get("autorun_entries", {})
        return [AIEEvent(
            timestamp=datetime.now(timezone.utc),
            host_id=host_id(),
            source=self.name,
            event_type=event_type,
            entity=EntityRef(type="registry_configuration", name="allowlisted_windows_configuration"),
            data={
                "changed_sections": changed_sections,
                "change_summary": change_summary,
                "policy_values": safe_snapshot["policy_values"],
                "service_catalog": {
                    "service_registry_count_sampled": services_data.get("service_registry_count_sampled", 0),
                    "driver_service_count_sampled": services_data.get("driver_service_count_sampled", 0),
                    "services_truncated": services_data.get("services_truncated", False),
                    "services": services_data.get("services", []),
                },
                "autorun_entries": autorun_data,
                "privacy": safe_snapshot["privacy"],
            },
            sensitivity="internal",
            confidence=1.0,
            evidence_kind="observed",
        )]
