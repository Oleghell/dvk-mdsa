# Offline color heuristic tests only, NOT a WinRT OCR or message-reader test.
$ErrorActionPreference='Stop'
function Stop-Safely([string]$Message) { throw $Message }
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'chat-ocr.ps1')
Add-Type -AssemblyName System.Drawing
$bitmap=[Drawing.Bitmap]::new(300,100)
$g=[Drawing.Graphics]::FromImage($bitmap)
$cyan=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(222,245,247))
try {
    $g.Clear([Drawing.Color]::FromArgb(240,241,246))
    $g.FillRectangle($cyan,100,10,180,60)
    if ((Get-LineDirection $bitmap 130 25 100 25) -ne 'outgoing_candidate') { throw 'Synthetic outgoing failed' }
    $g.Clear([Drawing.Color]::FromArgb(240,241,246))
    $g.FillRectangle([Drawing.Brushes]::White,5,10,140,60)
    if ((Get-LineDirection $bitmap 15 25 100 25) -ne 'incoming_candidate') { throw 'Synthetic incoming failed' }
    $g.Clear([Drawing.Color]::FromArgb(240,241,246))
    if ((Get-LineDirection $bitmap 15 25 100 25) -ne 'unknown') { throw 'Background should remain unknown' }
    Write-Host 'Synthetic direction checks passed. Real chat directions are still unverified.'
}
finally { $cyan.Dispose(); $g.Dispose(); $bitmap.Dispose() }
