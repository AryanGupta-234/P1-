[CmdletBinding()]
param([switch]$SkipWebView2Install)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py"; $PythonArgs = @("-3.11") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python"; $PythonArgs = @() }
else { throw "Python 3.11+ is required. Install from https://www.python.org/downloads/windows/" }
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$AieExe = Join-Path $Root ".venv\Scripts\aie.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[P1] Creating project virtual environment..." -ForegroundColor Cyan
    & $Python @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
}
Write-Host "[P1] Installing AIE and pywebview dependencies..." -ForegroundColor Cyan
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed." }
& $VenvPython -m pip install --disable-pip-version-check -e .
if ($LASTEXITCODE -ne 0) { throw "AIE dependency installation failed." }
$WebView2 = $false
$RuntimeRoots = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients","HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients")
foreach ($RootPath in $RuntimeRoots) {
    if (Test-Path $RootPath) {
        $found = Get-ChildItem $RootPath -ErrorAction SilentlyContinue | Get-ItemProperty -ErrorAction SilentlyContinue | Where-Object { $_.name -match "WebView2 Runtime" }
        if ($found) { $WebView2 = $true }
    }
}
if (-not $WebView2 -and -not $SkipWebView2Install -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "[P1] Installing Microsoft Edge WebView2 Runtime if required..." -ForegroundColor Cyan
    winget install --id Microsoft.EdgeWebView2Runtime --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -eq 0) { $WebView2 = $true }
}
if (-not $WebView2) { Write-Warning "WebView2 Runtime was not confirmed. If the window fails, install the Evergreen Runtime: https://developer.microsoft.com/microsoft-edge/webview2/" }
Write-Host "[P1] Launching AIE desktop dashboard..." -ForegroundColor Green
& $AieExe dashboard
if ($LASTEXITCODE -ne 0) { throw "Dashboard exited with code $LASTEXITCODE." }
