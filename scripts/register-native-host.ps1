[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Chrome', 'Edge', 'Brave')]
    [string]$Browser,

    [string]$HostExecutable = (Join-Path $PSScriptRoot '..\.venv\Scripts\aie-browser-host.exe')
)

$ErrorActionPreference = 'Stop'
$resolvedHost = (Resolve-Path -LiteralPath $HostExecutable).Path
$hostName = 'com.aie.browser_bridge'
$manifestDirectory = Join-Path $env:LOCALAPPDATA 'AIE\native-host'
New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null

$origin = "chrome-extension://$ExtensionId/"
if ($Browser -eq 'Edge') {
    $manifestPath = Join-Path $manifestDirectory ($hostName + '.edge.json')
    $registryRoot = 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts'
    $allowedOrigins = @($origin)
} else {
    # Chromium-based Brave resolves native hosts through the Google Chrome
    # NativeMessagingHosts registry root (verified on the target Brave build).
    # Chrome and Brave therefore share one manifest and an origin allowlist.
    $manifestPath = Join-Path $manifestDirectory ($hostName + '.chromium.json')
    $registryRoot = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts'
    $allowedOrigins = @()

    # Preserve origins already registered through this shared Chromium entry.
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            $existing = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if ($existing.name -eq $hostName) {
                $allowedOrigins += @($existing.allowed_origins | Where-Object { $_ -match '^chrome-extension://[a-p]{32}/$' })
            }
        } catch {
            throw "Existing shared Chromium manifest is invalid; refusing to overwrite it: $manifestPath"
        }
    }

    # Migrate prior per-browser manifests so registering Brave does not
    # accidentally remove an already-authorized Chrome extension origin.
    foreach ($legacyBrowser in @('chrome', 'brave')) {
        $legacyPath = Join-Path $manifestDirectory ($hostName + '.' + $legacyBrowser + '.json')
        if (Test-Path -LiteralPath $legacyPath) {
            try {
                $legacy = Get-Content -LiteralPath $legacyPath -Raw | ConvertFrom-Json
                $allowedOrigins += @($legacy.allowed_origins | Where-Object { $_ -match '^chrome-extension://[a-p]{32}/$' })
            } catch {
                throw "Legacy $legacyBrowser manifest is invalid; refusing to discard its origin list: $legacyPath"
            }
        }
    }
    $allowedOrigins = @($allowedOrigins | Sort-Object -Unique)
    $allowedOrigins += $origin
    $allowedOrigins = @($allowedOrigins | Sort-Object -Unique)
}

$manifest = [ordered]@{
    name = $hostName
    description = 'AIE local video playback telemetry bridge'
    path = $resolvedHost
    type = 'stdio'
    allowed_origins = $allowedOrigins
}
$manifestJson = $manifest | ConvertTo-Json -Depth 5
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8WithoutBom)

$registryKey = Join-Path $registryRoot $hostName
New-Item -Path $registryKey -Force | Out-Null
Set-Item -Path $registryKey -Value $manifestPath

# Remove the obsolete Brave-specific registration. Brave does not query it.
if ($Browser -eq 'Brave') {
    $legacyBraveKey = 'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts\' + $hostName
    if (Test-Path -LiteralPath $legacyBraveKey) {
        Remove-Item -LiteralPath $legacyBraveKey -Recurse -Force
    }
}

Write-Host "Registered $hostName for $Browser."
Write-Host "Registry: $registryKey"
Write-Host "Manifest: $manifestPath"
Write-Host "Host executable: $resolvedHost"
Write-Host "Allowed extension origins: $($allowedOrigins -join ', ')"
Write-Host "Restart the browser, open the AIE extension popup, then enable monitoring."
