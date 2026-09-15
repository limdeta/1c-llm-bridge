# onec.ps1 — мост к 1С через COM (V83.COMConnector) на чистом PowerShell.
# Работает БЕЗ Python. Требует: Windows + платформа 1С + зарегистрированный
# COM-коннектор (bridge/setup_com.ps1) + применённое расширение-исполнитель.
#
# ВАЖНО: в PS 5.1 COM-объект, возвращённый из ФУНКЦИИ, теряет диспетчеризацию
# (DISP_E_UNKNOWNNAME), поэтому все COM-цепочки здесь инлайн (см. docs/core/PITFALLS.md #43).
#
# Использование:
#   powershell -NoProfile -File onec.ps1 -ConnectionString 'File="C:\base";Usr="Имя";Pwd=""' info
#   powershell -NoProfile -File onec.ps1 -ConnectionString '...' exec 'Результат = 40 + 2;'
#   powershell -NoProfile -File onec.ps1 -ConnectionString '...' query "ВЫБРАТЬ 1 КАК А"
#   powershell -NoProfile -File onec.ps1 -ConnectionString '...' meta catalogs
#   powershell -NoProfile -File onec.ps1 -ConnectionString '...' check
#
# Подкоманды: info | exec <код> | query <текст> | meta [вид] | check

[CmdletBinding()]
param(
    [string]$ConnectionString = $env:ONEC_CONNECTION_STRING,
    [Parameter(Position = 0)][string]$Command = "info",
    [Parameter(Position = 1)][string]$Arg1 = "",
    [string]$ExecutorExt = $env:ONEC_EXECUTOR_EXT
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $ExecutorExt) { $ExecutorExt = "ИИМост_ИсполнительКода" }
$bf = [System.Reflection.BindingFlags]

if (-not $ConnectionString) {
    Write-Error "Нет строки соединения: -ConnectionString или env ONEC_CONNECTION_STRING"
    exit 1
}

function ConvertTo-PyValue {
    # Приводит COM-результат к простому значению (число/строка/дата)
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [bool] -or $Value -is [string]) { return $Value }
    if ($Value -is [datetime]) { return $Value.ToString("yyyy-MM-dd HH:mm:ss") }
    if ($Value -is [array]) { return $Value[0] }  # (результат, код)
    if ($Value -is [System.__ComObject]) {
        try { return $script:Conn.GetType().InvokeMember("XMLСтрока", $bf::InvokeMethod, $null, $script:Conn, @($Value)) }
        catch { return $Value.ToString() }
    }
    return $Value.ToString()
}

# ── соединение ──────────────────────────────────────────────────────────────
$script:Connector = New-Object -ComObject V83.COMConnector
$script:Conn = $script:Connector.Connect($ConnectionString)
if ($null -eq $script:Conn) { Write-Error "Не удалось подключиться к 1С"; exit 1 }

switch ($Command) {

    "check" {
        # Диагностика: подключение, исполнитель, метаданные
        $ok = $true
        try {
            $mgr = $script:Conn.GetType().InvokeMember("Обработки", $bf::GetProperty, $null, $script:Conn, $null)
            $dpMgr = $mgr.GetType().InvokeMember($ExecutorExt, $bf::GetProperty, $null, $mgr, $null)
            $dp = $dpMgr.GetType().InvokeMember("Создать", $bf::InvokeMethod, $null, $dpMgr, @())
            $r = $dp.GetType().InvokeMember("ВыполнитьКод", $bf::InvokeMethod, $null, $dp, @('Результат = 6 * 7;'))
            Write-Host "[OK] Исполнитель '$ExecutorExt': 6*7 = $(ConvertTo-PyValue $r)"
        } catch {
            $ok = $false
            Write-Host "[FAIL] Исполнитель '$ExecutorExt' недоступен: $($_.Exception.Message)"
            Write-Host "       Примените расширение: powershell -File apply_extension.ps1"
        }
        try {
            $q = $script:Conn.NewObject("Запрос")
            $q.GetType().InvokeMember("Текст", $bf::SetProperty, $null, $q, @('ВЫБРАТЬ 1 КАК А'))
            $res = $q.GetType().InvokeMember("Выполнить", $bf::InvokeMethod, $null, $q, @())
            $tbl = $res.GetType().InvokeMember("Выгрузить", $bf::InvokeMethod, $null, $res, @())
            $n = $tbl.GetType().InvokeMember("Количество", $bf::InvokeMethod, $null, $tbl, @())
            Write-Host "[OK] Запросы работают"
        } catch { $ok = $false; Write-Host "[FAIL] Запросы: $($_.Exception.Message)" }
        if ($ok) { Write-Host "[OK] Мост готов к работе" } else { exit 1 }
    }

    "info" {
        $mgr = $script:Conn.GetType().InvokeMember("Обработки", $bf::GetProperty, $null, $script:Conn, $null)
        $dpMgr = $mgr.GetType().InvokeMember($ExecutorExt, $bf::GetProperty, $null, $mgr, $null)
        $dp = $dpMgr.GetType().InvokeMember("Создать", $bf::InvokeMethod, $null, $dpMgr, @())
        $ver = ConvertTo-PyValue ($dp.GetType().InvokeMember("ВыполнитьКод", $bf::InvokeMethod, $null, $dp, @('СИ = Новый СистемнаяИнформация; Результат = СИ.ВерсияПриложения;')))
        $md = $script:Conn.GetType().InvokeMember("Метаданные", $bf::GetProperty, $null, $script:Conn, $null)
        $cfg = $md.GetType().InvokeMember("Имя", $bf::GetProperty, $null, $md, $null)
        [pscustomobject]@{ connected = $true; configuration = $cfg; platform_version = $ver; connection = $ConnectionString } |
            ConvertTo-Json -Depth 3
    }

    "exec" {
        if (-not $Arg1) { Write-Error "exec: нужен код"; exit 1 }
        $mgr = $script:Conn.GetType().InvokeMember("Обработки", $bf::GetProperty, $null, $script:Conn, $null)
        $dpMgr = $mgr.GetType().InvokeMember($ExecutorExt, $bf::GetProperty, $null, $mgr, $null)
        $dp = $dpMgr.GetType().InvokeMember("Создать", $bf::InvokeMethod, $null, $dpMgr, @())
        $r = ConvertTo-PyValue ($dp.GetType().InvokeMember("ВыполнитьКод", $bf::InvokeMethod, $null, $dp, @($Arg1)))
        Write-Output $r
    }

    "query" {
        if (-not $Arg1) { Write-Error "query: нужен текст запроса"; exit 1 }
        $q = $script:Conn.NewObject("Запрос")
        $q.GetType().InvokeMember("Текст", $bf::SetProperty, $null, $q, @($Arg1))
        $res = $q.GetType().InvokeMember("Выполнить", $bf::InvokeMethod, $null, $q, @())
        $tbl = $res.GetType().InvokeMember("Выгрузить", $bf::InvokeMethod, $null, $res, @())
        $cols = $tbl.GetType().InvokeMember("Колонки", $bf::GetProperty, $null, $tbl, $null)
        $colCount = $cols.GetType().InvokeMember("Количество", $bf::InvokeMethod, $null, $cols, @())
        $columns = @()
        for ($i = 0; $i -lt $colCount; $i++) {
            $c = $cols.GetType().InvokeMember("Получить", $bf::InvokeMethod, $null, $cols, @($i))
            $columns += $c.GetType().InvokeMember("Имя", $bf::GetProperty, $null, $c, $null)
        }
        $rows = @()
        $n = $tbl.GetType().InvokeMember("Количество", $bf::InvokeMethod, $null, $tbl, @())
        for ($i = 0; $i -lt $n; $i++) {
            $row = $tbl.GetType().InvokeMember("Получить", $bf::InvokeMethod, $null, $tbl, @($i))
            $vals = @()
            for ($j = 0; $j -lt $colCount; $j++) {
                $vals += ConvertTo-PyValue ($row.GetType().InvokeMember("Получить", $bf::InvokeMethod, $null, $row, @($j)))
            }
            $rows += ,@($vals)
        }
        [pscustomobject]@{ columns = $columns; rows = $rows; row_count = $rows.Count; total_rows = $n; truncated = $false } |
            ConvertTo-Json -Depth 5
    }

    "meta" {
        $md = $script:Conn.GetType().InvokeMember("Метаданные", $bf::GetProperty, $null, $script:Conn, $null)
        $kinds = @{
            catalogs = "Справочники"; documents = "Документы"; enums = "Перечисления";
            informationregisters = "РегистрыСведений"; accumulationregisters = "РегистрыНакопления";
            accountingregisters = "РегистрыБухгалтерии"; chartsofaccounts = "ПланыСчетов";
            reports = "Отчеты"; dataprocessors = "Обработки"
        }
        $result = @{}
        $selected = if ($Arg1 -and $kinds.ContainsKey($Arg1)) { @{ $Arg1 = $kinds[$Arg1] } } else { $kinds }
        foreach ($k in $selected.Keys) {
            $coll = $md.GetType().InvokeMember($selected[$k], $bf::GetProperty, $null, $md, $null)
            $names = @()
            $cnt = $coll.GetType().InvokeMember("Количество", $bf::InvokeMethod, $null, $coll, @())
            for ($i = 0; $i -lt $cnt; $i++) {
                $o = $coll.GetType().InvokeMember("Получить", $bf::InvokeMethod, $null, $coll, @($i))
                $names += $o.GetType().InvokeMember("Имя", $bf::GetProperty, $null, $o, $null)
            }
            $result[$k] = $names
        }
        [pscustomobject]@{ metadata = $result } | ConvertTo-Json -Depth 4
    }

    default { Write-Error "Неизвестная команда: $Command (info|exec|query|meta|check)"; exit 1 }
}
