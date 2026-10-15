#requires -Version 5.1
param([int]$Port=5555)
$ErrorActionPreference='Stop'
$script:SafeError=$null;$script:UiForegroundProbe=@();$script:OcrDiagnostics=$null
function Stop-Safely([string]$Message) {$script:SafeError=$Message;throw 'Stopped'}
$report=[ordered]@{stage='mumu_local_read';local_only=$true;remote_access_configured=$false;created_at_utc=[DateTime]::UtcNow.ToString('o');clicks_performed=0;messages_sent=0;text_values_exported=$false;screenshot_saved=$false}
$stage='startup';$exitCode=0
try {
    Add-Type -AssemblyName System.Windows.Forms
    foreach ($file in @('adb-check.ps1','ui-inspect.ps1','visual-preview.ps1','chat-ocr.ps1','mumu-local.ps1')) {. (Join-Path $PSScriptRoot $file)}
    $exe=Select-MuMuAdb
    $confirm=[Windows.Forms.MessageBox]::Show(
        ('Подключиться только к MuMu по адресу 127.0.0.1:'+$Port+' и прочитать открытый тестовый диалог? Будут прочитаны структура экрана и изображение. Распознанный текст сохранится локально в reports. Нажатий и отправки не будет. Временный XML на Android будет удалён после чтения.'+"`n`nADB: "+$exe),
        'Локальное чтение MuMu',[Windows.Forms.MessageBoxButtons]::YesNo,[Windows.Forms.MessageBoxIcon]::Information,[Windows.Forms.MessageBoxDefaultButton]::Button2)
    if ($confirm -ne [Windows.Forms.DialogResult]::Yes) {Stop-Safely 'Подключение и чтение отменены.'}
    $stage='adb_connect'
    $connection=Invoke-MuMuConnection $exe -Port $Port
    $report.adb_connection=[ordered]@{status=$connection.status;port=$connection.port;android_version=$connection.android_version}
    $stage='ui_read'
    $report.chat_content_read=$true
    $ui=Invoke-UiInspection $exe $connection.serial
    $report.ui_inspection=$ui
    $stage='ocr_preview'
    $report.chat_read_preview=Show-LocalChatOcr $exe $connection.serial $ui
    $report.status='ok'
}
catch {
    $report.status='failed';$report.failed_stage=$stage
    $report.error=if ($script:SafeError) {$script:SafeError} else {'Локальное чтение MuMu остановлено. Сырые данные скрыты; сообщения не отправлялись.'}
    if ($null -ne $script:OcrDiagnostics) {$report.ocr_diagnostics=$script:OcrDiagnostics}
    if ($script:UiForegroundProbe.Count -gt 0) {$report.ui_foreground_probe=@($script:UiForegroundProbe)}
    Write-Host $report.error;$exitCode=1
}
try {
    $folder=Join-Path $PSScriptRoot 'reports';[void][IO.Directory]::CreateDirectory($folder)
    $path=Join-Path $folder 'mumu-read-diagnostic.json'
    [IO.File]::WriteAllText($path,($report | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($true))
    Start-Process notepad.exe -ArgumentList ('"'+$path+'"')
} catch {Write-Host 'Не удалось сохранить отчёт. Распакуйте архив в отдельную папку с правом записи.';$exitCode=1}
exit $exitCode
