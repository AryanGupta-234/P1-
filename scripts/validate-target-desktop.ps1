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
    python -c "import aie; import pywinauto; import win32evtlog; from aie.providers.uia import WindowsUIATreeProvider; from aie.providers.eventlog import WindowsEventLogProvider; from aie.providers.etw_process import WindowsETWProcessProvider; from aie.providers.process_resources import WindowsProcessResourceProvider; from aie.browser.native_host import event_from_browser_payload"
    Add-Check "Provider imports" ($LASTEXITCODE -eq 0) "Windows optional providers imported successfully."
} catch { Add-Check "Provider imports" $false "One or more Windows provider imports failed." }

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
$artifacts = @("browser_extension\manifest.json","scripts\register-native-host.ps1","scripts\unregister-native-host.ps1")
foreach ($relative in $artifacts) {
    $path = Join-Path $repoRoot $relative
    Add-Check ('Artifact: ' + $relative) (Test-Path -LiteralPath $path) 'Expected repository artifact exists.'
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