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
$manifestFile = $hostName + '.' + $Browser.ToLowerInvariant() + '.json'
$manifestPath = Join-Path $manifestDirectory $manifestFile

New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null

$manifest = [ordered]@{
    name = $hostName
    description = 'AIE local video playback telemetry bridge'
    path = $resolvedHost
    type = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
}

$manifestJson = $manifest | ConvertTo-Json -Depth 5
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($manifestPath, $manifestJson, $utf8WithoutBom)

$registryRoot = switch ($Browser) {
    'Chrome' { 'HKCU:\Software\Google\Chrome\NativeMessagingHosts' }
    'Edge'   { 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts' }
    'Brave'  { 'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts' }
}
$registryKey = Join-Path $registryRoot $hostName
New-Item -Path $registryKey -Force | Out-Null
Set-Item -Path $registryKey -Value $manifestPath

Write-Host "Registered $hostName for $Browser."
Write-Host "Manifest: $manifestPath"
Write-Host "Host executable: $resolvedHost"
Write-Host "Restart the browser, open the AIE extension popup, then enable monitoring."
