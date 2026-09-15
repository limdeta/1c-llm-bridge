# remote.ps1 — удалённый режим: вызов моста onec.ps1 на рабочей машине через SSH.
#
# Мост (COM) обязан работать там, где установлена 1С (рабочая машина). ИИ может быть
# где угодно. SSH-доступ на рабочую машину — всё, что нужно; открывать порты не требуется:
# каждая операция выполняется на удалённой машине, результат возвращается по SSH.
#
# Использование (с домашней машины, где ИИ):
#   $env:ONEC_SSH = "<пользователь>@<рабочая-машина>"     # ssh-таргет
#   $env:ONEC_REMOTE_BRIDGE = "C:\1c-bridge\bridge\onec.ps1"   # путь к мосту НА РАБОЧЕЙ
#   $env:ONEC_CONNECTION_STRING = 'File="C:\Bases\МояБаза";Usr="Имя";Pwd=""'
#
#   powershell -NoProfile -File remote.ps1 check
#   powershell -NoProfile -File remote.ps1 info
#   powershell -NoProfile -File remote.ps1 exec 'Результат = 40 + 2;'
#   powershell -NoProfile -File remote.ps1 query "ВЫБРАТЬ 1 КАК А"
#   powershell -NoProfile -File remote.ps1 meta catalogs
#
# Кириллица передаётся через -EncodedCommand (base64 UTF-16) — иначе SSH-оболочка
# Windows ломает кодировку аргументов.

[CmdletBinding()]
param(
    [string]$SshTarget = $env:ONEC_SSH,
    [string]$RemoteBridge = $env:ONEC_REMOTE_BRIDGE,
    [string]$ConnectionString = $env:ONEC_CONNECTION_STRING,
    [Parameter(Position = 0)][string]$Command = "check",
    [Parameter(Position = 1)][string]$Arg1 = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $SshTarget) { Write-Error "Нет ssh-таргета: -SshTarget или env ONEC_SSH (напр. user@host)"; exit 1 }
if (-not $RemoteBridge) { Write-Error "Нет пути к мосту на удалённой: -RemoteBridge или env ONEC_REMOTE_BRIDGE"; exit 1 }
if (-not $ConnectionString) { Write-Error "Нет строки соединения: -ConnectionString или env ONEC_CONNECTION_STRING"; exit 1 }

# Собираем PowerShell-команду для удалённой машины (одинарные кавычки экранируем удвоением)
$esc = { param($s) if ($null -eq $s) { return "''" }; return "'" + ($s.ToString().Replace("'", "''")) + "'" }
$inner = "& $(& $esc $RemoteBridge) -ConnectionString $(& $esc $ConnectionString) $(& $esc $Command) $(& $esc $Arg1)"
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($inner))

Write-Host "[ssh] $SshTarget :: $Command" -ForegroundColor DarkGray
& ssh -o BatchMode=yes $SshTarget "powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand $b64"
exit $LASTEXITCODE
