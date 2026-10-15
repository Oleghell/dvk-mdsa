# Optional local Tesseract adapter. Does not install software or use the network.
function ConvertFrom-TesseractTsv([string]$Tsv, [int]$ImageWidth, [int]$ImageHeight) {
    $groups=[ordered]@{}
    $items=@($Tsv | ConvertFrom-Csv -Delimiter "`t")
    foreach ($row in $items) {
        if ($row.level -ne '5' -or [string]::IsNullOrWhiteSpace($row.text)) { continue }
        $numbers=@{}
        foreach ($name in @('page_num','block_num','par_num','line_num','left','top','width','height')) {
            $number=0
            if (-not [int]::TryParse([string]$row.$name,[ref]$number) -or $number -lt 0) { Stop-Safely 'OCR вернул некорректные координаты.' }
            $numbers[$name]=$number
        }
        if ($numbers.left + $numbers.width -gt $ImageWidth -or $numbers.top + $numbers.height -gt $ImageHeight) { Stop-Safely 'Координаты OCR выходят за изображение.' }
        $key='{0}/{1}/{2}/{3}' -f $numbers.page_num,$numbers.block_num,$numbers.par_num,$numbers.line_num
        if (-not $groups.Contains($key)) { $groups[$key]=New-Object 'System.Collections.Generic.List[object]' }
        $groups[$key].Add([pscustomobject]@{
            Text=[string]$row.text
            BoundingRect=[pscustomobject]@{X=$numbers.left; Y=$numbers.top; Width=$numbers.width; Height=$numbers.height}
        })
    }
    $lines=@()
    foreach ($key in $groups.Keys) {
        $words=@($groups[$key].ToArray())
        $lines += [pscustomobject]@{Text=(($words | ForEach-Object {$_.Text}) -join ' '); Words=$words}
    }
    return [pscustomobject]@{Lines=$lines}
}

function Invoke-PortableOcr($Engine, $Bitmap) {
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Engine.Executable
    $info.Arguments='stdin stdout --tessdata-dir "'+$Engine.DataDirectory+'" -l rus+eng --oem 1 --psm 6 tsv'
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.Encoding]::UTF8
    $info.StandardErrorEncoding=[Text.Encoding]::UTF8
    $info.WorkingDirectory=Split-Path -Parent $Engine.Executable
    # Do not rely on an installed copy or system PATH for runtime DLLs.
    $info.EnvironmentVariables['PATH']=$env:SystemRoot+'\System32;'+$env:SystemRoot
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    $stream=New-Object IO.MemoryStream
    $buffer=$null
    try {
        $Bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
        $buffer=$stream.ToArray()
        [void]$process.Start()
        $outTask=$process.StandardOutput.ReadToEndAsync()
        $errTask=$process.StandardError.ReadToEndAsync()
        $process.StandardInput.BaseStream.Write($buffer,0,$buffer.Length)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(60000)) {
            try {$process.Kill()} catch {}
            Stop-Safely 'Локальный Tesseract не завершился за 60 секунд.'
        }
        $output=$outTask.GetAwaiter().GetResult()
        $privateError=$errTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { Stop-Safely 'Локальный Tesseract вернул ошибку. Убедитесь, что runtime распакован целиком и запуск разрешён.' }
        return (ConvertFrom-TesseractTsv $output $Bitmap.Width $Bitmap.Height)
    }
    catch {
        if ($script:SafeError) {throw}
        Stop-Safely 'Не удалось выполнить локальный Tesseract. Права служб и политики Windows не изменяются.'
    }
    finally {
        $output=$null; $privateError=$null
        if ($null -ne $buffer) {[Array]::Clear($buffer,0,$buffer.Length)}
        $stream.Dispose(); $process.Dispose()
    }
}
