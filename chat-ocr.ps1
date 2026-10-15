# Local OCR diagnostic only. No AI responses, taps or sending.
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'portable-ocr.ps1')) { . (Join-Path $PSScriptRoot 'portable-ocr.ps1') }
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'chat-core.ps1')) { . (Join-Path $PSScriptRoot 'chat-core.ps1') }
function Initialize-LocalOcr {
    # Prefer the bundled portable backend; no Windows services or language packs.
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    $portableExe=Join-Path $PSScriptRoot 'runtime\tesseract\tesseract.exe'
    $portableData=Join-Path $PSScriptRoot 'runtime\tesseract\tessdata'
    if ((Test-Path -LiteralPath $portableExe) -and (Test-Path -LiteralPath (Join-Path $portableData 'rus.traineddata')) -and (Test-Path -LiteralPath (Join-Path $portableData 'eng.traineddata'))) {
        . (Join-Path $PSScriptRoot 'portable-ocr.ps1')
        $script:OcrDiagnostics=[ordered]@{engine='tesseract_local'; status='initialized'; language_requested='rus+eng'; windows_language_pack_required=$false}
        return [pscustomobject]@{Backend='tesseract_local'; Executable=$portableExe; DataDirectory=$portableData; RecognizerLanguage=[pscustomobject]@{LanguageTag='rus+eng'}}
    }
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        Add-Type -AssemblyName System.Drawing
        Add-Type -AssemblyName System.Windows.Forms
        $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Globalization.Language, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Graphics.Imaging.BitmapAlphaMode, Windows.Foundation, ContentType=WindowsRuntime]
        $script:OcrDiagnostics = [ordered]@{engine='windows_local'; language_requested='ru'; status='initializing'}
        $available = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
        $script:OcrDiagnostics.available_languages = $available
        $language = [Windows.Globalization.Language]::new('ru')
        if (-not [Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($language)) {
            Stop-Safely 'На ноутбуке нет русского языкового компонента Windows OCR. Этот режим требует его; автоматически устанавливать компоненты или отключать ограничения он не будет.'
        }
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
        if ($null -eq $engine) { Stop-Safely 'Windows не смог создать русский OCR. Проверьте доступность языкового компонента.' }
        $script:OcrAsTask = @([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        })[0]
        if ($null -eq $script:OcrAsTask) { Stop-Safely 'Не найден мост WinRT AsTask. Требуется Windows PowerShell 5.1 с поддержкой WinRT.' }
        $script:OcrDiagnostics.status='initialized'
        return $engine
    }
    catch {
        if ($script:SafeError) { throw }
        Stop-Safely 'Не удалось инициализировать встроенный Windows OCR. Компонент может быть недоступен в этой редакции Windows.'
    }
}

function Wait-LocalWinRt($Operation, [Type]$ResultType) {
    try {
        $method=$script:OcrAsTask.MakeGenericMethod(@($ResultType))
        $task=$method.Invoke($null,@($Operation))
        if (-not $task.Wait(30000)) { Stop-Safely 'Локальный OCR не завершился за 30 секунд.' }
        return ,$task.Result
    }
    catch {
        if ($script:SafeError) { throw }
        Stop-Safely 'Ошибка встроенного Windows OCR/WinRT. Текст распознаваемого экрана и системные исключения не выводятся.'
    }
}

function Get-LineDirection($Bitmap, [int]$X, [int]$Y, [int]$Width, [int]$Height) {
    $left=[Math]::Max(0,$X - 10); $top=[Math]::Max(0,$Y - 6)
    $right=[Math]::Min($Bitmap.Width,$X + $Width + 10); $bottom=[Math]::Min($Bitmap.Height,$Y + $Height + 6)
    $cyan=0; $white=0; $samples=0
    for ($yy=$top; $yy -lt $bottom; $yy+=3) {
        for ($xx=$left; $xx -lt $right; $xx+=3) {
            $color=$Bitmap.GetPixel($xx,$yy)
            if ($color.R -lt 150 -or $color.G -lt 150 -or $color.B -lt 150) { continue }
            $samples++
            if ($color.R -ge 160 -and $color.G -ge 200 -and $color.B -ge 200 -and
                $color.G - $color.R -ge 7 -and $color.B - $color.R -ge 7) { $cyan++ }
            if ($color.R -ge 249 -and $color.G -ge 249 -and $color.B -ge 249) { $white++ }
        }
    }
    if ($samples -lt 10) { return 'unknown' }
    $center=$X + $Width / 2
    if ($cyan / [double]$samples -ge 0.20 -and $center -gt $Bitmap.Width * 0.35) { return 'outgoing_candidate' }
    if ($white / [double]$samples -ge 0.30 -and $X -lt $Bitmap.Width * 0.55) { return 'incoming_candidate' }
    return 'unknown'
}

function Show-LocalChatOcr([string]$Executable, [string]$Serial, $UiReport) {
    $engine=Initialize-LocalOcr
    $fields=@($UiReport.nodes | Where-Object { $_.class -eq 'android.widget.EditText' -and $_.enabled })
    if ($fields.Count -ne 1 -or $fields[0].bounds -notmatch '^\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]$') {
        Stop-Safely 'Не найдено однозначное поле ввода. Откройте тестовый диалог.'
    }
    $fieldTop=[int]$Matches[2]
    $fieldHeight=[int]$Matches[4] - $fieldTop
    if ($fields[0].has_text -or $fields[0].focused) { Stop-Safely 'Для чтения очистите черновик и закройте клавиатуру, затем повторите запуск.' }
    $choice=[Windows.Forms.MessageBox]::Show(
        'Будет прочитана видимая часть переписки первого телефона. Распознанный текст будет показан и сохранён в reports/chat-preview-local-*.txt на вашем ноутбуке. Изображения и текст не загружаются в OCR-сервисы. Используйте только согласованный тестовый диалог. Нажатий и отправки не будет. Продолжить?',
        'Локальное чтение тестового диалога',[Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Information,[Windows.Forms.MessageBoxDefaultButton]::Button2)
    if ($choice -ne [Windows.Forms.DialogResult]::Yes) { Stop-Safely 'Локальное чтение переписки отменено.' }
    if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') { Stop-Safely 'Откройте drug.vokrug на первом телефоне.' }
    $bytes=$null; $imageStream=$null; $image=$null; $bitmap=$null; $crop=$null; $pngStream=$null
    $winStream=$null; $writer=$null; $softwareBitmap=$null; $dialog=$null; $pngBytes=$null
    try {
        $bytes=Read-AdbScreenshot $Executable $Serial
        $imageStream=[IO.MemoryStream]::new($bytes,$false)
        $image=[Drawing.Image]::FromStream($imageStream)
        $bitmap=[Drawing.Bitmap]::new($image)
        if ($fieldTop -gt $bitmap.Height -or $fieldTop -lt 1) { Stop-Safely 'Размер снимка не соответствует полю ввода.' }
        if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') { Stop-Safely 'Приложение изменилось во время чтения.' }
        # Only a visible band, not the complete conversation. No scrolling.
        $cropTop=[int]($bitmap.Height * 0.22)
        $cropBottom=$fieldTop - [Math]::Max(8,[int]($fieldHeight * 0.4))
        if ($cropBottom -le $cropTop) { Stop-Safely 'Недостаточно видимой области переписки. Закройте клавиатуру.' }
        $rect=[Drawing.Rectangle]::new(0,$cropTop,$bitmap.Width,$cropBottom - $cropTop)
        $crop=$bitmap.Clone($rect,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $max=if ($engine.Backend -eq 'tesseract_local') {8192} else {[Windows.Media.Ocr.OcrEngine]::MaxImageDimension}
        if ($crop.Width -gt $max -or $crop.Height -gt $max) { Stop-Safely 'Изображение больше предела встроенного OCR; автоматическое масштабирование пока не реализовано.' }
        if ($engine.Backend -eq 'tesseract_local') {
            $ocr=Invoke-PortableOcr $engine $crop
        }
        else {
        $pngStream=New-Object IO.MemoryStream
        $crop.Save($pngStream,[Drawing.Imaging.ImageFormat]::Png)
        $pngBytes=$pngStream.ToArray()
        $winStream=[Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
        $writer=[Windows.Storage.Streams.DataWriter]::new($winStream)
        $writer.WriteBytes($pngBytes)
        $stored=Wait-LocalWinRt ($writer.StoreAsync()) ([uint32])
        [void]$writer.DetachStream()
        $winStream.Seek(0)
        $decoder=Wait-LocalWinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($winStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $softwareBitmap=Wait-LocalWinRt ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocr=Wait-LocalWinRt ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
        }
        $rows=@()
        foreach ($line in $ocr.Lines) {
            $words=@($line.Words)
            if ($words.Count -eq 0) { continue }
            $x=[double]::PositiveInfinity; $y=[double]::PositiveInfinity; $right=0.0; $bottom=0.0
            foreach ($word in $words) {
                $box=$word.BoundingRect
                $x=[Math]::Min($x,$box.X); $y=[Math]::Min($y,$box.Y)
                $right=[Math]::Max($right,$box.X + $box.Width); $bottom=[Math]::Max($bottom,$box.Y + $box.Height)
            }
            $ix=[int][Math]::Floor($x); $iy=[int][Math]::Floor($y)
            $width=[int][Math]::Ceiling($right - $x); $height=[int][Math]::Ceiling($bottom - $y)
            $direction=Get-LineDirection $crop $ix $iy $width $height
            $text=[string]$line.Text
            $timeOnly=$text.Trim() -match '^[0-9]{1,2}[:.][0-9]{2}[\s✓✔]*$'
            $rows += [pscustomobject]@{x=$ix; y=$iy; width=$width; height=$height; direction=$direction; text=$text; timestamp_only=$timeOnly}
        }
        $rows=@($rows | Sort-Object y,x)
        $grouping=Invoke-ChatGrouping $crop $rows
        $incoming=@($rows | Where-Object { $_.direction -eq 'incoming_candidate' -and -not $_.timestamp_only })
        $outgoing=@($rows | Where-Object { $_.direction -eq 'outgoing_candidate' -and -not $_.timestamp_only })
        $unknown=@($rows | Where-Object { $_.direction -eq 'unknown' })
        $preview=New-Object Text.StringBuilder
        [void]$preview.AppendLine('ЛОКАЛЬНАЯ ПРОВЕРКА OCR — НИЧЕГО НЕ ОТПРАВЛЕНО')
        [void]$preview.AppendLine('Строки OCR не равны сообщениям. Направления предположительные. Время/разделители могут распознаться как текст.')
        [void]$preview.AppendLine('Показана только часть текущего экрана, не вся история. Новизна сообщений и собеседник не проверены.')
        [void]$preview.AppendLine('')
        [void]$preview.Append((Format-ChatCandidates $grouping))
        foreach ($row in $rows) {
            $label=switch ($row.direction) {
                'incoming_candidate' { 'ВХОДЯЩАЯ?' }
                'outgoing_candidate' { 'ИСХОДЯЩАЯ?' }
                default { 'НЕИЗВЕСТНО' }
            }
            if ($row.timestamp_only) { $label='ВРЕМЯ?' }
            [void]$preview.AppendLine(('['+$label+'] '+$row.text))
        }
        if ($rows.Count -eq 0) { [void]$preview.AppendLine('Текст не найден. Это не означает, что сообщений нет.') }
        $folder=Join-Path $PSScriptRoot 'reports'
        [void][IO.Directory]::CreateDirectory($folder)
        $name='chat-preview-local-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')+'.txt'
        [IO.File]::WriteAllText((Join-Path $folder $name),$preview.ToString(),[Text.UTF8Encoding]::new($true))
        $script:OcrDiagnostics.status='recognized'
        $result=[ordered]@{
            status='ok'; engine=$script:OcrDiagnostics.engine; language=$engine.RecognizerLanguage.LanguageTag
            ocr_line_count=$rows.Count; incoming_candidate_lines=$incoming.Count
            outgoing_candidate_lines=$outgoing.Count; unknown_lines=$unknown.Count
            text_values_exported_in_json=$false; local_text_preview_saved=$true; local_preview_file=$name
            grouping_status=$grouping.status; message_candidate_count=@($grouping.message_candidates).Count
            message_candidate_grouping_applied=($grouping.status -eq 'ok'); bubble_boundaries_verified=$false
            directions_verified=$false; messages_grouped=$false; new_messages_detected=$false
            automatic_reply_enabled=$false; messages_sent=0; screenshot_saved=$false
        }
        $dialog=New-Object Windows.Forms.Form
        $dialog.Text='Локальный OCR — проверьте текст и направления, отправки нет'
        $dialog.Size=[Drawing.Size]::new(850,650)
        $dialog.StartPosition='CenterScreen'
        $dialog.TopMost=$true
        $textBox=New-Object Windows.Forms.TextBox
        $textBox.Multiline=$true; $textBox.ReadOnly=$true
        $textBox.ScrollBars=[Windows.Forms.ScrollBars]::Both
        $textBox.WordWrap=$true; $textBox.Dock=[Windows.Forms.DockStyle]::Fill
        $textBox.Font=[Drawing.Font]::new('Segoe UI',12)
        $textBox.Text=$preview.ToString()
        $dialog.Controls.Add($textBox)
        [void]$dialog.ShowDialog()
        Write-Host ('Локальный текст сохранён в reports\{0}. Не присылайте личную переписку.' -f $name)
        return $result
    }
    catch {
        if ($script:SafeError) { throw }
        Stop-Safely 'Ошибка локального OCR-предпросмотра. Сырые данные и системное исключение скрыты для защиты переписки.'
    }
    finally {
        if ($null -ne $dialog) { $dialog.Dispose() }
        foreach ($item in @($softwareBitmap,$writer,$winStream,$pngStream,$crop,$bitmap,$image,$imageStream)) {
            if ($null -ne $item -and $item -is [IDisposable]) { $item.Dispose() }
        }
        foreach ($buffer in @($bytes,$pngBytes)) { if ($null -ne $buffer) { [Array]::Clear($buffer,0,$buffer.Length) } }
        $grouping=$null; $rows=$null; $ocr=$null; $preview=$null; $text=$null; $bytes=$null; $pngBytes=$null
    }
}
