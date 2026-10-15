# MuMu-only transport. Addresses are always loopback; no MoreLogin auth.
function Find-MuMuAdbCandidates {
    $dirs=New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($item in @(Get-Process | Where-Object {$_.ProcessName -match '^(MuMu|Nemu)'})) {
        try {
            $path=$item.Path
            if ($path) {
                $folder=Split-Path -Parent $path
                for ($n=0;$n -lt 3 -and $folder;$n++) {[void]$dirs.Add($folder);$folder=Split-Path -Parent $folder}
            }
        } catch {}
    }
    $paths=New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($dir in $dirs) {
        foreach ($suffix in @('','shell','bin','vmonitor\bin','adb','nx_main','nx_device')) {
            $base=if ($suffix) {Join-Path $dir $suffix} else {$dir}
            foreach ($name in @('adb.exe','adb_server.exe')) {
                $path=Join-Path $base $name
                if (Test-Path -LiteralPath $path -PathType Leaf) {[void]$paths.Add($path)}
            }
        }
    }
    return @($paths | Sort-Object)
}
function Select-MuMuAdb {
    Add-Type -AssemblyName System.Windows.Forms
    $candidates=@(Find-MuMuAdbCandidates)
    if ($candidates.Count -eq 1) {return $candidates[0]}
    $picker=New-Object Windows.Forms.OpenFileDialog
    $picker.Title='Выберите adb.exe или adb_server.exe из установленного MuMu'
    $picker.Filter='Android Debug Bridge|adb.exe;adb_server.exe';$picker.CheckFileExists=$true
    if ($candidates.Count -gt 0) {$picker.InitialDirectory=Split-Path -Parent $candidates[0]}
    try {
        if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) {Stop-Safely 'Выбор ADB отменён.'}
        if ([IO.Path]::GetFileName($picker.FileName) -notin @('adb.exe','adb_server.exe')) {Stop-Safely 'Выберите ADB из MuMu.'}
        return $picker.FileName
    } finally {$picker.Dispose()}
}
function Invoke-MuMuConnection([string]$Executable, [int]$Port=5555) {
    if ($Port -lt 1 -or $Port -gt 65535) {Stop-Safely 'Некорректный локальный порт.'}
    $serial='127.0.0.1:'+$Port
    $version=Invoke-AdbProcess $Executable @('version')
    if ($version.exit_code -ne 0 -or $version.stdout -notmatch 'Android Debug Bridge') {Stop-Safely 'Выбранный ADB не прошёл проверку version.'}
    $connection=Invoke-AdbProcess $Executable @('connect',$serial)
    if ($connection.exit_code -ne 0) {Stop-Safely 'ADB не подключился к локальному MuMu. Не меняйте настройки защиты.'}
    # connect output is not proof; check the exact transport and Android shell.
    $state=Invoke-AdbProcess $Executable @('-s',$serial,'get-state')
    if ($state.exit_code -ne 0 -or $state.stdout.Trim() -cne 'device') {Stop-Safely 'Локальный порт не подтвердил готовое ADB-устройство. Проверьте, что MuMu полностью загрузился.'}
    $android=Invoke-AdbProcess $Executable @('-s',$serial,'shell','getprop','ro.build.version.release')
    if ($android.exit_code -ne 0 -or $android.stdout.Trim() -notmatch '^[0-9]+(\.[0-9]+){0,3}$') {Stop-Safely 'Не подтверждён доступ к Android MuMu. Ответы сервиса не выполняются как команды.'}
    return [pscustomobject]@{status='connected';serial=$serial;local_only=$true;android_version=$android.stdout.Trim();port=$Port}
}
