# TSV adapter unit tests, no OCR executable or network required.
$ErrorActionPreference='Stop'
function Stop-Safely([string]$Message) {throw $Message}
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'portable-ocr.ps1')
$tsv="level`tpage_num`tblock_num`tpar_num`tline_num`tword_num`tleft`ttop`twidth`theight`tconf`ttext`n"+
     "5`t1`t1`t1`t1`t1`t10`t20`t100`t40`t95`tПривет`n"+
     "5`t1`t1`t1`t1`t2`t120`t20`t80`t40`t90`t123`n"
$result=ConvertFrom-TesseractTsv $tsv 1000 500
if ($result.Lines.Count -ne 1 -or $result.Lines[0].Text -ne 'Привет 123') {throw 'TSV line grouping failed'}
if ($result.Lines[0].Words.Count -ne 2) {throw 'TSV words missing'}
$invalid=$tsv.Replace("`t100`t40", "`t99999`t40")
$rejected=$false
try {ConvertFrom-TesseractTsv $invalid 1000 500} catch {$rejected=$true}
if (-not $rejected) {throw 'Invalid OCR coordinates accepted'}
Write-Host 'Portable OCR TSV adapter tests passed.'
