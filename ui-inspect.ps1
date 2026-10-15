# Structural UI diagnostics only. Never tap, type or send.
function Get-ForegroundPackage([string]$Executable, [string]$Serial) {
    $focus = Invoke-AdbProcess $Executable @('-s', $Serial, 'shell', 'dumpsys', 'window', 'windows')
    if ($focus.exit_code -ne 0 -or $focus.stdout -notmatch '(?m)mCurrentFocus=Window\{[^\r\n}]*?\s([A-Za-z0-9_.]+)/') {
        Stop-Safely 'Не удалось определить приложение на переднем плане. Откройте ДругВокруг на первом телефоне.'
    }
    return $Matches[1]
}

function Get-SafeResourceId([string]$Value) {
    if ($Value -match '^[A-Za-z0-9_.]+:id/[A-Za-z0-9_]+$') { return $Value }
    return $null
}

function ConvertTo-SafeUiReport([string]$XmlText) {
    if ([string]::IsNullOrWhiteSpace($XmlText) -or $XmlText.Length -gt 2097152) {
        Stop-Safely 'Пустая или слишком большая структура экрана. Сырые данные не сохраняются.'
    }
    $settings = New-Object Xml.XmlReaderSettings
    $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 2097152
    $stringReader = New-Object IO.StringReader($XmlText)
    $reader = $null
    try {
        $reader = [Xml.XmlReader]::Create($stringReader, $settings)
        $document = New-Object Xml.XmlDocument
        $document.XmlResolver = $null
        try { $document.Load($reader) }
        catch { Stop-Safely 'Не удалось разобрать XML интерфейса. Текст XML скрыт.' }
        if ($null -eq $document.DocumentElement -or $document.DocumentElement.Name -ne 'hierarchy') {
            Stop-Safely 'Неожиданный формат структуры Android.'
        }
        $nodes = @($document.SelectNodes('//node[@package="drug.vokrug"]'))
        if ($nodes.Count -eq 0) { Stop-Safely 'В структуре нет элементов drug.vokrug. Убедитесь, что на первом телефоне открыт тестовый диалог.' }
        $safe = @()
        $limit = [Math]::Min(512, $nodes.Count)
        for ($i = 0; $i -lt $limit; $i++) {
            $node = $nodes[$i]
            $class = $node.GetAttribute('class')
            if ($class -notmatch '^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$') { $class = $null }
            $bounds = $node.GetAttribute('bounds')
            if ($bounds -notmatch '^\[[0-9]{1,5},[0-9]{1,5}\]\[[0-9]{1,5},[0-9]{1,5}\]$') { $bounds = $null }
            $parentId = $null
            if ($node.ParentNode -is [Xml.XmlElement]) { $parentId = Get-SafeResourceId $node.ParentNode.GetAttribute('resource-id') }
            # Only recognize static UI labels. Never export arbitrary text or descriptions.
            $hint = $null
            $description = $node.GetAttribute('content-desc')
            if ($description -in @('Отправить', 'Отправить сообщение', 'Send', 'Send message')) { $hint = 'send_label' }
            elseif ($description -in @('Назад', 'Back')) { $hint = 'back_label' }
            elseif ($class -eq 'android.widget.EditText') { $hint = 'editable_field' }
            $safe += [pscustomobject]@{
                node_index=$i
                resource_id=(Get-SafeResourceId $node.GetAttribute('resource-id'))
                parent_resource_id=$parentId
                class=$class
                bounds=$bounds
                clickable=($node.GetAttribute('clickable') -eq 'true')
                long_clickable=($node.GetAttribute('long-clickable') -eq 'true')
                enabled=($node.GetAttribute('enabled') -eq 'true')
                focusable=($node.GetAttribute('focusable') -eq 'true')
                focused=($node.GetAttribute('focused') -eq 'true')
                scrollable=($node.GetAttribute('scrollable') -eq 'true')
                has_text=(-not [string]::IsNullOrEmpty($node.GetAttribute('text')))
                has_content_description=(-not [string]::IsNullOrEmpty($description))
                semantic_hint=$hint
            }
        }
        return [ordered]@{
            status='ok'; app_package='drug.vokrug'; node_count=$nodes.Count
            exported_node_count=$safe.Count; truncated=($nodes.Count -gt $limit)
            text_values_exported=$false; content_description_values_exported=$false
            nodes=@($safe)
        }
    }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        $stringReader.Dispose()
        $document = $null
        $XmlText = $null
    }
}

function Invoke-UiInspection([string]$Executable, [string]$Serial) {
    if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') {
        Stop-Safely 'На первом телефоне активно не drug.vokrug. Откройте тестовый диалог и повторите проверку.'
    }
    # A unique short-lived file exists only on the Android phone; never on the laptop.
    $dumpPath = '/sdcard/dvk_ui_diag_' + [Guid]::NewGuid().ToString('N') + '.xml'
    $xml = $null
    try {
        Write-Host 'Считываю структуру открытого экрана без нажатий и отправки...'
        $dump = Invoke-AdbProcess $Executable @('-s', $Serial, 'shell', 'uiautomator', 'dump', $dumpPath)
        if ($dump.exit_code -ne 0) { Stop-Safely 'Android не смог получить структуру интерфейса. Закройте всплывающие окна и попробуйте снова.' }
        $read = Invoke-AdbProcess $Executable @('-s', $Serial, 'shell', 'cat', $dumpPath)
        if ($read.exit_code -ne 0) { Stop-Safely 'Не удалось прочитать временную структуру экрана.' }
        $xml = $read.stdout
        if ((Get-ForegroundPackage $Executable $Serial) -cne 'drug.vokrug') {
            Stop-Safely 'Приложение на переднем плане изменилось. Результат не используется.'
        }
        $safe = ConvertTo-SafeUiReport $xml
    }
    finally {
        $xml = $null; $read = $null; $dump = $null
        # Delete raw XML even when collection/parsing fails. Do not delete other files.
        $removed = Invoke-AdbProcess $Executable @('-s', $Serial, 'shell', 'rm', '-f', $dumpPath)
        if ($removed.exit_code -ne 0) {
            Stop-Safely 'Не удалось удалить временный XML на телефоне. Он может содержать текст экрана; не публикуйте его. Очистку нужно завершить перед повторной проверкой.'
        }
    }
    $safe.raw_dump_deleted = $true
    Write-Host ('Получено технических элементов: {0}. Тексты исключены из отчёта.' -f $safe.exported_node_count)
    return $safe
}
