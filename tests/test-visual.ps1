# Offline synthetic image tests; Windows System.Drawing required, no API/device.
$ErrorActionPreference='Stop'
function Stop-Safely([string]$Message) { throw $Message }
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'visual-preview.ps1')
Add-Type -AssemblyName System.Drawing
$bitmap=[Drawing.Bitmap]::new(300,200)
$g=[Drawing.Graphics]::FromImage($bitmap)
$brush=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(0,165,180))
try {
    $g.Clear([Drawing.Color]::White)
    $g.FillEllipse($brush,220,60,60,60)
    $candidate=Find-TealCandidate $bitmap 200 30 300 150 45
    if ($null -eq $candidate) { throw 'Synthetic teal button not detected' }
    if ($candidate.x -lt 218 -or $candidate.x -gt 224) { throw 'Unexpected candidate location' }
    $g.Clear([Drawing.Color]::White)
    $g.FillEllipse([Drawing.Brushes]::Gold,220,60,60,60)
    if ($null -ne (Find-TealCandidate $bitmap 200 30 300 150 45)) { throw 'Yellow plus falsely accepted as teal' }
    $g.Clear([Drawing.Color]::White)
    if ($null -ne (Find-TealCandidate $bitmap 200 30 300 150 45)) { throw 'Blank image falsely accepted' }
    Write-Host 'Synthetic visual candidate tests passed. This is NOT send-button verification.'
}
finally { $brush.Dispose(); $g.Dispose(); $bitmap.Dispose() }
