"""Bounded, read-only Windows UI Automation inspection.

Only structural control metadata is returned. Control names, text, values,
password contents, screenshots and UI patterns are intentionally excluded.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


MAX_WINDOWS = 40
MAX_NODES = 1000
MAX_DEPTH = 8
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class UIAInspection:
    available: bool
    reason: str | None
    windows: list[dict[str, Any]]
    nodes_inspected: int
    truncated: bool


def _powershell_script(max_windows: int, max_nodes: int, max_depth: int) -> str:
    # Do not add Current.Name, ValuePattern, TextPattern, screenshots or actions here.
    return r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$windows = New-Object System.Collections.Generic.List[object]
$script:nodeCount = 0
$script:truncated = $false
$maxWindows = __MAX_WINDOWS__
$maxNodes = __MAX_NODES__
$maxDepth = __MAX_DEPTH__

function Get-ControlRecord($element, $depth) {
    $current = $element.Current
    $rect = $current.BoundingRectangle
    $processName = $null
    if ($depth -eq 0 -and $current.ProcessId -gt 0) {
        try { $processName = (Get-Process -Id $current.ProcessId -ErrorAction Stop).ProcessName }
        catch { $processName = $null }
    }
    return @{
        depth = $depth
        process_id = $(if ($depth -eq 0) { $current.ProcessId } else { $null })
        process_name = $processName
        control_type = $current.ControlType.ProgrammaticName
        automation_id = $current.AutomationId
        class_name = $current.ClassName
        framework_id = $current.FrameworkId
        enabled = $current.IsEnabled
        offscreen = $current.IsOffscreen
        password_control = $current.IsPassword
        bounds = @{
            x = [math]::Round($rect.X, 1)
            y = [math]::Round($rect.Y, 1)
            width = [math]::Round($rect.Width, 1)
            height = [math]::Round($rect.Height, 1)
        }
    }
}

function Visit-Children($parent, $depth, $records) {
    if ($depth -ge $maxDepth -or $script:nodeCount -ge $maxNodes) {
        $script:truncated = $true
        return
    }
    try { $child = $walker.GetFirstChild($parent) } catch { return }
    while ($null -ne $child) {
        if ($script:nodeCount -ge $maxNodes) {
            $script:truncated = $true
            return
        }
        try {
            $record = Get-ControlRecord $child $depth
            $records.Add($record)
            $script:nodeCount++
            Visit-Children $child ($depth + 1) $records
            $next = $walker.GetNextSibling($child)
            $child = $next
        } catch {
            try { $child = $walker.GetNextSibling($child) } catch { break }
        }
    }
}

try { $top = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition) }
catch { throw "UIA root enumeration failed: $($_.Exception.GetType().Name)" }

$windowCount = [math]::Min($top.Count, $maxWindows)
for ($i = 0; $i -lt $windowCount; $i++) {
    if ($script:nodeCount -ge $maxNodes) { $script:truncated = $true; break }
    try {
        $records = New-Object System.Collections.Generic.List[object]
        $window = $top.Item($i)
        $records.Add((Get-ControlRecord $window 0))
        $script:nodeCount++
        Visit-Children $window 1 $records
        $windows.Add(@{ controls = @($records.ToArray()) })
    } catch { continue }
}
if ($top.Count -gt $maxWindows) { $script:truncated = $true }
@{
    schema_version = 1
    mode = 'read_only_structure'
    text_values_collected = $false
    password_values_collected = $false
    windows = @($windows.ToArray())
    nodes_inspected = $script:nodeCount
    truncated = $script:truncated
} | ConvertTo-Json -Depth 8 -Compress
""".replace("__MAX_WINDOWS__", str(max_windows)).replace(
        "__MAX_NODES__", str(max_nodes)
    ).replace("__MAX_DEPTH__", str(max_depth))


def inspect_windows(
    *,
    max_windows: int = 12,
    max_nodes: int = 250,
    max_depth: int = 5,
    timeout: float = 12.0,
) -> UIAInspection:
    """Inspect visible Windows control structure with strict resource bounds."""
    if os.name != "nt":
        return UIAInspection(False, "native_windows_required", [], 0, False)
    if isinstance(max_windows, bool) or not 1 <= max_windows <= MAX_WINDOWS:
        raise ValueError(f"max_windows must be between 1 and {MAX_WINDOWS}")
    if isinstance(max_nodes, bool) or not 1 <= max_nodes <= MAX_NODES:
        raise ValueError(f"max_nodes must be between 1 and {MAX_NODES}")
    if isinstance(max_depth, bool) or not 1 <= max_depth <= MAX_DEPTH:
        raise ValueError(f"max_depth must be between 1 and {MAX_DEPTH}")
    if isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout must be between 1 and {MAX_TIMEOUT_SECONDS} seconds")

    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        return UIAInspection(False, "powershell_not_found", [], 0, False)
    script = _powershell_script(max_windows, max_nodes, max_depth)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        completed = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return UIAInspection(False, "inspection_timeout", [], 0, True)
    except OSError as exc:
        return UIAInspection(False, type(exc).__name__, [], 0, False)

    output = completed.stdout.strip()
    if completed.returncode != 0:
        return UIAInspection(False, "uia_query_failed", [], 0, False)
    if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
        return UIAInspection(False, "uia_output_limit_exceeded", [], 0, True)
    try:
        payload = json.loads(output)
        if payload.get("schema_version") != 1 or payload.get("mode") != "read_only_structure":
            raise ValueError("unexpected UIA response schema")
        windows = payload.get("windows")
        if not isinstance(windows, list) or len(windows) > max_windows:
            raise ValueError("invalid UIA window collection")
        nodes = payload.get("nodes_inspected")
        if isinstance(nodes, bool) or not isinstance(nodes, int) or not 0 <= nodes <= max_nodes:
            raise ValueError("invalid UIA node count")
        return UIAInspection(
            True, None, windows, nodes, bool(payload.get("truncated", False))
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return UIAInspection(False, "invalid_uia_response", [], 0, False)
