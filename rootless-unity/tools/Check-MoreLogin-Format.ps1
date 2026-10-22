param([switch]$SelfTest, [string]$PhoneId = '1732535802182343')
$ErrorActionPreference = 'Stop'
Set-PSDebug -Off
function Get-TypeLabel($Value) {
    if ($null -eq $Value) { return 'null' }
    if ($Value -is [string]) { return 'string' }
    if ($Value -is [bool]) { return 'boolean' }
    if ($Value -is [ValueType]) { return 'number' }
    return 'other'
}
function Get-SafeShape($Entry) {
    $fields = [ordered]@{}
    foreach ($name in @('id','supportAdb','enableAdb','envStatus','remark','command','adbIp','adbPort','adbPassword')) {
        $fields[$name] = Get-TypeLabel $Entry.$name
    }
    $command = if ($Entry.command -is [string]) { $Entry.command } else { '' }
    $shapes = @()
    $safeWords = @('ssh','adb','adb.exe','connect','shell','exit','-s','-p','-L','-N','-f','-Nf','-fN','-o','&&',';','||','HostKeyAlgorithms=+ssh-rsa','StrictHostKeyChecking=no','UserKnownHostsFile=/dev/null','-oHostKeyAlgorithms=+ssh-rsa','-oStrictHostKeyChecking=no')
    $matches = [regex]::Matches($command, '"[^"]*"|''[^'']*''|\S+')
    foreach ($match in @($matches | Select-Object -First 64)) {
        $token = $match.Value.Trim('"', "'")
        $canonical = @($safeWords | Where-Object { $_ -ceq $token })
        if ($canonical.Count -eq 1) { $shapes += $canonical[0] }
        elseif ($token -match '^\d+$') { $shapes += '<number>' }
        elseif ($token -match '^\d{1,3}(\.\d{1,3}){3}:\d+$') { $shapes += '<IPv4:port>' }
        elseif ($token -match '^\d{1,3}(\.\d{1,3}){3}$') { $shapes += '<IPv4>' }
        elseif ($token -match '^[^@\s]+@[^@\s]+$') { $shapes += '<user@host>' }
        elseif ($token -match '^-L.+$') { $shapes += '-L<forwarding>' }
        elseif ($token -match '^\d+:[^\s]+:\d+$') { $shapes += '<forwarding>' }
        else { $shapes += '<redacted>' }
    }
    $kind = 'other'
    if ($command -match '^\s*ssh\s') { $kind = 'ssh' }
    elseif ($command -match '^\s*adb(\.exe)?\s') { $kind = 'adb' }
    elseif ([string]::IsNullOrWhiteSpace($command)) { $kind = 'empty' }
    $portValid = [string]$Entry.adbPort -match '^\d{1,5}$'
    if ($portValid) { $portValid = ([int]$Entry.adbPort -ge 1 -and [int]$Entry.adbPort -le 65535) }
    $state = $null
    if ($Entry.envStatus -is [ValueType] -and $Entry.envStatus -isnot [bool] -and $Entry.envStatus -in (0..20)) { $state = [int]$Entry.envStatus }
    return [ordered]@{
        fields=$fields
        command_kind=$kind
        command_tokens=$shapes
        command_token_count=$matches.Count
        command_has_newline=($command.Contains("`n") -or $command.Contains("`r"))
        command_has_outer_whitespace=($command -cne $command.Trim())
        command_has_shell_separator=($command -match '[;&|]')
        adb_ip_is_ipv4=([string]$Entry.adbIp -match '^\d{1,3}(\.\d{1,3}){3}$')
        adb_port_valid=$portValid
        adb_password_present=($null -ne $Entry.adbPassword -and [string]$Entry.adbPassword -ne '')
        adb_password_numeric=([string]$Entry.adbPassword -cmatch '^[0-9]{1,32}$')
        support_adb=($Entry.supportAdb -eq $true)
        enable_adb=($Entry.enableAdb -eq $true)
        env_status=$state
        remark_present=($null -ne $Entry.remark -and [string]$Entry.remark -ne '')
    }
}
if ($SelfTest) {
    $entry = [pscustomobject]@{id='SYNTHETIC-ID';command='adb connect 8.8.8.8:15555 && adb -s 8.8.8.8:15555 shell 726491';adbIp='8.8.8.8';adbPort=15555;adbPassword='SYNTHETIC-SECRET';envStatus=4;supportAdb=$true;enableAdb=$true;remark='PRIVATE-REMARK'}
    $json = Get-SafeShape $entry | ConvertTo-Json -Depth 8
    foreach ($secret in @('SYNTHETIC-ID','8.8.8.8','15555','726491','SYNTHETIC-SECRET','PRIVATE-REMARK')) {
        if ($json.Contains($secret)) { throw 'Sanitizer self-test failed' }
    }
    if (-not $json.Contains('<IPv4:port>')) { throw 'Missing safe command shape' }
    Write-Host 'Offline sanitizer self-test passed. No network or saved credentials accessed.'
    exit 0
}
$report = [ordered]@{check='morelogin-format-v1';utc=[DateTime]::UtcNow.ToString('o');result='not-started';stage='credentials';http_status=$null;service_code=$null;shape=$null}
function Invoke-OfficialRead([string]$ApiPath, $Body, [string]$Token) {
    if ($ApiPath -notin @('/oauth2/token','/cloudphone/batchAdbInfo')) { throw 'Not allowed' }
    $req=$null; $response=$null; $bytes=$null
    try {
        $req = [Net.HttpWebRequest]::Create('https://api.morelogin.com' + $ApiPath)
        $req.Method='POST'; $req.ContentType='application/json'; $req.Accept='application/json'
        $req.Proxy=$null; $req.AllowAutoRedirect=$false; $req.Timeout=25000; $req.ReadWriteTimeout=25000
        if ($Token) { $req.Headers.Add('Authorization', 'Bearer ' + $Token) }
        $bytes=[Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress -Depth 4))
        $req.ContentLength=$bytes.Length
        $stream=$req.GetRequestStream()
        try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
        try { $response=$req.GetResponse() }
        catch [Net.WebException] { if ($null -eq $_.Exception.Response) { throw }; $response=$_.Exception.Response }
        $report.http_status=[int]$response.StatusCode
        if ($report.http_status -ne 200) { $report.result='http-error'; throw 'HTTP error' }
        $reader=New-Object IO.StreamReader($response.GetResponseStream())
        try {
            $buffer=New-Object char[] 4096; $builder=New-Object Text.StringBuilder
            while (($read=$reader.Read($buffer,0,$buffer.Length)) -gt 0) {
                if ($builder.Length + $read -gt 2097152) { throw 'Response too large' }
                [void]$builder.Append($buffer,0,$read)
            }
            $parsed=$builder.ToString() | ConvertFrom-Json
        } finally { $reader.Dispose() }
        $report.service_code=$null
        if ($parsed.code -is [ValueType] -and $parsed.code -isnot [bool] -and $parsed.code -ge 0 -and $parsed.code -le 999999 -and [long]$parsed.code -eq $parsed.code) { $report.service_code=[long]$parsed.code }
        if ($null -eq $report.service_code -or $report.service_code -ne 0) { $report.result='api-response-error'; throw 'API error' }
        return $parsed
    } finally {
        if ($null -ne $bytes) { [Array]::Clear($bytes,0,$bytes.Length) }
        if ($null -ne $response) { $response.Close() }
        if ($null -ne $req) { $req.Abort() }
    }
}
$plain=$null; $creds=$null; $auth=$null; $token=$null; $entries=$null; $entry=$null
try {
    Write-Host 'Проверка формата MoreLogin. Телефоны не запускаются, ADB-команды не выполняются.'
    Write-Host 'Используются сохранённые ключи текущего пользователя Windows. Не включайте запись PowerShell Transcript.'
    if ($PhoneId -notmatch '^[1-9][0-9]{0,29}$') { throw 'Invalid ID' }
    Add-Type -AssemblyName System.Security
    $path=Join-Path $env:LOCALAPPDATA 'DvkAssistantMoreLogin\morelogin.dpapi'
    $info=Get-Item -LiteralPath $path
    if ($info.Length -lt 1 -or $info.Length -gt 16384) { throw 'Invalid credentials file' }
    $plain=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($path),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $creds=[Text.Encoding]::UTF8.GetString($plain) | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($creds.app_id) -or [string]::IsNullOrWhiteSpace($creds.key)) { throw 'Invalid credentials' }
    [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $report.stage='auth'
    $auth=Invoke-OfficialRead '/oauth2/token' @{client_id=$creds.app_id;client_secret=$creds.key;grant_type='client_credentials'} ''
    $token=$auth.data.access_token
    if ($token -isnot [string] -or $token -notmatch '^[A-Za-z0-9_.~-]{16,16384}$') { throw 'Invalid token' }
    $report.stage='adb-info'
    $reply=Invoke-OfficialRead '/cloudphone/batchAdbInfo' @{envIds=@($PhoneId)} $token
    $entries=@($reply.data | Where-Object { $_.id -ceq $PhoneId })
    if ($entries.Count -ne 1) { $report.result='phone-not-returned'; throw 'Missing exact phone' }
    $entry=$entries[0]
    $report.shape=Get-SafeShape $entry
    $report.result='shape-ok'
} catch {
    if ($report.result -eq 'not-started') { $report.result='check-failed' }
} finally {
    if ($null -ne $plain) { [Array]::Clear($plain,0,$plain.Length) }
    $creds=$null; $auth=$null; $token=$null; $entries=$null; $entry=$null; $reply=$null
    # Managed strings cannot be guaranteed to be immediately erased from RAM.
}
try {
    $output=Join-Path $PSScriptRoot 'morelogin-format-check.json'
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding UTF8
    Write-Host ('Итог: ' + $report.result)
    Write-Host 'Пришлите только morelogin-format-check.json. Ключи и исходный ответ API не присылайте.'
} catch { Write-Host 'Не удалось сохранить отчёт. Проверьте доступ на запись в папку скрипта.' }
[void](Read-Host 'Нажмите Enter, чтобы закрыть')
