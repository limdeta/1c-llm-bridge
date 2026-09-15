# check_ps_bom.ps1 — проверка и восстановление BOM в .ps1
#
# Зачем: PowerShell 5.1 читает .ps1 без BOM как ANSI, и вся кириллица в скрипте
# превращается в мусор («Unexpected token» на первой же русской строке). Многие
# редакторы и инструменты правки файлов BOM не сохраняют, поэтому проверять нужно
# регулярно — особенно после правок комментариев.
#
# Использование:
#   powershell -NoProfile -File tools\check_ps_bom.ps1           # только проверка
#   powershell -NoProfile -File tools\check_ps_bom.ps1 -Fix      # добавить BOM, где нет

[CmdletBinding()]
param(
    [switch]$Fix,
    [string]$Root = ""
)

# $PSScriptRoot в блоке param недоступен в PS 5.1 — считаем путь в теле скрипта
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }

$utf8Bom = [byte[]](0xEF, 0xBB, 0xBF)
$skip = @('\.internal\', '\cc-1c-skills\', '\.venv\', '\src\onec-cs\obj\')

$files = Get-ChildItem $Root -Recurse -Filter *.ps1 -File | Where-Object {
    $p = $_.FullName
    -not ($skip | Where-Object { $p -like "*$_*" })
}

$bad = @()
foreach ($f in $files) {
    $head = [byte[]](Get-Content $f.FullName -Encoding Byte -TotalCount 3)
    $hasBom = ($head.Length -eq 3 -and $head[0] -eq $utf8Bom[0] -and $head[1] -eq $utf8Bom[1] -and $head[2] -eq $utf8Bom[2])
    if (-not $hasBom) {
        $bad += $f
        if ($Fix) {
            $text = Get-Content $f.FullName -Raw -Encoding UTF8
            Set-Content $f.FullName -Value $text -Encoding UTF8 -NoNewline
            Write-Host "[FIX] BOM добавлен: $($f.FullName.Substring($Root.Length + 1))"
        } else {
            Write-Host "[BAD] нет BOM: $($f.FullName.Substring($Root.Length + 1))" -ForegroundColor Yellow
        }
    }
}

if ($bad.Count -eq 0) {
    Write-Host "[OK] BOM на месте у всех $($files.Count) файлов .ps1"
    exit 0
}

if (-not $Fix) {
    Write-Host ""
    Write-Host "Запустите с -Fix, чтобы починить: powershell -NoProfile -File tools\check_ps_bom.ps1 -Fix"
    exit 1
}

Write-Host "[OK] Исправлено файлов: $($bad.Count)"
exit 0
