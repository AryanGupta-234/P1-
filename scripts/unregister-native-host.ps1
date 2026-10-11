[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Chrome', 'Edge')]
    [string]$Browser
)

$ErrorActionPreference = 'Stop'
$hostName = 'com.aie.browser_bridge'
$registryRoot = if ($Browser -eq 'Chrome') {
    'HKCU:\Software\Google\Chrome\NativeMessagingHosts'
} else {
    'HKCU:\Software\Microsoft\Edge\NativeMessagingHosts'
}
$registryKey = Join-Path $registryRoot $hostName

if (Test-Path -LiteralPath $registryKey) {
    Remove-Item -LiteralPath $registryKey -Recurse -Force
    Write-Host "Unregistered $hostName from $Browser."
} else {
    Write-Host "No $hostName registration found for $Browser."
}
