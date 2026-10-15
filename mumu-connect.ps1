$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
$root=$PSScriptRoot
$report=[ordered]@{stage='mumu_local_connection'; local_only=$true; remote_access_configured=$false; clicks_performed=0; messages_sent=0; mumu_versions=@(); local_devices=@(); possible_listening_ports=@()}
$process=$null
try {
    $running=@(Get-Process | Where-Object {$_.ProcessName -match '^(MuMu|Nemu)'})
    $dirs=New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($item in $running) {
        try {
            $path=$item.Path
            if ($path) {
                $report.mumu_versions += [ordered]@{process=$item.ProcessName;version=[Diagnostics.FileVersionInfo]::GetVersionInfo($path).FileVersion}
                $folder=Split-Path -Parent $path
                for ($n=0;$n -lt 3 -and $folder;$n++) {
                    [void]$dirs.Add($folder)
                    $folder=Split-Path -Parent $folder
                }
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
    $candidates=@($paths | Sort-Object)
    $exe=$null
    if ($candidates.Count -eq 1) {$exe=$candidates[0]}
    else {
        $picker=New-Object Windows.Forms.OpenFileDialog
        $picker.Title='Выберите adb.exe или adb_server.exe из папки MuMu'
        $picker.Filter='Android Debug Bridge|adb.exe;adb_server.exe'
        if ($candidates.Count -gt 0) {$picker.InitialDirectory=Split-Path -Parent $candidates[0]}
        elseif ($dirs.Count -gt 0) {$picker.InitialDirectory=@($dirs)[0]}
        try {if ($picker.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) {$exe=$picker.FileName}}
        finally {$picker.Dispose()}
    }
    if (-not $exe) {throw 'Выбор ADB отменён. Ничего не подключено.'}
    $name=[IO.Path]::GetFileName($exe)
    if ($name -notin @('adb.exe','adb_server.exe')) {throw 'Выбран не ADB.'}
    $answer=[Windows.Forms.MessageBox]::Show(
        ('Будет выполнена только команда adb devices -l для списка устройств. Возможен запуск локального ADB-сервера. Подключение по новым адресам, нажатия, чтение переписки и отправка не выполняются.'+"`n`n"+$exe),
        'Проверка подключения MuMu',[Windows.Forms.MessageBoxButtons]::YesNo,[Windows.Forms.MessageBoxIcon]::Information,[Windows.Forms.MessageBoxDefaultButton]::Button2)
    if ($answer -ne [Windows.Forms.DialogResult]::Yes) {throw 'Проверка отменена.'}
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$exe; $info.Arguments='devices -l'; $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $process=New-Object Diagnostics.Process; $process.StartInfo=$info
    [void]$process.Start()
    $out=$process.StandardOutput.ReadToEndAsync();$err=$process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(15000)) {$process.Kill();throw 'ADB не ответил за 15 секунд.'}
    $output=$out.GetAwaiter().GetResult();$privateError=$err.GetAwaiter().GetResult()
    $report.adb_exit_code=$process.ExitCode
    foreach ($line in ($output -split "`r?`n")) {
        if ($line -match '^((?:127\.0\.0\.1|localhost):[0-9]{1,5}|emulator-[0-9]+)\s+(device|offline|unauthorized)\b') {
            $report.local_devices += [ordered]@{serial=$Matches[1];state=$Matches[2]}
        }
    }
    # Diagnostic candidates only; never connect to or probe unknown ports.
    try {
        $pids=@($running | ForEach-Object {$_.Id})
        $report.possible_listening_ports=@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {$_.OwningProcess -in $pids -and $_.LocalAddress -in @('127.0.0.1','::1')} | Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
    } catch {}
    $report.status=if ($report.local_devices.Count -gt 0) {'local_devices_found'} else {'no_local_devices_yet'}
    $report.port_candidates_are_not_verified_adb=$true
}
catch {
    $report.status='incomplete'
    # Do not print native exceptions or local paths into the shared report.
    $report.error='Подключение не проверено. Если вы отменили выбор ADB или подтверждение, повторите запуск. Если не отменяли, сообщите об ошибке.'
}
finally {
    if ($null -ne $process) {$process.Dispose()}
    $output=$null;$privateError=$null
    try {
        $destination=Join-Path $root 'mumu-connection.json'
        $report | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $destination -Encoding UTF8
        Start-Process -FilePath notepad.exe -ArgumentList ('"'+$destination+'"')
    }
    catch {[void][Windows.Forms.MessageBox]::Show('Не удалось сохранить отчёт. Полностью распакуйте архив в папку с правом записи.')}
}
