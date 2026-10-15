# Common Python core is shipped as a Windows EXE. JSON/PNG travels via pipes,
# not command arguments or image files. No network, clicks or sending here.
function Invoke-ChatGrouping($Bitmap, $Rows, [string]$CoreExecutable=(Join-Path $PSScriptRoot 'runtime\chat-core\dvk-chat-core.exe'), [switch]$SyntheticCiDiagnostics) {
    $fallback=[pscustomobject]@{status='unavailable'; message_candidates=@(); unassigned_source_indices=@(); automatic_reply_enabled=$false; messages_sent=0}
    if (-not (Test-Path -LiteralPath $CoreExecutable -PathType Leaf)) { return $fallback }
    $stream=New-Object IO.MemoryStream
    $process=New-Object Diagnostics.Process
    $png=$null; $started=$false
    try {
        $Bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
        $png=$stream.ToArray()
        $lines=@($Rows | ForEach-Object {
            [ordered]@{bounds=@([int]$_.x,[int]$_.y,[int]$_.width,[int]$_.height); text=[string]$_.text; role='content'}
        })
        $document=[ordered]@{schema_version=1; image_width=$Bitmap.Width; image_height=$Bitmap.Height
            lines=@($lines); bubbles=@(); roi=@(0,0,$Bitmap.Width,$Bitmap.Height)
            image_png_base64=[Convert]::ToBase64String($png)}
        $json=$document | ConvertTo-Json -Depth 12 -Compress
        if ([Text.Encoding]::UTF8.GetByteCount($json) -gt 8MB) { throw 'Core input size limit' }
        $info=New-Object Diagnostics.ProcessStartInfo
        $info.FileName=[IO.Path]::GetFullPath($CoreExecutable)
        $info.UseShellExecute=$false; $info.CreateNoWindow=$true
        $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
        $info.StandardOutputEncoding=[Text.Encoding]::UTF8; $info.StandardErrorEncoding=[Text.Encoding]::UTF8
        $info.WorkingDirectory=Split-Path -Parent $info.FileName
        $process.StartInfo=$info
        $savedEncoding=$null
        try {
            if ($null -ne $info.PSObject.Properties['StandardInputEncoding']) {$info.StandardInputEncoding=[Text.UTF8Encoding]::new($false)}
            else {$savedEncoding=[Console]::InputEncoding; [Console]::InputEncoding=[Text.UTF8Encoding]::new($false)}
            [void]$process.Start(); $started=$true
        }
        finally {if ($null -ne $savedEncoding) {[Console]::InputEncoding=$savedEncoding}}
        $outTask=$process.StandardOutput.ReadToEndAsync(); $errTask=$process.StandardError.ReadToEndAsync()
        $writeTask=$process.StandardInput.WriteAsync($json)
        if (-not $writeTask.Wait(60000)) {throw 'Core input timeout'}
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(60000)) {throw 'Core timeout'}
        $output=$outTask.GetAwaiter().GetResult(); $privateError=$errTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {throw 'Core rejected input'}
        $result=$output | ConvertFrom-Json
        if ($result.schema_version -ne 1 -or $result.automatic_reply_enabled -ne $false -or $result.messages_sent -ne 0) {throw 'Invalid core response'}
        $result | Add-Member -MemberType NoteProperty -Name status -Value 'ok'
        return $result
    }
    catch {
        if ($SyntheticCiDiagnostics) {Write-Host ('Synthetic grouping exception: '+$_.Exception.Message); throw}
        $fallback.status='failed'
        return $fallback
    }
    finally {
        if ($started) {try {if (-not $process.HasExited) {$process.Kill();[void]$process.WaitForExit(5000)}} catch {}}
        $stream.Dispose(); $process.Dispose()
        if ($null -ne $png) {[Array]::Clear($png,0,$png.Length)}
        $json=$null; $document=$null; $lines=$null; $output=$null; $privateError=$null
    }
}

function Format-ChatCandidates($Grouping) {
    $text=New-Object Text.StringBuilder
    if ($Grouping.status -eq 'ok') {
        [void]$text.AppendLine('КАНДИДАТЫ СООБЩЕНИЙ — границы и направления не подтверждены')
        foreach ($message in @($Grouping.message_candidates)) {
            $label=switch ($message.direction) {'incoming_candidate' {'ВХОДЯЩЕЕ?'} 'outgoing_candidate' {'ИСХОДЯЩЕЕ?'} default {'НЕИЗВЕСТНО'}}
            [void]$text.AppendLine(('['+$label+'] '+$message.text))
        }
        if (@($Grouping.message_candidates).Count -eq 0) {[void]$text.AppendLine('Однозначные кандидатные пузыри не найдены. Это не означает, что сообщений нет.')}
        [void]$text.AppendLine(('Не распределено OCR-строк: {0}. Исходные строки сохранены ниже.' -f @($Grouping.unassigned_source_indices).Count))
    }
    else {[void]$text.AppendLine('Группировка недоступна или завершилась ошибкой. Ниже — исходный OCR без группировки.')}
    [void]$text.AppendLine('')
    [void]$text.AppendLine('ИСХОДНЫЕ OCR-СТРОКИ — включая шум и возможные служебные элементы')
    return $text.ToString()
}
