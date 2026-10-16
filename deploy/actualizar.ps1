# Actualiza el servidor desde GitHub y reinicia la API (ejecutar en el EC2).
$ErrorActionPreference = 'Stop'
Set-Location C:\iot\vehiculo-iot-api
git pull
.\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
Stop-ScheduledTask -TaskName 'IoT-API' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'uvicorn app.main' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
Start-ScheduledTask -TaskName 'IoT-API'
