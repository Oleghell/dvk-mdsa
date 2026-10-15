# Local, human-reviewed visual candidate only. No input/tap/send operations.
function Read-AdbScreenshot([string]$Executable, [string]$Serial) {
    if ($Serial -notmatch '^[0-9.]+:[0-9]+$') { Stop-Safely 'Неподдерживаемый адрес ADB.' }
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = '-s ' + $Serial + ' exec-out screencap -p'
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['ADB_SERVER_SOCKET'] = 'tcp:localhost:5037'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $memory = New-Object IO.MemoryStream
    try {
        [void]$process.Start()
        # Copy binary PNG bytes directly. Never use text decoding for screencap.
        $copyTask = $process.StandardOutput.BaseStream.CopyToAsync($memory)
        $errorTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(25000)) {
            try { $process.Kill() } catch {}
            Stop-Safely 'Снимок ADB не получен за 25 секунд.'
        }
        [void]$copyTask.GetAwaiter().GetResult()
        $privateError = $errorTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0 -or $memory.Length -lt 8 -or $memory.Length -gt 16777216) {
            Stop-Safely 'Не удалось получить корректный PNG через ADB. Сырые ответы скрыты.'
        }
        $bytes = $memory.ToArray()
        $signature = @(137,80,78,71,13,10,26,10)
        for ($i=0; $i -lt 8; $i++) { if ($bytes[$i] -ne $signature[$i]) { Stop-Safely 'Ответ ADB не является PNG.' } }
        return ,$bytes
    }
    catch {
        if ($script:SafeError) { throw }
        Stop-Safely 'Ошибка получения локального снимка. Проверьте adb.exe и соединение.'
    }
    finally {
        $privateError = $null
        $memory.Dispose()
        $process.Dispose()
    }
}

function Find-TealCandidate($Bitmap, [int]$X1, [int]$Y1, [int]$X2, [int]$Y2, [int]$FieldHeight) {
    # Coarse visual hypothesis only, not an icon classifier or send permission.
    $hits=0; $minX=$Bitmap.Width; $minY=$Bitmap.Height; $maxX=-1; $maxY=-1
    for ($y=$Y1; $y -lt $Y2; $y+=2) {
        for ($x=$X1; $x -lt $X2; $x+=2) {
            $color=$Bitmap.GetPixel($x,$y)
            if ($color.R -le 90 -and $color.G -ge 110 -and $color.B -ge 110 -and
                $color.G - $color.R -ge 50 -and $color.B - $color.R -ge 30 -and
                [Math]::Abs([int]$color.G - [int]$color.B) -le 100) {
                $hits++
                $minX=[Math]::Min($minX,$x); $maxX=[Math]::Max($maxX,$x)
                $minY=[Math]::Min($minY,$y); $maxY=[Math]::Max($maxY,$y)
            }
        }
    }
    if ($hits -lt 20 -or $maxX -lt $minX -or $maxY -lt $minY) { return $null }
    $width=$maxX - $minX + 2; $height=$maxY - $minY + 2
    $ratio=[double]$width/[double]$height
    $fill=[double]($hits * 4)/[double]($width * $height)
    if ($ratio -lt 0.55 -or $ratio -gt 1.8 -or $fill -lt 0.25 -or
        $width -lt $FieldHeight * 0.45 -or $height -lt $FieldHeight * 0.45 -or
        $width -gt $FieldHeight * 3 -or $height -gt $FieldHeight * 3) { return $null }
    return @{x=$minX; y=$minY; width=$width; height=$height; sampled_teal_pixels=$hits}
}

function Show-LocalVisualPreview([string]$Executable, [string]$Serial, $UiReport) {
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    $fields=@($UiReport.nodes | Where-Object { $_.class -eq 'android.widget.EditText' -and $_.enabled })
    if ($fields.Count -ne 1) { Stop-Safely 'Для визуального предпросмотра нужно ровно одно доступное поле ввода.' }
    $field=$fields[0]
    if ($field.bounds -notmatch '^\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]$') { Stop-Safely 'Не удалось определить границы поля ввода.' }
    $left=[int]$Matches[1]; $top=[int]$Matches[2]; $right=[int]$Matches[3]; $bottom=[int]$Matches[4]
    if ($right -le $left -or $bottom -le $top) { Stop-Safely 'Некорректный размер поля.' }
    $answer=[Windows.Forms.MessageBox]::Show(
        "Будет получен снимок экрана первого телефона. Полный снимок останется только в памяти, а обрезанная полоса около поля ввода сохранится на вашем ноутбуке в reports. Она может содержать черновик и часть переписки. Используйте только тестовый диалог. Ничего не нажимается и не отправляется. Продолжить?",
        'Локальный визуальный предпросмотр', [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Information, [Windows.Forms.MessageBoxDefaultButton]::Button2)
    if ($answer -ne [Windows.Forms.DialogResult]::Yes) { Stop-Safely 'Создание предпросмотра отменено.' }
    if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') { Stop-Safely 'Перед снимком откройте drug.vokrug на первом телефоне.' }
    $bytes=$null; $stream=$null; $image=$null; $bitmap=$null; $crop=$null; $canvas=$null; $graphics=$null
    $inputPen=$null; $candidatePen=$null; $font=$null; $dialog=$null
    try {
        $bytes=Read-AdbScreenshot $Executable $Serial
        $stream=[IO.MemoryStream]::new($bytes, $false)
        $image=[Drawing.Image]::FromStream($stream)
        $bitmap=[Drawing.Bitmap]::new($image)
        if ($bitmap.Width -lt $right -or $bitmap.Height -lt $bottom -or $bitmap.Width -gt 8192 -or $bitmap.Height -gt 8192) {
            Stop-Safely 'Размер снимка не соответствует структуре экрана. Никакие координаты не используются для нажатия.'
        }
        if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') { Stop-Safely 'Активное приложение изменилось во время снимка.' }
        $height=$bottom - $top
        $pad=[Math]::Max(12,[int]($height * 0.55))
        $cropTop=[Math]::Max(0,$top - $pad)
        $cropBottom=[Math]::Min($bitmap.Height,$bottom + $pad)
        $searchX=[Math]::Min($bitmap.Width,$right)
        $candidate=Find-TealCandidate $bitmap $searchX $cropTop $bitmap.Width $cropBottom $height
        $cropRect=[Drawing.Rectangle]::new(0,$cropTop,$bitmap.Width,$cropBottom - $cropTop)
        $crop=$bitmap.Clone($cropRect,[Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $canvas=[Drawing.Bitmap]::new($crop.Width,$crop.Height + 62)
        $graphics=[Drawing.Graphics]::FromImage($canvas)
        $graphics.Clear([Drawing.Color]::FromArgb(25,25,28))
        $graphics.DrawImageUnscaled($crop,0,62)
        $font=[Drawing.Font]::new('Segoe UI',14)
        $label=if ($candidate) { 'ORANGE = UNVERIFIED CANDIDATE. NO CLICKS.' } else { 'NO CANDIDATE FOUND. NO CLICKS.' }
        $graphics.DrawString($label,$font,[Drawing.Brushes]::White,12,17)
        $inputPen=[Drawing.Pen]::new([Drawing.Color]::LimeGreen,3)
        $graphics.DrawRectangle($inputPen,$left,$top - $cropTop + 62,$right - $left,$bottom - $top)
        $safeCandidate=$null
        if ($candidate) {
            $candidatePen=[Drawing.Pen]::new([Drawing.Color]::Orange,5)
            $graphics.DrawRectangle($candidatePen,$candidate.x,$candidate.y - $cropTop + 62,$candidate.width,$candidate.height)
            $safeCandidate=@{classification='unverified_teal_candidate'; bounds=@($candidate.x, $candidate.y, ($candidate.x + $candidate.width), ($candidate.y + $candidate.height))}
        }
        [void][IO.Directory]::CreateDirectory((Join-Path $PSScriptRoot 'reports'))
        $name='visual-preview-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')+'.png'
        $file=Join-Path (Join-Path $PSScriptRoot 'reports') $name
        $canvas.Save($file,[Drawing.Imaging.ImageFormat]::Png)
        $result=[ordered]@{
            status='ok'; candidate_found=($null -ne $candidate); candidate=$safeCandidate
            automatic_send_allowed=$false; clicks_performed=0; messages_sent=0
            full_screenshot_saved=$false; cropped_preview_saved=$true
            cropped_preview_contains_screen_content=$true; preview_file=$name
        }
        # Display only the local cropped preview. No HTTP upload or cloud OCR.
        $dialog=New-Object Windows.Forms.Form
        $dialog.Text='Предпросмотр — только проверка, без нажатий'
        $dialog.StartPosition='CenterScreen'
        $dialog.ClientSize=[Drawing.Size]::new([Math]::Min(1100,$canvas.Width),[Math]::Min(650,$canvas.Height + 70))
        $dialog.TopMost=$true
        $picture=New-Object Windows.Forms.PictureBox
        $picture.Dock=[Windows.Forms.DockStyle]::Fill
        $picture.SizeMode=[Windows.Forms.PictureBoxSizeMode]::Zoom
        $picture.Image=$canvas
        $dialog.Controls.Add($picture)
        $close=New-Object Windows.Forms.Button
        $close.Text='Закрыть — ничего не отправлять'
        $close.Dock=[Windows.Forms.DockStyle]::Bottom
        $close.Height=45
        $close.Add_Click({$dialog.Close()})
        $dialog.Controls.Add($close)
        [void]$dialog.ShowDialog()
        Write-Host ('Обрезанный предпросмотр сохранён локально: reports\{0}' -f $name)
        return $result
    }
    finally {
        if ($null -ne $dialog) { $dialog.Dispose() }
        foreach ($item in @($graphics,$font,$inputPen,$candidatePen,$canvas,$crop,$bitmap,$image,$stream)) {
            if ($null -ne $item) { $item.Dispose() }
        }
        if ($null -ne $bytes) { [Array]::Clear($bytes,0,$bytes.Length) }
        $bytes=$null
    }
}
