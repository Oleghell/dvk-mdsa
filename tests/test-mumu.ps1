$ErrorActionPreference='Stop'
function Stop-Safely([string]$Message) {throw $Message}
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'mumu-local.ps1')
function Invoke-AdbProcess([string]$Executable,[string[]]$CommandArgs) {
    $script:Calls+=,($CommandArgs -join ' ')
    if ($CommandArgs -contains 'kill-server' -or $CommandArgs -contains 'input') {throw 'Forbidden command'}
    if ($CommandArgs[0] -eq 'version') {return @{exit_code=0;stdout='Android Debug Bridge version 1.0.41'}}
    if ($CommandArgs[0] -eq 'connect') {
        if ($CommandArgs[1] -cne '127.0.0.1:5555') {throw 'Nonloopback connection'}
        return @{exit_code=0;stdout='connected'}
    }
    if ($CommandArgs -contains 'get-state') {return @{exit_code=0;stdout=$(if ($script:Mode -eq 'offline') {'offline'} else {'device'})}}
    if ($CommandArgs -contains 'getprop') {return @{exit_code=0;stdout=$(if ($script:Mode -eq 'bad_android') {'not Android'} else {'12'})}}
    throw 'Unexpected ADB command'
}
foreach ($mode in @('ok','offline','bad_android')) {
    $script:Mode=$mode;$script:Calls=@();$failed=$false
    try {$result=Invoke-MuMuConnection 'mock.exe'} catch {$failed=$true}
    if ($mode -eq 'ok' -and ($failed -or $result.serial -cne '127.0.0.1:5555' -or $result.android_version -ne '12')) {throw 'MuMu connection failed'}
    if ($mode -ne 'ok' -and -not $failed) {throw 'Unverified MuMu connection accepted'}
}
$script:Calls=@();$failed=$false
try {Invoke-MuMuConnection 'mock.exe' -Port 0} catch {$failed=$true}
if (-not $failed -or $script:Calls.Count -ne 0) {throw 'Invalid port reached ADB'}
Write-Host 'MuMu loopback transport, offline rejection and Android validation tests passed.'
