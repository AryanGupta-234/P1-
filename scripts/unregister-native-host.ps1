[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Chrome', 'Edge', 'Brave')]
    [string]$Browser,

    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId
)

$ErrorActionPreference = 'Stop'
$hostName = 'com.aie.browser_bridge'
$manifestDirectory = Join-Path $env:LOCALAPPDATA 'AIE\native-host'
if ($Browser -eq 'Edge') {
    $registryRoot = 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts'
    $manifestPath = Join-Path $manifestDirectory ($hostName + '.edge.json')
} else {
    # Chrome and Brave share Chromium's Google Chrome native-host registry root.
    $registryRoot = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts'
    $manifestPath = Join-Path $manifestDirectory ($hostName + '.chromium.json')
}
$registryKey = Join-Path $registryRoot $hostName

if ($Browser -eq 'Edge') {
    if (Test-Path -LiteralPath $registryKey) {
        Remove-Item -LiteralPath $registryKey -Recurse -Force
        Write-Host "Unregistered $hostName from Edge."
    }
    if (Test-Path -LiteralPath $manifestPath) {
        Remove-Item -LiteralPath $manifestPath -Force
        Write-Host 'Removed Edge native host manifest.'
    }
    return
}

if (-not $ExtensionId) {
    throw 'For Chrome/Brave, pass -ExtensionId so only that extension origin is removed from the shared Chromium manifest.'
}

if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $origin = "chrome-extension://$ExtensionId/"
    $remainingOrigins = @($manifest.allowed_origins | Where-Object { $_ -ne $origin })

    if ($remainingOrigins.Count -gt 0) {
        $manifest.allowed_origins = $remainingOrigins
        $json = $manifest | ConvertTo-Json -Depth 5
        $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
        [System.IO.File]::WriteAllText($manifestPath, $json, $utf8WithoutBom)
        Write-Host "Removed $Browser origin from shared Chromium manifest; other origins remain registered."
    } else {
        if (Test-Path -LiteralPath $registryKey) {
            Remove-Item -LiteralPath $registryKey -Recurse -Force
        }
        Remove-Item -LiteralPath $manifestPath -Force
        Write-Host 'Removed the final Chromium origin, registry entry and shared manifest.'
    }
} else {
    Write-Host 'Shared Chromium manifest not found; nothing to unregister.'
}
