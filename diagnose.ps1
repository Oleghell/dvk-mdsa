#requires -Version 5.1
# Read-only MoreLogin diagnostics. No software installation or elevation.
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'config.json'),
    [string]$ReportPath = (Join-Path $PSScriptRoot 'reports\diagnostic.json')
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$script:SafeError = $null

function Stop-Safely([string]$Message) {
    $script:SafeError = $Message
    throw 'Diagnostic stopped'
}

function Get-Field($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return ,$property.Value
}

function Get-Flag($Value) {
    if ($Value -is [bool]) { return $Value }
    if (($Value -is [int] -or $Value -is [long]) -and $Value -eq 1) { return $true }
    if (($Value -is [int] -or $Value -is [long]) -and $Value -eq 0) { return $false }
    return $null
}

function Read-Configuration {
    try { $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { Stop-Safely 'Не удалось прочитать config.json. Проверьте формат JSON.' }
    $base = Get-Field $config 'api_base'
    $uri = $null
    if ($base -isnot [string] -or -not [Uri]::TryCreate($base, [UriKind]::Absolute, [ref]$uri)) {
        Stop-Safely 'Некорректный адрес Local API.'
    }
    # Require an explicit loopback host and port, without credentials or path.
    if ($base -notmatch '^http://(127\.0\.0\.1|localhost|\[::1\]):[0-9]+/?$' -or
        $uri.Port -lt 1 -or $uri.Port -gt 65535) {
        Stop-Safely 'Разрешён только локальный HTTP-адрес с портом, например http://127.0.0.1:8001.'
    }
    $ids = Get-Field $config 'phone_ids'
    if ($ids -isnot [array] -or $ids.Count -lt 1 -or $ids.Count -gt 200) {
        Stop-Safely 'phone_ids: нужен массив от 1 до 200 ID в кавычках.'
    }
    $seen = @{}
    foreach ($id in $ids) {
        if ($id -isnot [string] -or $id -notmatch '^[0-9]+$' -or $seen.ContainsKey($id)) {
            Stop-Safely 'ID должны быть уникальными строками, состоящими только из цифр.'
        }
        $seen[$id] = $true
    }
    return @{ api_base = $base.TrimEnd('/'); phone_ids = $ids }
}

function Get-AdbInfo($Config) {
    $request = [System.Net.HttpWebRequest]::Create($Config.api_base + '/api/cloudphone/batchAdbInfo')
    $request.Method = 'POST'
    $request.ContentType = 'application/json'
    $request.Accept = 'application/json'
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 25000
    $request.ReadWriteTimeout = 25000
    $bytes = [Text.Encoding]::UTF8.GetBytes((@{envIds = @($Config.phone_ids)} | ConvertTo-Json -Compress))
    $request.ContentLength = $bytes.Length
    $response = $null
    $reader = $null
    try {
        $stream = $request.GetRequestStream()
        try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { Stop-Safely 'Local API вернул неожиданный HTTP-статус; перенаправления не разрешены.' }
        $reader = [System.IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8)
        $text = New-Object System.Text.StringBuilder
        $buffer = New-Object char[] 4096
        while (($read = $reader.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($text.Length + $read -gt 2097152) { Stop-Safely 'Ответ Local API слишком большой; обработка остановлена.' }
            [void]$text.Append($buffer, 0, $read)
        }
        try { $payload = $text.ToString() | ConvertFrom-Json }
        catch { Stop-Safely 'Local API вернул не JSON. Проверьте порт API.' }
        $code = Get-Field $payload 'code'
        if ($code -isnot [int] -and $code -isnot [long]) { Stop-Safely 'В ответе нет корректного кода результата.' }
        if ($code -ne 0) { Stop-Safely ("Ошибка MoreLogin, код {0}. Проверьте права и настройки API. Ключи в чат не отправляйте." -f $code) }
        $data = Get-Field $payload 'data'
        if ($data -isnot [array]) { Stop-Safely 'Неожиданный формат списка телефонов.' }
        foreach ($item in $data) {
            if ($item -isnot [System.Management.Automation.PSCustomObject]) { Stop-Safely 'Некорректный элемент в списке телефонов.' }
        }
        # Return one array object even for zero or one result.
        return ,$data
    }
    catch [System.Net.WebException] {
        $errorResponse = $_.Exception.Response
        $httpCode = 0
        if ($null -ne $errorResponse) {
            try { $httpCode = [int]$errorResponse.StatusCode } finally { $errorResponse.Dispose() }
        }
        if ($httpCode -eq 401 -or $httpCode -eq 403) {
            Stop-Safely 'Local API требует авторизацию. Не выключайте защиту: нужна настройка авторизации клиента. Ключи в чат не отправляйте.'
        }
        if ($httpCode -gt 0) { Stop-Safely ("Local API вернул HTTP {0}. Проверьте адрес и версию MoreLogin." -f $httpCode) }
        Stop-Safely 'Нет ответа от Local API. Запустите MoreLogin на этом же компьютере и проверьте адрес/порт.'
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
    }
}

function Get-SafePhoneReport($Ids, $Entries) {
    $states = @{0='new'; 1='creation_failed'; 2='powered_off'; 3='booting'; 4='powered_on'; 5='resetting'; 6='restarting'; 7='recreating'}
    foreach ($id in $Ids) {
        $matching = @($Entries | Where-Object { [string](Get-Field $_ 'id') -ceq $id })
        if ($matching.Count -ne 1) {
            $reason = if ($matching.Count -eq 0) { 'missing_result' } else { 'duplicate_result' }
            [pscustomobject]@{phone_id=$id; ready=$false; issues=@($reason)}
            continue
        }
        $entry = $matching[0]
        $supported = Get-Flag (Get-Field $entry 'supportAdb')
        $enabled = Get-Flag (Get-Field $entry 'enableAdb')
        $status = Get-Field $entry 'envStatus'
        $isInteger = $status -is [int] -or $status -is [long]
        $poweredOn = $isInteger -and $status -eq 4
        $direct = [bool]((Get-Field $entry 'adbIp') -and (Get-Field $entry 'adbPort'))
        $tunnel = [bool](Get-Field $entry 'command')
        $issues = @()
        if ($supported -ne $true) {
            if ($supported -eq $false) { $issues += 'adb_unsupported' } else { $issues += 'adb_support_unknown' }
        }
        if ($enabled -ne $true) {
            if ($enabled -eq $false) { $issues += 'adb_disabled' } else { $issues += 'adb_switch_unknown' }
        }
        if (-not $poweredOn) { $issues += 'phone_not_powered_on' }
        if (-not ($direct -or $tunnel)) { $issues += 'connection_details_missing' }
        if (Get-Field $entry 'remark') { $issues += 'service_remark_present' }
        $state = if ($isInteger -and $states.ContainsKey([int]$status)) { $states[[int]$status] } else { 'unknown' }
        $mode = if ($tunnel) { 'ssh_tunnel' } elseif ($direct) { 'direct' } else { 'unavailable' }
        # Allowlist only. Do not export raw fields, commands or remote messages.
        [pscustomobject]@{
            phone_id=$id; ready=($issues.Count -eq 0); state=$state
            adb_supported=$supported; adb_enabled=$enabled; connection_mode=$mode
            authentication_present=[bool](Get-Field $entry 'adbPassword'); issues=@($issues)
        }
    }
}

$report = [ordered]@{
    stage='read_only_diagnostics'; implementation='windows_powershell'
    chat_automation_implemented=$false; created_at_utc=[DateTime]::UtcNow.ToString('o')
}
$exitCode = 0
try {
    $config = Read-Configuration
    $entries = Get-AdbInfo $config
    $phones = @(Get-SafePhoneReport $config.phone_ids $entries)
    $entries = $null
    $report.local_api = 'ok'
    $report.phones = $phones
    # Installation lookup only: do not execute device commands.
    $adb = Get-Command adb.exe -CommandType Application -ErrorAction SilentlyContinue
    $report.adb = @{installed=($null -ne $adb); version_check='not_run'}
    $allReady = @($phones | Where-Object { -not $_.ready }).Count -eq 0
    $report.connection_parameters_available = $allReady
    Write-Host 'Local API отвечает. Результаты:'
    foreach ($phone in $phones) {
        $summary = if ($phone.ready) { 'параметры доступны' } else { $phone.issues -join ', ' }
        Write-Host ("  {0}: {1}" -f $phone.phone_id, $summary)
    }
    Write-Host 'Подключение к Android НЕ проверялось. Сообщения НЕ отправлялись.'
    if (-not $allReady) { $exitCode = 2 }
}
catch {
    $message = $script:SafeError
    if (-not $message) { $message = 'Диагностика остановлена из-за локальной ошибки. Проверьте конфигурацию и права записи. Сырые ответы сервиса скрыты.' }
    $report.local_api = 'failed'
    $report.error = $message
    Write-Host $message
    $exitCode = 1
}
try {
    $directory = Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath))
    [void][IO.Directory]::CreateDirectory($directory)
    $json = $report | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($ReportPath, $json, (New-Object Text.UTF8Encoding($true)))
    Write-Host 'Отчёт без ключей, паролей и адресов ADB: reports\diagnostic.json'
}
catch {
    Write-Host 'Не удалось записать отчёт. Распакуйте проект в свою папку с правом записи.'
    $exitCode = 1
}
exit $exitCode
