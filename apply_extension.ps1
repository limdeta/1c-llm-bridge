# apply_extension.ps1 — применить расширение-исполнитель «ИИМост» к базе 1С.
# Единственное «ручное» действие, которое требуется от разработчика.
#
# Использование:
#   powershell -NoProfile -File apply_extension.ps1 -InfoBasePath "C:\Bases\МояБаза" -UserName "Администратор" -Password ""
#   (для серверной базы: -InfoBaseServer "srv" -InfoBaseRef "ИмяБазы")
#
# Требует: пользователь ИБ с правом входа в конфигуратор (обычно Администратор),
#          база свободна от сеансов (обновление идёт в монопольном режиме).

[CmdletBinding()]
param(
    [string]$InfoBasePath = "",
    [string]$InfoBaseServer = "",
    [string]$InfoBaseRef = "",
    [string]$UserName = "Администратор",
    [string]$Password = "",
    [switch]$Anonymous,
    [string]$V8Path = "",
    [string]$ExtensionFile = "",
    [string]$ExtensionName = "ИИМост"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ── путь к платформе ────────────────────────────────────────────────────────
if (-not $V8Path) {
    $found = Get-ChildItem @("C:\Program Files\1cv8\*\bin\1cv8.exe", "C:\Program Files (x86)\1cv8\*\bin\1cv8.exe") -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } -Descending |
        Select-Object -First 1
    if (-not $found) { Write-Error "1cv8.exe не найден. Укажите -V8Path"; exit 1 }
    $V8Path = $found.FullName
    Write-Host "Платформа: $V8Path"
}

# ── параметры соединения ────────────────────────────────────────────────────
$connArgs = @()
if ($InfoBaseServer -and $InfoBaseRef) {
    $connArgs += "/S`"$InfoBaseServer/$InfoBaseRef`""
} elseif ($InfoBasePath) {
    if (-not (Test-Path (Join-Path $InfoBasePath "1Cv8.1CD"))) {
        Write-Error "Информационная база не найдена: $InfoBasePath"
        exit 1
    }
    $connArgs += "/F`"$InfoBasePath`""
} else {
    Write-Error "Укажите -InfoBasePath (файловая база) или -InfoBaseServer + -InfoBaseRef (серверная)"
    exit 1
}
if (-not $Anonymous) {
    if ($UserName) { $connArgs += "/N`"$UserName`"" }
    if ($Password) { $connArgs += "/P`"$Password`"" }
}

# ── файл расширения ──────────────────────────────────────────────────────────
if (-not $ExtensionFile) { $ExtensionFile = Join-Path $PSScriptRoot "ИИМост.cfe" }
if (-not (Test-Path $ExtensionFile)) { Write-Error "Файл расширения не найден: $ExtensionFile"; exit 1 }

$log1 = Join-Path $env:TEMP "cfe_load.log"
$log2 = Join-Path $env:TEMP "cfe_update.log"

function Invoke-V8 {
    # Надёжный вызов 1cv8: ProcessStartInfo; аргументы уже содержат нужные кавычки — только join
    param([string[]]$ExtraArgs)
    $all = @("DESIGNER") + $connArgs + $ExtraArgs
    $argString = $all -join ' '
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $V8Path
    $psi.Arguments = $argString
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $p = [System.Diagnostics.Process]::Start($psi)
    $p.WaitForExit()
    return $p.ExitCode
}

Write-Host "Шаг 1/2: загрузка расширения '$ExtensionName'..."
$code1 = Invoke-V8 @("/LoadCfg`"$ExtensionFile`"", "-Extension`"$ExtensionName`"", "/Out`"$log1`"", "/DisableStartupDialogs")
if ($code1 -ne 0) {
    Get-Content $log1 -ErrorAction SilentlyContinue -Encoding UTF8 | Select-Object -Last 10
    Write-Error "Загрузка расширения не удалась (код $code1). База может быть занята сеансами."
    exit $code1
}

Write-Host "Шаг 2/2: обновление конфигурации базы данных (монопольный режим)..."
$code2 = Invoke-V8 @("/UpdateDBCfg", "-Extension`"$ExtensionName`"", "/Out`"$log2`"", "/DisableStartupDialogs")
if ($code2 -ne 0) {
    Get-Content $log2 -ErrorAction SilentlyContinue -Encoding UTF8 | Select-Object -Last 10
    Write-Error "Обновление конфигурации БД не удалось (код $code2)."
    exit $code2
}

Write-Host ""
Write-Host "[OK] Расширение '$ExtensionName' применено к базе." -ForegroundColor Green
Write-Host "Проверка: см. README.md, раздел «Быстрый старт», шаг 3 (команда check)."
