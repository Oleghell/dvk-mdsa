param([Parameter(Mandatory=$true)][string]$ArchivePath,[Parameter(Mandatory=$true)][string]$ExpectedSha256)
$ErrorActionPreference='Stop'
if ((Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash -ine $ExpectedSha256) { throw 'Downloaded ZIP hash mismatch' }
$destination=Join-Path $env:RUNNER_TEMP ('delivered archive with spaces '+[Guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $destination
$required=@('chat-core.ps1','runtime\chat-core\dvk-chat-core.exe','START_CHAT_READ.bat','portable-ocr.ps1','chat-ocr.ps1','openapi.ps1','runtime\tesseract\tesseract.exe','runtime\tesseract\tessdata\rus.traineddata','runtime\tesseract\tessdata\eng.traineddata','BUILD-INFO.json','SHA256SUMS.txt')
foreach ($relative in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $destination $relative) -PathType Leaf)) { throw ('Missing delivered file: '+$relative) }
}
$verified=0
foreach ($entry in Get-Content -LiteralPath (Join-Path $destination 'SHA256SUMS.txt')) {
    if ($entry -notmatch '^([A-Fa-f0-9]{64})  (.+)$') { throw 'Invalid manifest entry' }
    $expected=$Matches[1]; $relative=$Matches[2]
    $file=Join-Path $destination $relative
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw ('Manifest file missing: '+$relative) }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $expected) { throw ('File hash mismatch: '+$relative) }
    $verified++
}
Write-Host ('Delivered ZIP: verified '+$verified+' file hashes.')
Get-ChildItem -LiteralPath $destination -Filter '*.ps1' -File | ForEach-Object {
    $tokens=$null; $errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errors)
    if ($errors.Count -gt 0) { throw ('Delivered PowerShell syntax failed: '+$_.Name) }
}
# Run the DELIVERED scripts, not the checkout's implementation. No API keys,
# ADB, real screenshots, accounts, clicks, sending, or GUI prompts are used.
function Stop-Safely([string]$Message) { throw $Message }
. (Join-Path $destination 'chat-ocr.ps1')
$engine=Initialize-LocalOcr
if ($engine.Backend -ne 'tesseract_local') { throw 'Delivered bundle selected Windows OCR instead of local Tesseract' }
$privateError=$null
$font=[Drawing.Font]::new('Arial',26)
$background=[Drawing.Color]::FromArgb(235,237,242)
$cyan=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(222,245,247))
try {
    foreach ($size in @(800,1100)) {
        $bitmap=[Drawing.Bitmap]::new($size,520)
        $g=[Drawing.Graphics]::FromImage($bitmap)
        try {
            $g.Clear($background)
            $left=[int]($size*0.48)
            $g.FillRectangle($cyan,$left,20,($size-$left-20),95)
            $g.DrawString('Привет',$font,[Drawing.Brushes]::Black,($left+18),40)
            $g.FillRectangle([Drawing.Brushes]::White,20,150,300,95)
            $g.DrawString('Отлично',$font,[Drawing.Brushes]::Black,38,170)
            $g.FillRectangle($cyan,$left,290,($size-$left-20),180)
            $g.DrawString("Тест сообщения`nВторая строка",$font,[Drawing.Brushes]::Black,($left+18),310)
            $originalEncoding=[Console]::InputEncoding
            try {
                [Console]::InputEncoding=[Text.Encoding]::UTF8
                $ocr=Invoke-PortableOcr $engine $bitmap -SyntheticCiDiagnostics
                if ([Console]::InputEncoding.GetPreamble().Length -ne 3) { throw 'Console encoding not restored' }
            }
            finally { [Console]::InputEncoding=$originalEncoding }
            $foundIncoming=$false; $foundOutgoing=$false; $foundWrapped=$false
            $groupRows=@()
            foreach ($line in $ocr.Lines) {
                $words=@($line.Words)
                if ($words.Count -eq 0) { continue }
                $x=($words | ForEach-Object {$_.BoundingRect.X} | Measure-Object -Minimum).Minimum
                $y=($words | ForEach-Object {$_.BoundingRect.Y} | Measure-Object -Minimum).Minimum
                $right=($words | ForEach-Object {$_.BoundingRect.X+$_.BoundingRect.Width} | Measure-Object -Maximum).Maximum
                $bottom=($words | ForEach-Object {$_.BoundingRect.Y+$_.BoundingRect.Height} | Measure-Object -Maximum).Maximum
                $groupRows += [pscustomobject]@{x=[int]$x;y=[int]$y;width=[int]($right-$x);height=[int]($bottom-$y);text=[string]$line.Text}
                $direction=Get-LineDirection $bitmap $x $y ($right-$x) ($bottom-$y)
                if ($line.Text -match 'Привет' -and $direction -eq 'outgoing_candidate') {$foundOutgoing=$true}
                if ($line.Text -match 'Отлично' -and $direction -eq 'incoming_candidate') {$foundIncoming=$true}
                if ($line.Text -match 'Вторая' -and $direction -eq 'outgoing_candidate') {$foundWrapped=$true}
            }
            if (-not ($foundIncoming -and $foundOutgoing -and $foundWrapped)) { throw ('Synthetic delivered chat OCR/directions failed at width '+$size) }
            $grouping=Invoke-ChatGrouping $bitmap $groupRows -SyntheticCiDiagnostics
            if ($grouping.status -ne 'ok' -or @($grouping.message_candidates).Count -ne 3) {throw ('Delivered full pipeline grouping count failed at width '+$size)}
            $wrapped=@($grouping.message_candidates | Where-Object {$_.text -match 'Тест сообщения' -and $_.text -match 'Вторая строка'})
            if ($wrapped.Count -ne 1 -or $wrapped[0].source_indices.Count -lt 2) {throw 'Multiline message was not grouped'}
            if ($grouping.messages_sent -ne 0 -or $grouping.automatic_reply_enabled) {throw 'Unexpected action capability'}
            $preview=Format-ChatCandidates $grouping
            if ($preview -notmatch 'ИСХОДНЫЕ OCR-СТРОКИ' -or $preview -notmatch 'Вторая строка') {throw 'Integrated preview formatting failed'}
            Write-Host ('Delivered full pipeline PNG -> real Tesseract -> bubble detector -> grouped preview passed at width '+$size)
            Write-Host ('Delivered OCR + directions + multiline text passed at width '+$size)
        }
        finally { $g.Dispose(); $bitmap.Dispose() }
    }
    $blank=[Drawing.Bitmap]::new(800,300)
    $g=[Drawing.Graphics]::FromImage($blank)
    try {
        $g.Clear($background)
        $ocr=Invoke-PortableOcr $engine $blank -SyntheticCiDiagnostics
        if (@($ocr.Lines).Count -ne 0) { throw 'Blank image produced OCR text' }
        $grouping=Invoke-ChatGrouping $blank @() -SyntheticCiDiagnostics
        if ($grouping.status -ne 'ok' -or @($grouping.message_candidates).Count -ne 0) {throw 'Blank full pipeline produced candidates'}
        Write-Host 'Delivered OCR and grouping: blank-image regression passed.'
    }
    finally {$g.Dispose();$blank.Dispose()}
}
finally { $font.Dispose(); $cyan.Dispose() }
# Missing executable must preserve source-line preview, not invent messages.
$missing=Join-Path $destination 'not-present-core.exe'
$fallback=Invoke-ChatGrouping $null @() -CoreExecutable $missing
if ($fallback.status -ne 'unavailable' -or @($fallback.message_candidates).Count -ne 0) {throw 'Missing-core fallback failed'}
Write-Host 'Delivered missing-core fallback passed.'
Write-Host 'PASS: actual downloaded ZIP executed on Windows. Live phone, GUI, message identity and sending NOT tested.'
