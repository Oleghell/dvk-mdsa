#requires -Version 5.1
# Run on your own authorized laptop, not on a restricted remote desktop.
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'openapi.config.json'),
    [string]$ReportPath = (Join-Path $PSScriptRoot 'reports\openapi-diagnostic.json'),
    [switch]$CheckFirstAdb,
    [switch]$InspectUi
)
if ($CheckFirstAdb -and -not $PSBoundParameters.ContainsKey('ReportPath')) {
    $ReportPath = Join-Path $PSScriptRoot 'reports\adb-diagnostic.json'
}
if ($InspectUi) {
    $CheckFirstAdb = $true
    if (-not $PSBoundParameters.ContainsKey('ReportPath')) { $ReportPath = Join-Path $PSScriptRoot 'reports\ui-diagnostic.json' }
}
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$script:SafeError = $null
$script:UiForegroundProbe = @()

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
    catch { Stop-Safely 'Не удалось прочитать openapi.config.json.' }
    $base = Get-Field $config 'api_base'
    # Credentials may go ONLY to the official HTTPS origin. No custom URLs.
    if ($base -isnot [string] -or $base.TrimEnd('/') -cne 'https://api.morelogin.com') {
        Stop-Safely 'Для Open API разрешён только https://api.morelogin.com. Не используйте 127.0.0.1 или адрес удалённого стола.'
    }
    $ids = Get-Field $config 'phone_ids'
    if ($ids -isnot [array] -or $ids.Count -lt 1 -or $ids.Count -gt 200) {
        Stop-Safely 'phone_ids: нужен массив от 1 до 200 ID в кавычках.'
    }
    $seen = @{}
    foreach ($id in $ids) {
        if ($id -isnot [string] -or $id -notmatch '^[0-9]+$' -or $seen.ContainsKey($id)) {
            Stop-Safely 'ID должны быть уникальными строками из цифр.'
        }
        $seen[$id] = $true
    }
    return @{api_base='https://api.morelogin.com'; phone_ids=$ids}
}

function Read-CredentialsDialog {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $form = New-Object Windows.Forms.Form
    $form.Text = 'MoreLogin Open API — локальная проверка'
    $form.ClientSize = New-Object Drawing.Size(570, 300)
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.TopMost = $true
    $form.Font = New-Object Drawing.Font('Segoe UI', 10)

    $notice = New-Object Windows.Forms.Label
    $notice.Text = "Данные отправляются только на https://api.morelogin.com.`r`nНе публикуйте ключ в чате или на сайте обмена текстом."
    $notice.Location = New-Object Drawing.Point(18, 15)
    $notice.Size = New-Object Drawing.Size(535, 50)
    $form.Controls.Add($notice)

    $appLabel = New-Object Windows.Forms.Label
    $appLabel.Text = 'APP ID'
    $appLabel.Location = New-Object Drawing.Point(18, 77)
    $appLabel.Size = New-Object Drawing.Size(95, 25)
    $form.Controls.Add($appLabel)
    $appBox = New-Object Windows.Forms.TextBox
    $appBox.Location = New-Object Drawing.Point(120, 74)
    $appBox.Size = New-Object Drawing.Size(425, 28)
    $form.Controls.Add($appBox)

    $keyLabel = New-Object Windows.Forms.Label
    $keyLabel.Text = 'API Key'
    $keyLabel.Location = New-Object Drawing.Point(18, 124)
    $keyLabel.Size = New-Object Drawing.Size(95, 25)
    $form.Controls.Add($keyLabel)
    $keyBox = New-Object Windows.Forms.TextBox
    $keyBox.Location = New-Object Drawing.Point(120, 121)
    $keyBox.Size = New-Object Drawing.Size(425, 28)
    $keyBox.UseSystemPasswordChar = $true
    $keyBox.ShortcutsEnabled = $true
    $form.Controls.Add($keyBox)

    $lengthLabel = New-Object Windows.Forms.Label
    $lengthLabel.Text = 'В ключе символов: 0. Вставка: Ctrl+V.'
    $lengthLabel.Location = New-Object Drawing.Point(120, 155)
    $lengthLabel.Size = New-Object Drawing.Size(425, 25)
    $form.Controls.Add($lengthLabel)
    $keyBox.Add_TextChanged({ $lengthLabel.Text = 'В ключе символов: ' + $keyBox.TextLength + '. Вставка: Ctrl+V.' })

    $validation = New-Object Windows.Forms.Label
    $validation.ForeColor = [Drawing.Color]::DarkRed
    $validation.Location = New-Object Drawing.Point(18, 187)
    $validation.Size = New-Object Drawing.Size(530, 42)
    $form.Controls.Add($validation)

    $ok = New-Object Windows.Forms.Button
    $ok.Text = 'Проверить'
    $ok.Location = New-Object Drawing.Point(300, 244)
    $ok.Size = New-Object Drawing.Size(115, 34)
    $ok.Add_Click({
        if ($appBox.Text.Trim() -notmatch '^[0-9]+$') {
            $validation.Text = 'APP ID должен состоять из цифр.'
            return
        }
        if ($keyBox.TextLength -le 1) {
            $validation.Text = 'Ключ пустой или содержит один символ. Скопируйте полный API Key из MoreLogin.'
            return
        }
        if ($keyBox.Text -match '\s') {
            $validation.Text = 'В ключе есть пробел или перенос строки. Скопируйте API Key заново.'
            return
        }
        $form.DialogResult = [Windows.Forms.DialogResult]::OK
        $form.Close()
    })
    $form.Controls.Add($ok)
    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = 'Отмена'
    $cancel.Location = New-Object Drawing.Point(430, 244)
    $cancel.Size = New-Object Drawing.Size(115, 34)
    $cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel
    try {
        $result = $form.ShowDialog()
        if ($result -ne [Windows.Forms.DialogResult]::OK) { Stop-Safely 'Проверка отменена пользователем.' }
        $secure = ConvertTo-SecureString -String $keyBox.Text -AsPlainText -Force
        return [pscustomobject]@{AppId=$appBox.Text.Trim(); SecureKey=$secure}
    }
    finally {
        $keyBox.Clear()
        $appBox.Clear()
        $form.Dispose()
    }
}

function Invoke-OpenApi([string]$Path, $Body, [string]$Token) {
    # Allowlist exactly two read-only diagnostic operations.
    if ($Path -notin @('/oauth2/token', '/cloudphone/batchAdbInfo')) {
        Stop-Safely 'Операция не разрешена диагностическим клиентом.'
    }
    $request = [Net.HttpWebRequest]::Create('https://api.morelogin.com' + $Path)
    $request.Method = 'POST'
    $request.ContentType = 'application/json'
    $request.Accept = 'application/json'
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 25000
    $request.ReadWriteTimeout = 25000
    if ($Token) { $request.Headers['Authorization'] = 'Bearer ' + $Token }
    $jsonBody = $Body | ConvertTo-Json -Compress -Depth 5
    $bytes = [Text.Encoding]::UTF8.GetBytes($jsonBody)
    $jsonBody = $null
    $request.ContentLength = $bytes.Length
    $response = $null
    $reader = $null
    try {
        $stream = $request.GetRequestStream()
        try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        [Array]::Clear($bytes, 0, $bytes.Length)
        $response = $request.GetResponse()
        if ([int]$response.StatusCode -ne 200) { Stop-Safely 'Open API вернул неожиданный HTTP-статус. Перенаправления не разрешены.' }
        $reader = [IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8)
        $text = New-Object Text.StringBuilder
        $buffer = New-Object char[] 4096
        while (($read = $reader.Read($buffer, 0, $buffer.Length)) -gt 0) {
            if ($text.Length + $read -gt 2097152) { Stop-Safely 'Ответ Open API слишком большой.' }
            [void]$text.Append($buffer, 0, $read)
        }
        try { $payload = $text.ToString() | ConvertFrom-Json }
        catch { Stop-Safely 'Open API вернул неожиданный формат ответа.' }
        $code = Get-Field $payload 'code'
        if ($code -isnot [int] -and $code -isnot [long]) { Stop-Safely 'В ответе нет корректного кода результата.' }
        if ($code -eq 35002) { Stop-Safely 'MoreLogin 35002: APP ID/API Key не прошли проверку. Скопируйте полную пару из одного блока Open API. Ключ в чат не отправляйте.' }
        if ($code -eq 35005) { Stop-Safely 'MoreLogin 35005: операция запрещена. Проверьте активность участника и разрешённые IP у владельца команды.' }
        if ($code -eq 12002) { Stop-Safely 'MoreLogin 12002: команда не существует. Обратитесь в поддержку MoreLogin.' }
        if ($code -ne 0) {
            Stop-Safely ("MoreLogin вернул код {0}. Ответ сервиса скрыт для защиты секретов." -f $code)
        }
        return $payload
    }
    catch [Net.WebException] {
        $errorResponse = $_.Exception.Response
        $httpCode = 0
        if ($null -ne $errorResponse) {
            try { $httpCode = [int]$errorResponse.StatusCode } finally { $errorResponse.Dispose() }
        }
        if ($httpCode -eq 401 -or $httpCode -eq 403) {
            Stop-Safely ("Open API: HTTP {0}. Проверьте ключ, права аккаунта и разрешённые IP. Не отключайте ограничения команды." -f $httpCode)
        }
        if ($httpCode -gt 0) { Stop-Safely ("Open API: HTTP {0}. Ответ сервера скрыт для защиты ключей." -f $httpCode) }
        Stop-Safely 'Не удалось безопасно подключиться к Open API. Проверьте интернет, дату/время и TLS. Не отключайте проверку сертификатов.'
    }
    finally {
        if ($null -ne $bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
        if ($null -ne $reader) { $reader.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        $request.Headers.Remove('Authorization')
        $Body = $null
        $Token = $null
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
    stage='read_only_openapi_diagnostics'; implementation='windows_powershell'
    chat_automation_implemented=$false; created_at_utc=[DateTime]::UtcNow.ToString('o')
    authentication='not_checked'; phone_query='not_checked'
}
$exitCode = 0
$secureKey = $null
$key = $null
$body = $null
$pointer = [IntPtr]::Zero
$token = $null
$tokenResponse = $null
$currentStage = 'configuration'
try {
    $config = Read-Configuration
    if ($CheckFirstAdb) {
        . (Join-Path $PSScriptRoot 'adb-check.ps1')
        if ($InspectUi) { . (Join-Path $PSScriptRoot 'ui-inspect.ps1') }
        $adbExecutable = Select-AdbExecutable
        $report.adb_check = @{status='not_checked'}
    }
    Write-Host 'Проверка MoreLogin Open API на вашем ноутбуке.'
    Write-Host 'Секрет будет отправлен только на https://api.morelogin.com, не в GitHub и не в чат.'
    Write-Host 'Телефоны не запускаются/останавливаются. Сообщения не отправляются.'
    Write-Host 'Введите данные в отдельном окне MoreLogin Open API. Ключ в консоль не вставляйте.'
    $credentials = Read-CredentialsDialog
    $appId = $credentials.AppId
    $secureKey = $credentials.SecureKey
    $credentials = $null
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $pointer = [IntPtr]::Zero
    $body = @{client_id=$appId; client_secret=$key; grant_type='client_credentials'}
    $currentStage = 'authentication'
    Write-Host 'Проверяю авторизацию...'
    try {
        $tokenResponse = Invoke-OpenApi '/oauth2/token' $body ''
    }
    finally {
        if ($null -ne $body) { $body.client_secret = $null }
        $body = $null
        $key = $null
        if ($null -ne $secureKey) { $secureKey.Dispose(); $secureKey = $null }
    }
    $tokenData = Get-Field $tokenResponse 'data'
    $token = Get-Field $tokenData 'access_token'
    if ($token -isnot [string] -or [string]::IsNullOrWhiteSpace($token)) { Stop-Safely 'В ответе нет access_token. Продолжение остановлено.' }
    $report.authentication = 'ok'
    $lifetime = Get-Field $tokenData 'expires_in'
    if ($lifetime -is [int] -or $lifetime -is [long]) { $report.token_lifetime_seconds = $lifetime }
    $tokenResponse = $null
    $tokenData = $null
    Write-Host 'Авторизация успешна. Проверяю четыре телефона...'
    $currentStage = 'phone_query'
    $response = Invoke-OpenApi '/cloudphone/batchAdbInfo' @{envIds=@($config.phone_ids)} $token
    $entries = Get-Field $response 'data'
    if ($entries -isnot [array]) { Stop-Safely 'Неожиданный формат списка телефонов.' }
    foreach ($entry in $entries) {
        if ($entry -isnot [System.Management.Automation.PSCustomObject]) { Stop-Safely 'Некорректный элемент в списке телефонов.' }
    }
    $phones = @(Get-SafePhoneReport $config.phone_ids $entries)
    $report.phone_query = 'ok'
    $report.phones = $phones
    if ($CheckFirstAdb) {
        $currentStage = 'adb_check'
        $report.adb_check = Invoke-FirstAdbCheck $adbExecutable $config.phone_ids[0] $entries -InspectUi:$InspectUi
    }
    $entries = $null
    $response = $null
    $allReady = @($phones | Where-Object { -not $_.ready }).Count -eq 0
    $report.connection_parameters_available = $allReady
    foreach ($phone in $phones) {
        $summary = if ($phone.ready) { 'параметры ADB доступны' } else { $phone.issues -join ', ' }
        Write-Host ("  {0}: {1}" -f $phone.phone_id, $summary)
    }
    if (-not $CheckFirstAdb) { Write-Host 'Фактическое подключение к Android ещё НЕ проверялось. Сообщения НЕ отправлялись.' }
    if (-not $allReady) { $exitCode = 2 }
}
catch {
    $message = $script:SafeError
    if (-not $message) { $message = 'Диагностика остановлена из-за локальной ошибки. Сырые данные скрыты. Ключи в чат не отправляйте.' }
    if ($currentStage -eq 'authentication') { $report.authentication = 'failed' }
    if ($currentStage -eq 'phone_query') { $report.phone_query = 'failed' }
    if ($currentStage -eq 'adb_check') { $report.adb_check = @{status='failed'} }
    if ($InspectUi -and $script:UiForegroundProbe.Count -gt 0) { $report.ui_foreground_probe = @($script:UiForegroundProbe) }
    $report.failed_stage = $currentStage
    $report.error = $message
    Write-Host $message
    $exitCode = 1
}
finally {
    if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($null -ne $secureKey) { $secureKey.Dispose() }
    if ($null -ne $body) { $body.client_secret = $null }
    $body = $null; $key = $null; $token = $null; $tokenResponse = $null; $tokenData = $null
    $entries = $null; $response = $null
}
try {
    $directory = Split-Path -Parent ([IO.Path]::GetFullPath($ReportPath))
    [void][IO.Directory]::CreateDirectory($directory)
    $json = $report | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($ReportPath, $json, (New-Object Text.UTF8Encoding($true)))
    if ($InspectUi) { Write-Host 'Отчёт со структурой без текстов: reports\ui-diagnostic.json' }
    elseif ($CheckFirstAdb) { Write-Host 'Отчёт без секретов: reports\adb-diagnostic.json' }
    else { Write-Host 'Отчёт без ключей, токенов, паролей и адресов ADB: reports\openapi-diagnostic.json' }
}
catch {
    Write-Host 'Не удалось записать отчёт. Распакуйте проект в свою папку с правом записи.'
    $exitCode = 1
}
exit $exitCode
