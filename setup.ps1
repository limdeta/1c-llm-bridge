# setup.ps1 — диагностика окружения и подготовка моста к работе.
# Запустите один раз: powershell -NoProfile -File setup.ps1
#
# Что делает:
#   1. Находит платформу 1С (1cv8.exe)
#   2. Регистрирует COM-коннектор (V83.COMConnector) — без прав администратора
#   3. Проверяет подключение и исполнитель (расширение) через onec.ps1
#   4. Проверяет Python (опционально, для MCP-режима)
#   5. Печатает итог и следующие шаги

[CmdletBinding()]
param(
    [string]$ConnectionString = $env:ONEC_CONNECTION_STRING,
    [string]$V8Path = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = $PSScriptRoot

Write-Host "=== 1/5 Платформа 1С ===" -ForegroundColor Cyan
if (-not $V8Path) {
    $found = Get-ChildItem @("C:\Program Files\1cv8\*\bin\1cv8.exe", "C:\Program Files (x86)\1cv8\*\bin\1cv8.exe") -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } -Descending |
        Select-Object -First 1
    if ($found) { $V8Path = $found.FullName }
}
if (-not $V8Path) {
    Write-Host "[FAIL] 1cv8.exe не найден. Установите платформу 1С:Предприятие 8.3." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Платформа: $V8Path"

Write-Host "`n=== 2/5 Регистрация COM-коннектора ===" -ForegroundColor Cyan
$comScript = Join-Path $root "bridge\setup_com.ps1"
if (Test-Path $comScript) {
    # Bypass — только для случая, когда локальная политика машины ограничивает запуск скриптов.
    # Политика домена (GPO) имеет приоритет и этим флагом не обходится.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $comScript
} else {
    try {
        $c = New-Object -ComObject V83.COMConnector
        Write-Host "[OK] V83.COMConnector доступен"
    } catch {
        Write-Host "[FAIL] COM-коннектор не зарегистрирован: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "       Запустите от администратора: regsvr32 `"$(Split-Path $V8Path)\comcntr.dll`""
        exit 1
    }
}

Write-Host "`n=== 3/5 Строка соединения ===" -ForegroundColor Cyan
if (-not $ConnectionString) {
    Write-Host "Строка соединения не задана (env ONEC_CONNECTION_STRING)."
    Write-Host "Пример для файловой базы: File=`"C:\Bases\МояБаза`";Usr=`"Администратор`";Pwd=`"`""
    Write-Host "Пример для серверной:    Srvr=`"server`";Ref=`"МояБаза`";Usr=`"Имя`";Pwd=`"`""
    Write-Host "Задайте её и запустите setup повторно, либо переходите к шагу проверки вручную."
} else {
    $ps = Join-Path $root "bridge\onec.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ps -ConnectionString $ConnectionString check
}

Write-Host "`n=== 4/5 Ограничения среды (Windows) ===" -ForegroundColor Cyan
$ep = Get-ExecutionPolicy -List -ErrorAction SilentlyContinue | Where-Object { $_.Scope -in @("MachinePolicy", "UserPolicy", "LocalMachine", "CurrentUser") }
$ep | ForEach-Object { Write-Host "  ExecutionPolicy $($_.Scope): $($_.ExecutionPolicy)" }
$blocked = $ep | Where-Object { $_.ExecutionPolicy -in @("Restricted", "AllSigned") }
if ($blocked) {
    Write-Host "[WARN] Запуск PowerShell-скриптов ограничен политикой ($($blocked.ExecutionPolicy -join ', '))." -ForegroundColor Yellow
    Write-Host "       Если это политика домена — обратитесь к администратору."
    Write-Host "       Если exe разрешены, доступен bridge\bin\onec.exe (C#-мост, без PowerShell)."
} else {
    Write-Host "[OK] Запуск PowerShell-скриптов не ограничен политикой"
}
try {
    $al = Get-AppLockerPolicy -Effective -ErrorAction Stop
    $rules = $al.RuleCollections
    Write-Host "[INFO] AppLocker активен: $($rules.Count) коллекций правил (Exe: $($rules.ExeRules.Count), Script: $($rules.ScriptRules.Count))"
    if ($rules.ScriptRules.Count -gt 0) { Write-Host "       Запуск скриптов ограничен — доступен bridge\bin\onec.exe" -ForegroundColor Yellow }
} catch {
    Write-Host "[OK] AppLocker не настроен (или недоступен)"
}
try {
    $c = New-Object -ComObject V83.COMConnector
    Write-Host "[OK] COM V83.COMConnector доступен"
} catch {
    Write-Host "[FAIL] COM-коннектор недоступен: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "       Возможно, политика запрещает COM-компоненты 1С — это решает администратор."
}

Write-Host "`n=== 5/5 Python (опционально, для MCP-режима) ===" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    Write-Host "[OK] Python найден: $($py.Source)"
    Write-Host "     MCP-сервер: .\.venv\Scripts\python bridge\mcp_server.py (см. README)"
} else {
    Write-Host "[INFO] Python не найден. Мост работает на чистом PowerShell (bridge\onec.ps1) или C# (bridge\bin\onec.exe);"
    Write-Host "       MCP-режим недоступен, пока не установлен Python."
}

Write-Host ""
Write-Host "=== ИТОГ ===" -ForegroundColor Cyan
Write-Host "1. Расширение-исполнитель к базе применить один раз:" -ForegroundColor Yellow
Write-Host "   powershell -NoProfile -File apply_extension.ps1 -InfoBasePath `"C:\Bases\МояБаза`""
Write-Host "2. Дать ИИ-агенту строку соединения (env ONEC_CONNECTION_STRING или параметр)."
Write-Host "3. Пользователь ИБ должен иметь роль с правами на данные (см. README, раздел «Безопасность»)."
Write-Host "4. Если скрипты или COM ограничены политикой — вопрос решает администратор (см. README)."

