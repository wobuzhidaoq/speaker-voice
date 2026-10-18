# Установка Speaker Voice для Claude Code на Windows.
# Запуск в PowerShell:
#   irm https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$repo = "https://raw.githubusercontent.com/wobuzhidaoq/speaker-voice/main"
$dir = Join-Path $HOME ".claude\speaker-voice"
$settingsPath = Join-Path $HOME ".claude\settings.json"

function Find-Py {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @("$env:WINDIR\py.exe", "$env:LOCALAPPDATA\Programs\Python\Launcher\py.exe")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "1/4 Проверяю Python..." -ForegroundColor Cyan
$py = Find-Py
if (-not $py) {
    Write-Host "    Python не найден, устанавливаю через winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    $py = Find-Py
    if (-not $py) { throw "Не удалось найти Python после установки. Установите его с https://www.python.org/downloads/ и запустите скрипт снова." }
}
& $py --version

Write-Host "2/4 Устанавливаю нейронный голос (edge-tts)..." -ForegroundColor Cyan
& $py -m pip install --user --upgrade --quiet edge-tts

Write-Host "3/4 Скачиваю speak.py в $dir ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest "$repo/claude-code-hook/speak.py" -OutFile (Join-Path $dir "speak.py") -UseBasicParsing

Write-Host "4/4 Подключаю хуки в $settingsPath ..." -ForegroundColor Cyan
$command = "py " + ((Join-Path $dir "speak.py") -replace "\\", "/")
if (Test-Path $settingsPath) {
    $raw = [IO.File]::ReadAllText($settingsPath)
    try { $settings = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { [pscustomobject]@{} } }
    catch { throw "В $settingsPath ошибка JSON — исправьте файл (часто это два блока { } подряд) и запустите скрипт снова." }
    Copy-Item $settingsPath "$settingsPath.bak" -Force
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $settingsPath) | Out-Null
    $settings = [pscustomobject]@{}
}
if (-not $settings.PSObject.Properties["hooks"]) {
    $settings | Add-Member -NotePropertyName hooks -NotePropertyValue ([pscustomobject]@{})
}
foreach ($event in @("UserPromptSubmit", "PreToolUse", "Stop", "Notification")) {
    $groups = @()
    if ($settings.hooks.PSObject.Properties[$event]) {
        # убираем старые записи speak.py, чужие хуки оставляем
        $groups = @($settings.hooks.$event | Where-Object { -not ($_.hooks | Where-Object { $_.command -like "*speak.py*" }) })
    }
    $group = [pscustomobject]@{ hooks = @([pscustomobject]@{ type = "command"; command = $command }) }
    if ($event -eq "PreToolUse") { $group | Add-Member -NotePropertyName matcher -NotePropertyValue "*" }
    $groups += $group
    $settings.hooks | Add-Member -NotePropertyName $event -NotePropertyValue $groups -Force
}
# UTF-8 без BOM — иначе Claude Code не прочитает файл
[IO.File]::WriteAllText($settingsPath, ($settings | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))

Write-Host ""
Write-Host "Готово! Проверка голоса..." -ForegroundColor Green
& $py (Join-Path $dir "speak.py") "Привет! Я буду читать статусы и отчёты Claude."
Write-Host "Перезапустите Claude Code — и он заговорит." -ForegroundColor Green
