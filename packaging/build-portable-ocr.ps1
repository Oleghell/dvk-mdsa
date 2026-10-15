# CI-only builder. NEVER run this installer script on the user's laptop.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$root=Split-Path -Parent $PSScriptRoot
$work=Join-Path $env:RUNNER_TEMP ('dvk-ocr-build-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($work)
$installer=Join-Path $work 'tesseract-setup.exe'
$url='https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe'
$expected='BEE9E3434BD94FD65387D9BE28CD467A41F61B1275383B55B0F59A1331270AE4'
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer
if ((Get-FileHash $installer -Algorithm SHA256).Hash -cne $expected) {throw 'Installer SHA256 mismatch. Build stopped.'}
$installed=Join-Path $work 'installed'
$install=Start-Process -FilePath $installer -ArgumentList @('/S',('/D='+$installed)) -Wait -PassThru
if ($install.ExitCode -ne 0 -or -not (Test-Path (Join-Path $installed 'tesseract.exe'))) {throw 'Tesseract CI installation failed'}
$bundle=Join-Path $root 'out\dvk-local-ocr-windows-x64'
$runtime=Join-Path $bundle 'runtime\tesseract'
[void][IO.Directory]::CreateDirectory($runtime)
Copy-Item -Path (Join-Path $installed '*') -Destination $runtime -Recurse -Force
Get-ChildItem -LiteralPath $runtime -Filter '*uninstall*.exe' -File | Remove-Item -Force
$data=Join-Path $runtime 'tessdata'
[void][IO.Directory]::CreateDirectory($data)
foreach ($language in @('rus','eng')) {
    Invoke-WebRequest -UseBasicParsing -Uri ('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/'+$language+'.traineddata') -OutFile (Join-Path $data ($language+'.traineddata'))
}
$legal=Join-Path $runtime 'bundle-licenses'
[void][IO.Directory]::CreateDirectory($legal)
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/LICENSE' -OutFile (Join-Path $legal 'tessdata-LICENSE.txt')
# Keep all vendor runtime documentation/license files. Do not strip DLLs.
foreach ($pattern in @('*.ps1','*.bat','*.py','*.example.json','README.md','.gitignore')) {
    Get-ChildItem -LiteralPath $root -Filter $pattern -File | Copy-Item -Destination $bundle
}
'Open START_CHAT_READ.bat on your own authorized laptop. No Windows OCR pack or administrator rights are requested. Do not run packaging/build-portable-ocr.ps1 locally.' | Set-Content -LiteralPath (Join-Path $bundle 'HOW_TO_START.txt') -Encoding UTF8
# Real Russian OCR smoke test with synthetic text, no accounts or screenshots.
Add-Type -AssemblyName System.Drawing
function Stop-Safely([string]$Message) {throw $Message}
. (Join-Path $bundle 'portable-ocr.ps1')
$bitmap=[Drawing.Bitmap]::new(1000,250)
$graphics=[Drawing.Graphics]::FromImage($bitmap)
$font=[Drawing.Font]::new('Arial',36)
try {
    $graphics.Clear([Drawing.Color]::White)
    $graphics.DrawString("Привет`nТест входящего 123",$font,[Drawing.Brushes]::Black,25,25)
    $engine=[pscustomobject]@{Executable=(Join-Path $runtime 'tesseract.exe'); DataDirectory=$data}
    $recognized=Invoke-PortableOcr $engine $bitmap -SyntheticCiDiagnostics
    $text=($recognized.Lines | ForEach-Object {$_.Text}) -join ' '
    if ($text -notmatch 'Привет' -or $text -notmatch '123') {throw 'Synthetic Russian OCR smoke test failed'}
    Write-Host 'Portable runtime: Russian synthetic OCR smoke test passed.'
}
finally {$font.Dispose(); $graphics.Dispose(); $bitmap.Dispose()}
$provenance=[ordered]@{
    engine='tesseract'; version='5.5.3.20260724'; platform='windows-x64'
    installer_url=$url; installer_sha256=$expected; models='tesseract-ocr/tessdata_fast tag 4.1.0'
    smoke_test='synthetic_russian_passed'; built_from_commit=$env:GITHUB_SHA
    installs_on_user_device=$false; changes_windows_services_on_user_device=$false
}
$provenance | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bundle 'BUILD-INFO.json') -Encoding UTF8
$hashes=Get-ChildItem -LiteralPath $bundle -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relative=$_.FullName.Substring($bundle.Length+1)
    '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash,$relative
}
$hashes | Set-Content -LiteralPath (Join-Path $bundle 'SHA256SUMS.txt') -Encoding ASCII
Write-Host 'Bundle built. Real phone behavior is NOT validated by this smoke test.'
