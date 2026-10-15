# Read-only direct ADB check for the first configured phone. Dot-sourced by openapi.ps1.
function Select-AdbExecutable {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object Windows.Forms.OpenFileDialog
    $dialog.Title = 'Выберите adb.exe из официального Android SDK Platform-Tools'
    $dialog.Filter = 'Android Debug Bridge (adb.exe)|adb.exe'
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false
    try {
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { Stop-Safely 'Выбор adb.exe отменён.' }
        $path = $dialog.FileName
        if ([IO.Path]::GetFileName($path) -ine 'adb.exe') { Stop-Safely 'Выберите именно adb.exe из распакованной папки platform-tools.' }
        return $path
    }
    finally { $dialog.Dispose() }
}

function Invoke-AdbProcess([string]$Executable, [string[]]$CommandArgs, [string]$InputText = '') {
    # No cmd.exe or arbitrary shell expansion. All CLI tokens have a strict alphabet.
    foreach ($arg in $CommandArgs) {
        if ($arg -notmatch '^[A-Za-z0-9_.:/\-]+$') { Stop-Safely 'Небезопасный формат аргумента ADB. Выполнение остановлено.' }
    }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Executable
    $start.Arguments = $CommandArgs -join ' '
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.RedirectStandardInput = $true
    # Keep the ADB server local. Never bind it publicly or kill an existing server.
    $start.EnvironmentVariables['ADB_SERVER_SOCKET'] = 'tcp:localhost:5037'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $outTask = $process.StandardOutput.ReadToEndAsync()
        $errTask = $process.StandardError.ReadToEndAsync()
        if ($InputText) { $process.StandardInput.WriteLine($InputText) }
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(25000)) {
            try { $process.Kill() } catch {}
            Stop-Safely 'ADB не ответил за 25 секунд. Проверьте сеть и состояние телефона; параметры подключения могли истечь.'
        }
        $stdout = $outTask.GetAwaiter().GetResult()
        # Consume stderr but do not publish it: it may include endpoint/password.
        $stderr = $errTask.GetAwaiter().GetResult()
        return @{exit_code=$process.ExitCode; stdout=$stdout}
    }
    catch {
        if ($script:SafeError) { throw }
        Stop-Safely 'Не удалось выполнить adb.exe. Проверьте, что рядом остались DLL из platform-tools и Windows разрешает запуск.'
    }
    finally {
        $stderr = $null
        $process.Dispose()
    }
}

function Invoke-FirstAdbCheck([string]$Executable, [string]$PhoneId, $Entries, [switch]$InspectUi) {
    $matching = @($Entries | Where-Object { [string](Get-Field $_ 'id') -ceq $PhoneId })
    if ($matching.Count -ne 1) { Stop-Safely 'Нет однозначных параметров первого телефона.' }
    $entry = $matching[0]
    if ((Get-Flag (Get-Field $entry 'supportAdb')) -ne $true -or
        (Get-Flag (Get-Field $entry 'enableAdb')) -ne $true -or
        (Get-Field $entry 'envStatus') -ne 4) {
        Stop-Safely 'Первый телефон должен быть включён, поддерживать ADB и иметь включённый ADB.'
    }
    if (Get-Field $entry 'command') { Stop-Safely 'Первый телефон требует SSH. Эта проверка предназначена только для direct; SSH-команды автоматически не выполняются.' }
    $ipText = [string](Get-Field $entry 'adbIp')
    $ip = $null
    if (-not [Net.IPAddress]::TryParse($ipText, [ref]$ip) -or $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
        Stop-Safely 'Для этой версии нужен IPv4-адрес прямого ADB из MoreLogin. Другой формат не будет исполняться.'
    }
    $portText = [string](Get-Field $entry 'adbPort')
    $port = 0
    if ($portText -notmatch '^[0-9]{1,5}$' -or -not [int]::TryParse($portText, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        Stop-Safely 'MoreLogin вернул некорректный порт ADB.'
    }
    $password = [string](Get-Field $entry 'adbPassword')
    $serial = $ip.ToString() + ':' + $port
    try {
        Write-Host 'Проверяю adb.exe...'
        $versionCheck = Invoke-AdbProcess $Executable @('version')
        if ($versionCheck.exit_code -ne 0) { Stop-Safely 'adb.exe не прошёл проверку version.' }
        Write-Host ('Подключаю первый телефон {0}...' -f $PhoneId)
        $connect = Invoke-AdbProcess $Executable @('connect', $serial)
        if ($connect.exit_code -ne 0 -or $connect.stdout -notmatch '(?i)(already )?connected to') {
            Stop-Safely 'ADB не смог подключиться к первому телефону. Возможны сетевые ограничения или истёкшие параметры. Сырые адреса скрыты.'
        }
        # Idempotent: first test an existing authorized shell before sending CODE.
        $script:AdbProbeDiagnostics = [ordered]@{authentication_attempted=$false}
        $probe = Invoke-AdbProcess $Executable @('-s', $serial, 'shell', 'getprop', 'ro.build.version.release')
        $script:AdbProbeDiagnostics.probe_before_auth_exit_code = $probe.exit_code
        $android = $probe.stdout.Trim()
        $shellReady = $probe.exit_code -eq 0 -and $android -match '^[0-9]+(\.[0-9]+){0,3}$'
        $authMode = 'existing_session'
        if (-not $shellReady) {
            if ($password -notmatch '^[A-Za-z0-9_-]{1,256}$') {
                Stop-Safely 'Для новой авторизации код ADB имеет неподдерживаемый формат. Его содержимое скрыто; произвольные shell-команды не выполняются.'
            }
            $script:AdbProbeDiagnostics.authentication_attempted = $true
            $authMode = 'code_then_probe'
            # Official MoreLogin direct authentication. Safe single-token CODE may
            # briefly be visible to local process monitoring; never log arguments.
            $auth = Invoke-AdbProcess $Executable @('-s', $serial, 'shell', $password) 'exit'
            $script:AdbProbeDiagnostics.auth_command_exit_code = $auth.exit_code
            # The auth command's exit code alone does not prove whether the session
            # is authorized. The subsequent read-only Android probe is decisive.
            $probe = Invoke-AdbProcess $Executable @('-s', $serial, 'shell', 'getprop', 'ro.build.version.release')
            $script:AdbProbeDiagnostics.probe_after_auth_exit_code = $probe.exit_code
            $android = $probe.stdout.Trim()
            $shellReady = $probe.exit_code -eq 0 -and $android -match '^[0-9]+(\.[0-9]+){0,3}$'
        }
        $password = $null
        if (-not $shellReady) {
            Stop-Safely 'Не удалось подтвердить Android shell после проверки текущей сессии и штатной авторизации. Причина по одному коду не установлена. Передайте отчёт с adb_probe_diagnostics, без секретов.'
        }
        $result = [ordered]@{status='ok'; phone_id=$PhoneId; connection_mode='direct'; android_version=$android; messages_sent=0; chat_content_read=$false}
        $result.authentication_mode = $authMode
        $result.adb_probe_diagnostics = $script:AdbProbeDiagnostics
        $screen = Invoke-AdbProcess $Executable @('-s', $serial, 'shell', 'wm', 'size')
        if ($screen.exit_code -eq 0 -and $screen.stdout -match '(?m)Physical size:\s*([0-9]{2,5})x([0-9]{2,5})') {
            $result.physical_screen_size = $Matches[1] + 'x' + $Matches[2]
        }
        # App names only. No message database, screenshot, UI dump or chat text.
        $packages = Invoke-AdbProcess $Executable @('-s', $serial, 'shell', 'pm', 'list', 'packages')
        $candidates = @()
        if ($packages.exit_code -eq 0) {
            foreach ($line in ($packages.stdout -split '[\r\n]+')) {
                if ($line -match '^package:([A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+)$') {
                    $name = $Matches[1]
                    if ($name -match '(?i)(drug|vokrug|mobstudio)') { $candidates += $name }
                }
            }
        }
        $result.app_package_candidates = @($candidates | Select-Object -Unique)
        if ($InspectUi) {
            $result.chat_content_read = $true
            $result.ui_inspection = Invoke-UiInspection $Executable $serial
            Write-Host 'Текст экрана мог присутствовать в исходном XML, но в отчёт не экспортировался.'
        }
        Write-Host ('Android {0}: связь с первым телефоном подтверждена.' -f $android)
        if (-not $InspectUi) { Write-Host 'Переписки не читались.' }
        Write-Host 'Другие три телефона не подключались. Нажатия и отправка не выполнялись.'
        return $result
    }
    finally {
        $password = $null; $serial = $null; $entry = $null; $matching = $null
        $connect = $null; $auth = $null; $probe = $null; $packages = $null
    }
}
