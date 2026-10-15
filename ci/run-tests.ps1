# Offline Windows PowerShell tests. Never connect to real MoreLogin/ADB devices.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$syntaxFailed = $false
Get-ChildItem -LiteralPath $root -Filter '*.ps1' -Recurse | ForEach-Object {
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        $syntaxFailed = $true
        foreach ($item in $parseErrors) {
            Write-Host ('SYNTAX ERROR {0}:{1}: {2}' -f $_.Name, $item.Extent.StartLineNumber, $item.Message)
        }
    }
}
if ($syntaxFailed) { throw 'PowerShell syntax validation failed. Do not distribute this revision.' }
Write-Host 'All PowerShell files parsed successfully.'
$tests = @('test-ui.ps1', 'test-adb-auth.ps1', 'test-visual.ps1', 'test-chat-direction.ps1', 'test-portable-ocr.ps1')
foreach ($name in $tests) {
    Write-Host ('RUN OFFLINE TEST: {0}' -f $name)
    & (Join-Path (Join-Path $root 'tests') $name)
    if (-not $?) { throw ('Offline test failed: ' + $name) }
}
Write-Host 'All offline Windows tests completed. Live API, ADB, GUI and WinRT OCR are NOT certified by this run.'
