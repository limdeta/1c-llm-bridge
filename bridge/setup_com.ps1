# Регистрация COM-коннектора 1С (V83.COMConnector) без прав администратора.
# Регистрирует класс comcntr.dll и библиотеку типов в HKCU (реестр текущего пользователя).
# Для системной регистрации (все пользователи) запустите от администратора:
#   regsvr32 "C:\Program Files\1cv8\<версия>\bin\comcntr.dll"
#
# Использование:
#   powershell -NoProfile -File setup_com.ps1 [-V8Bin <путь к bin>]

param(
    [string]$V8Bin = ""
)

if (-not $V8Bin) {
    $found = Get-ChildItem "C:\Program Files\1cv8\*\bin\comcntr.dll" -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]"0.0" } } -Descending |
        Select-Object -First 1
    if (-not $found) {
        Write-Host "comcntr.dll не найдена. Укажите -V8Bin." -ForegroundColor Red
        exit 1
    }
    $V8Bin = $found.DirectoryName
}

$dll = Join-Path $V8Bin "comcntr.dll"
if (-not (Test-Path $dll)) {
    Write-Host "Нет файла: $dll" -ForegroundColor Red
    exit 1
}

# --- CLSID и typelib для 8.3.x (стабильны внутри платформы) ---
$clsid = "{181e893d-73a4-4722-b61d-d604b3d67d47}"   # COMConnector
$tlbGuid = "{98ac3b5b-5323-418f-8f07-e32f231d2393}" # typelib comcntr.dll
$base = "HKCU:\Software\Classes"

# Класс
New-Item -Path "$base\V83.COMConnector" -Force | Out-Null
Set-ItemProperty -Path "$base\V83.COMConnector" -Name "(default)" -Value "1C:Enterprise 8.3 COMConnector"
New-Item -Path "$base\V83.COMConnector\CLSID" -Force | Out-Null
Set-ItemProperty -Path "$base\V83.COMConnector\CLSID" -Name "(default)" -Value $clsid
New-Item -Path "$base\CLSID\$clsid\InprocServer32" -Force | Out-Null
Set-ItemProperty -Path "$base\CLSID\$clsid\InprocServer32" -Name "(default)" -Value $dll
Set-ItemProperty -Path "$base\CLSID\$clsid\InprocServer32" -Name "ThreadingModel" -Value "Both"
New-Item -Path "$base\CLSID\$clsid\ProgID" -Force | Out-Null
Set-ItemProperty -Path "$base\CLSID\$clsid\ProgID" -Name "(default)" -Value "V83.COMConnector"

# Библиотека типов (без неё Connect() не резолвится: TYPE_E_LIBNOTREGISTERED)
New-Item -Path "$base\TypeLib\$tlbGuid\1.0\0\win64" -Force | Out-Null
Set-ItemProperty -Path "$base\TypeLib\$tlbGuid\1.0\0\win64" -Name "(default)" -Value $dll
New-Item -Path "$base\TypeLib\$tlbGuid\1.0\FLAGS" -Force | Out-Null
Set-ItemProperty -Path "$base\TypeLib\$tlbGuid\1.0\FLAGS" -Name "(default)" -Value 0 -Type DWord
New-Item -Path "$base\TypeLib\$tlbGuid\1.0\HELPDIR" -Force | Out-Null
Set-ItemProperty -Path "$base\TypeLib\$tlbGuid\1.0\HELPDIR" -Name "(default)" -Value $V8Bin

# Проверка
try {
    $c = New-Object -ComObject V83.COMConnector
    Write-Host "[OK] V83.COMConnector создан ($dll)" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] V83.COMConnector: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
