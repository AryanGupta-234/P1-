[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-p]{32}$')]
    [string]$ExtensionId,

    [Parameter(Mandatory = $true)]
    [ValidateSet('Chrome', 'Edge')]
    [string]$Browser,

    [string]$HostExecutable = (Join-Path $PSScriptRoot '..\.venv\Scripts\aie-browser-host.exe')
)

$ErrorActionPreference = 'Stop'
$resolvedHost = (Resolve-Path -LiteralPath $HostExecutable).Path
$hostName = 'com.aie.browser_bridge'
$manifestDirectory = Join-Path $env:LOCALAPPDATA 'AIE\native-host'
$manifestPath = Join-Path $manifestDirectory ($hostName + '.json')

New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null

$manifest = [ordered]@{
    name = $hostName
    description = 'AIE local video playback telemetry bridge'
    path = $resolvedHost
    type = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding ASCII

$registryRoot = if ($Browser -eq 'Chrome') {
    'HKCU:\Software\Google\Chrome\NativeMessagingHosts'
} else {
    'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts'
}
$registryKey = Join-Path $registryRoot $hostName
New-Item -Path $registryKey -Force | Out-Null
Set-Item -Path $registryKey -Value $manifestPath

Write-Host "Registered $hostName for $Browser."
Write-Host "Manifest: $manifestPath"
Write-Host "Host executable: $resolvedHost"
Write-Host "Restart the browser, open the AIE extension popup, then enable monitoring."
