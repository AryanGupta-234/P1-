[CmdletBinding()]
param(
    [ValidateSet('Chrome', 'Edge')]
    [string[]]$Browser = @('Chrome', 'Edge'),

    [switch]$RequireBrowserRegistration
)

$ErrorActionPreference = "Stop"

# Read-only target-desktop validation for AIE. This script never changes policy,
# security protections, registry state, browser registration or Ollama models.

$results = [System.Collections.Generic.List[object]]::new()

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $results.Add([pscustomobject]@{ Name=$Name; Passed=$Passed; Detail=$Detail })
}

Add-Check "Windows" ($IsWindows -or $env:OS -eq "Windows_NT") "Windows host required."

try {
    $python = python --version 2>&1
    Add-Check "Python" ($LASTEXITCODE -eq 0) ([string]$python)
} catch { Add-Check "Python" $false "python executable not available on PATH." }

try {
    python -c "import aie; import pywinauto; import win32evtlog; from aie.providers.uia import WindowsUIATreeProvider; from aie.providers.eventlog import WindowsEventLogProvider; from aie.providers.etw_process import WindowsETWProcessProvider; from aie.providers.process_resources import WindowsProcessResourceProvider; from aie.browser.native_host import event_from_browser_payload; from aie.diagnostics.video_probe import run_video_network_probe; from aie.diagnostics.video_evaluation import evaluate_trace_dataset"
    Add-Check "Provider and video imports" ($LASTEXITCODE -eq 0) "Windows and browser/video diagnostic modules imported successfully."
} catch { Add-Check "Provider and video imports" $false "One or more Windows/browser video imports failed." }

try {
    $traceDataset = Join-Path $PSScriptRoot '..\aie\diagnostics\data\video_traces_v1.json'
    $evaluation = python -c "import sys; from pathlib import Path; from aie.diagnostics.video_evaluation import evaluate_trace_dataset; r=evaluate_trace_dataset(Path(sys.argv[1])); assert r.trace_count > 0; print(str(r.trace_count) + ' synthetic traces loaded')" $traceDataset 2>&1
    Add-Check "Video trace corpus" ($LASTEXITCODE -eq 0) ([string]$evaluation)
} catch { Add-Check "Video trace corpus" $false "Synthetic video trace corpus could not be loaded." }

try {
    $ollama = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -Method Get -TimeoutSec 3
    $names = @($ollama.models | ForEach-Object { $_.name })
    $required = @('qwen2.5:3b-instruct', 'qwen2.5:7b-instruct', 'nomic-embed-text:latest')
    $missing = @($required | Where-Object { $_ -notin $names })
    if ($missing.Count -eq 0) {
        Add-Check "Local Ollama" $true "Required local models are installed."
    } else {
        Add-Check "Local Ollama" $false ("Missing: " + ($missing -join ", "))
    }
} catch { Add-Check "Local Ollama" $false "Local Ollama endpoint was not reachable; no remote endpoint was attempted." }

$repoRoot = Split-Path -Parent $PSScriptRoot
$artifacts = @(
    "browser_extension\manifest.json",
    "browser_extension\content.js",
    "browser_extension\service_worker.js",
    "browser_extension\popup.html",
    "browser_extension\popup.js",
    "scripts\register-native-host.ps1",
    "scripts\unregister-native-host.ps1"
)
foreach ($relative in $artifacts) {
    $path = Join-Path $repoRoot $relative
    Add-Check ('Artifact: ' + $relative) (Test-Path -LiteralPath $path) 'Expected repository artifact exists.'
}

foreach ($selectedBrowser in $Browser) {
    $registryRoot = if ($selectedBrowser -eq 'Chrome') {
        'HKCU:\Software\Google\Chrome\NativeMessagingHosts'
    } else {
        'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts'
    }
    $registryKey = Join-Path $registryRoot 'com.aie.browser_bridge'
    $registrationValid = $false
    $detail = 'Not registered. Load the unpacked extension, then run scripts/register-native-host.ps1.'

    if (Test-Path -LiteralPath $registryKey) {
        try {
            $key = Get-Item -LiteralPath $registryKey
            $manifestPath = [string]$key.GetValue('')
            if ($manifestPath -and (Test-Path -LiteralPath $manifestPath)) {
                $hostManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
                $hostPath = [string]$hostManifest.path
                $originValid = @($hostManifest.allowed_origins) -match '^chrome-extension://[a-p]{32}/

try {
    $importTest = python -c "from aie.policy.execution_control import ExecutionControl; from aie.config import execution_enabled_path, execution_kill_switch_path; c=ExecutionControl(enabled_path=execution_enabled_path(), kill_switch_path=execution_kill_switch_path()); print('enabled=' + str(c.status().enabled).lower() + ' kill_switch=' + str(c.status().kill_switch_active).lower())" 2>&1
    Add-Check "Execution gate" ($LASTEXITCODE -eq 0) ([string]$importTest)
} catch { Add-Check "Execution gate" $false "Execution control contract could not be inspected." }

$failed = @($results | Where-Object { -not $_.Passed })

Write-Host ""
Write-Host "AIE TARGET DESKTOP VALIDATION" -ForegroundColor Cyan
Write-Host "Read-only checks only; no security or execution settings were changed." -ForegroundColor DarkGray
Write-Host ''
$results | Format-Table -AutoSize

if ($failed.Count -gt 0) {
    Write-Host ("Validation failed: " + $failed.Count + " check(s).") -ForegroundColor Red
    exit 1
}

Write-Host "All target-desktop checks passed." -ForegroundColor Green
exit 0
                $registrationValid = (
                    $hostManifest.name -eq 'com.aie.browser_bridge' -and
                    $hostManifest.type -eq 'stdio' -and
                    $originValid -and
                    $hostPath -and
                    (Test-Path -LiteralPath $hostPath)
                )
                $detail = if ($registrationValid) {
                    'Native host manifest, extension origin and executable are present.'
                } else {
                    'Native host manifest or executable is incomplete; re-register this browser.'
                }
            } else {
                $detail = 'Registry entry exists but its browser-specific manifest is missing.'
            }
        } catch {
            $detail = 'Browser native host registration could not be read safely.'
        }
    }

    $passed = $registrationValid -or -not $RequireBrowserRegistration
    Add-Check ("Native host: " + $selectedBrowser) $passed $detail
}

try {
    $importTest = python -c "from aie.policy.execution_control import ExecutionControl; from aie.config import execution_enabled_path, execution_kill_switch_path; c=ExecutionControl(enabled_path=execution_enabled_path(), kill_switch_path=execution_kill_switch_path()); print('enabled=' + str(c.status().enabled).lower() + ' kill_switch=' + str(c.status().kill_switch_active).lower())" 2>&1
    Add-Check "Execution gate" ($LASTEXITCODE -eq 0) ([string]$importTest)
} catch { Add-Check "Execution gate" $false "Execution control contract could not be inspected." }

$failed = @($results | Where-Object { -not $_.Passed })

Write-Host ""
Write-Host "AIE TARGET DESKTOP VALIDATION" -ForegroundColor Cyan
Write-Host "Read-only checks only; no security or execution settings were changed." -ForegroundColor DarkGray
Write-Host ''
$results | Format-Table -AutoSize

if ($failed.Count -gt 0) {
    Write-Host ("Validation failed: " + $failed.Count + " check(s).") -ForegroundColor Red
    exit 1
}

Write-Host "All target-desktop checks passed." -ForegroundColor Green
exit 0