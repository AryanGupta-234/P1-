[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Chrome', 'Edge', 'Brave')]
    [string]$Browser
)

$ErrorActionPreference = 'Stop'
$hostName = 'com.aie.browser_bridge'
$registryRoot = switch ($Browser) {
    'Chrome' { 'HKCU:\Software\Google\Chrome\NativeMessagingHosts' }
    'Edge'   { 'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts' }
    'Brave'  { 'HKCU:\Software\BraveSoftware\Brave-Browser\NativeMessagingHosts' }
}
$registryKey = Join-Path $registryRoot $hostName
$manifestDirectory = Join-Path $env:LOCALAPPDATA 'AIE\native-host'
$manifestPath = Join-Path $manifestDirectory ($hostName + '.' + $Browser.ToLowerInvariant() + '.json')

if (Test-Path -LiteralPath $registryKey) {
    Remove-Item -LiteralPath $registryKey -Recurse -Force
    Write-Host "Unregistered $hostName from $Browser."
} else {
    Write-Host "No $hostName registration found for $Browser."
}

if (Test-Path -LiteralPath $manifestPath) {
    Remove-Item -LiteralPath $manifestPath -Force
    Write-Host "Removed $Browser native host manifest."
}
