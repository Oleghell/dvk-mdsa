# Offline mocked tests: no ADB executable, API or device is used.
$ErrorActionPreference = 'Stop'
function Stop-Safely([string]$Message) { throw $Message }
function Get-Field($Object, [string]$Name) { return $Object[$Name] }
function Get-Flag($Value) { return $Value }
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'adb-check.ps1')
function Invoke-AdbProcess([string]$Executable, [string[]]$CommandArgs, [string]$InputText = '') {
    if ($CommandArgs[0] -eq 'version') { return @{exit_code=0; stdout='Android Debug Bridge version'} }
    if ($CommandArgs[0] -eq 'connect') { return @{exit_code=0; stdout='connected to FAKE_HOST'} }
    if ($CommandArgs -contains 'getprop') {
        $script:ProbeCount++
        if ($script:Mode -eq 'existing' -or ($script:Mode -eq 'auth_then_ok' -and $script:ProbeCount -ge 2)) {
            return @{exit_code=0; stdout='15'}
        }
        return @{exit_code=1; stdout='PRIVATE_ERROR'}
    }
    if ($CommandArgs -contains 'FAKE_CODE') {
        $script:AuthCount++
        return @{exit_code=127; stdout='PRIVATE_AUTH_ERROR'}
    }
    if ($CommandArgs -contains 'wm') { return @{exit_code=0; stdout='Physical size: 1080x1920'} }
    if ($CommandArgs -contains 'pm') { return @{exit_code=0; stdout='package:drug.vokrug'} }
    throw 'Unexpected mocked command'
}
$entry = @{id='1'; supportAdb=$true; enableAdb=$true; envStatus=4; command=$null; adbIp='192.0.2.1'; adbPort='5555'; adbPassword='FAKE_CODE'}
foreach ($mode in @('existing', 'auth_then_ok', 'failure')) {
    $script:Mode=$mode; $script:ProbeCount=0; $script:AuthCount=0; $script:AdbProbeDiagnostics=$null
    $failed=$false
    try { $result=Invoke-FirstAdbCheck 'unused.exe' '1' @($entry) } catch { $failed=$true }
    if ($mode -eq 'existing') {
        if ($failed -or $script:AuthCount -ne 0 -or $script:ProbeCount -ne 1) { throw 'Existing session incorrectly reauthenticated' }
        if ($result.authentication_mode -ne 'existing_session') { throw 'Wrong auth mode' }
    }
    if ($mode -eq 'auth_then_ok') {
        if ($failed -or $script:AuthCount -ne 1 -or $script:ProbeCount -ne 2) { throw 'Final probe must determine auth success' }
    }
    if ($mode -eq 'failure' -and -not $failed) { throw 'Unconfirmed shell accepted' }
    if (($script:AdbProbeDiagnostics | ConvertTo-Json) -match 'PRIVATE|FAKE_CODE') { throw 'Secret leaked to diagnostics' }
}
Write-Host 'Offline mocked ADB authentication tests passed.'
