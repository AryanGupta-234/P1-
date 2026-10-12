[CmdletBinding()]
param(
    [ValidateSet('Chrome', 'Edge', 'Brave')]
    [string[]]$Browser = @('Chrome', 'Edge', 'Brave'),

    [switch]$RequireBrowserRegistration
)

$ErrorActionPreference = 'Stop'
$results = [System.Collections.Generic.List[object]]::new()
$repoRoot = Split-Path -Parent $PSScriptRoot

# Read-only browser/video preflight: no registry, browser, security or execution changes.
function Add-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail
    )
    $results.Add([pscustomobject]@{
        Name = $Name
        Passed = $Passed
        Detail = $Detail
    })
}

Add-Check 'Windows' ($env:OS -eq 'Windows_NT') 'Windows host required.'

try {
    $python = python --version 2>&1
    Add-Check 'Python' ($LASTEXITCODE -eq 0) ([string]$python)
} catch {
    Add-Check 'Python' $false 'python executable not available on PATH.'
}

try {
    python -c "import aie; from aie.browser.native_host import event_from_browser_payload; from aie.diagnostics.video_probe import run_video_network_probe; from aie.diagnostics.video_evaluation import evaluate_trace_dataset; from aie.diagnostics.video_field_export import prepare_field_trace_candidates"
    Add-Check 'Browser/video imports' ($LASTEXITCODE -eq 0) 'Native host, bounded network probes, trace evaluation and sanitized field export imported successfully.'
} catch {
    Add-Check 'Browser/video imports' $false 'One or more required browser/video modules failed to import.'
}

try {
    $traceDataset = Join-Path $PSScriptRoot '..\aie\diagnostics\data\video_traces_v1.json'
    $evaluation = python -c "import sys; from pathlib import Path; from aie.diagnostics.video_evaluation import evaluate_trace_dataset; report=evaluate_trace_dataset(Path(sys.argv[1])); assert report.trace_count > 0; print(str(report.trace_count) + ' synthetic traces loaded')" $traceDataset 2>&1
    Add-Check 'Video trace corpus' ($LASTEXITCODE -eq 0) ([string]$evaluation)
} catch {
    Add-Check 'Video trace corpus' $false 'Synthetic video trace corpus could not be loaded.'
}

$artifacts = @(
    'browser_extension\manifest.json',
    'browser_extension\content.js',
    'browser_extension\service_worker.js',
    'browser_extension\popup.html',
    'browser_extension\popup.js',
    'scripts\register-native-host.ps1',
    'scripts\unregister-native-host.ps1'
)
foreach ($relative in $artifacts) {
    $artifactPath = Join-Path $repoRoot $relative
    Add-Check ('Artifact: ' + $relative) (Test-Path -LiteralPath $artifactPath) 'Expected repository artifact exists.'
}

foreach ($selectedBrowser in $Browser) {
    $registryRoot = switch ($selectedBrowser) {
        'Chrome' { 'HKCU:\Software\Google\Chrome\NativeMessagingHosts' }
        'Edge'   { 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts' }
        'Brave'  { 'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts' }
    }

    $registryKey = Join-Path $registryRoot 'com.aie.browser_bridge'
    $registrationValid = $false
    $detail = ('Not registered. Load the unpacked extension in {0}, then run scripts/register-native-host.ps1 -Browser {0}.' -f $selectedBrowser)

    if (Test-Path -LiteralPath $registryKey) {
        try {
            $key = Get-Item -LiteralPath $registryKey
            $manifestPath = [string]$key.GetValue('')
            if ($manifestPath -and (Test-Path -LiteralPath $manifestPath)) {
                $hostManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
                $hostPath = [string]$hostManifest.path
                $originValid = [bool](@($hostManifest.allowed_origins) -match '^chrome-extension://[a-p]{32}/$')
                $registrationValid = (
                    $hostManifest.name -eq 'com.aie.browser_bridge' -and
                    $hostManifest.type -eq 'stdio' -and
                    $originValid -and
                    $hostPath -and
                    (Test-Path -LiteralPath $hostPath)
                )
                if ($registrationValid) {
                    $detail = 'Native host manifest, extension origin and executable are present.'
                    $probe = @'
import json
import struct
import subprocess
import sys

payload = json.dumps({"kind": "bridge_ping"}, separators=(",", ":")).encode("utf-8")
frame = struct.pack("<I", len(payload)) + payload
try:
    result = subprocess.run(
        [sys.argv[1]], input=frame, capture_output=True, timeout=8, check=False
    )
    if result.returncode != 0:
        raise SystemExit("host exited with code " + str(result.returncode))
    if len(result.stdout) < 4:
        raise SystemExit("host returned no framed response")
    size = struct.unpack("<I", result.stdout[:4])[0]
    if size == 0 or size > 1024 * 1024 or len(result.stdout) != size + 4:
        raise SystemExit("host returned an invalid response frame")
    response = json.loads(result.stdout[4:].decode("utf-8"))
    if response != {"ok": True, "kind": "bridge_pong"}:
        raise SystemExit("unexpected host response: " + repr(response))
    print("Native host launch and PING/PONG handshake passed.")
except subprocess.TimeoutExpired:
    raise SystemExit("native host handshake timed out")
'@
                    $probeResult = python -c $probe $hostPath 2>&1
                    $probePassed = ($LASTEXITCODE -eq 0)
                    if ($probePassed) {
                        $detail += ' ' + [string]$probeResult
                    } else {
                        $registrationValid = $false
                        $detail = 'Native host is registered but launch/handshake failed: ' + [string]$probeResult
                    }
                } else {
                    $detail = 'Native host manifest or executable is incomplete; re-register this browser.'
                }
            } else {
                $detail = 'Registry entry exists but its browser-specific manifest is missing.'
            }
        } catch {
            $detail = 'Browser native host registration could not be read safely.'
        }
    }

    $passed = $registrationValid -or -not $RequireBrowserRegistration
    Add-Check ('Native host: ' + $selectedBrowser) $passed $detail
}

try {
    $importTest = python -c "from aie.policy.execution_control import ExecutionControl; from aie.config import execution_enabled_path, execution_kill_switch_path; control=ExecutionControl(enabled_path=execution_enabled_path(), kill_switch_path=execution_kill_switch_path()); state=control.status(); print('enabled=' + str(state.enabled).lower() + ' kill_switch=' + str(state.kill_switch_active).lower())" 2>&1
    Add-Check 'Execution gate' ($LASTEXITCODE -eq 0) ([string]$importTest)
} catch {
    Add-Check 'Execution gate' $false 'Execution control contract could not be inspected.'
}

$failed = @($results | Where-Object { -not $_.Passed })

Write-Host ''
Write-Host 'AIE BROWSER/VIDEO TARGET DESKTOP VALIDATION' -ForegroundColor Cyan
Write-Host 'Performs a framed PING/PONG process test; does not change registry, browser or execution settings.' -ForegroundColor DarkGray
Write-Host ''
$results | Format-Table -AutoSize

if ($failed.Count -gt 0) {
    Write-Host ('Validation failed: ' + $failed.Count + ' check(s).') -ForegroundColor Red
    exit 1
}

Write-Host 'All target-desktop checks passed.' -ForegroundColor Green
exit 0
