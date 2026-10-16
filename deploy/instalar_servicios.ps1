# Registra la API y Caddy como tareas de inicio de Windows (SYSTEM, reinicio automático cada minuto si caen).
# Ejecutar como Administrador en el servidor EC2 (Windows Server). Requiere: C:\iot\vehiculo-iot-api con .venv y .env,
# y C:\caddy\caddy.exe con su Caddyfile (ver deploy\Caddyfile.example).
$ErrorActionPreference = 'Stop'
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
$trg = New-ScheduledTaskTrigger -AtStartup
$usr = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$api = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c cd /d C:\iot\vehiculo-iot-api && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 >> C:\iot\api.log 2>&1'
$cad = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c C:\caddy\caddy.exe run --config C:\caddy\Caddyfile --adapter caddyfile >> C:\caddy\caddy.log 2>&1'
Register-ScheduledTask -TaskName 'IoT-API'   -Action $api -Trigger $trg -Settings $cfg -Principal $usr -Force | Out-Null
Register-ScheduledTask -TaskName 'IoT-Caddy' -Action $cad -Trigger $trg -Settings $cfg -Principal $usr -Force | Out-Null
foreach ($p in 80, 443) {
    New-NetFirewallRule -DisplayName "IoT-TCP-$p" -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow -ErrorAction SilentlyContinue | Out-Null
}
Start-ScheduledTask -TaskName 'IoT-API'; Start-Sleep 8; Start-ScheduledTask -TaskName 'IoT-Caddy'
Get-ScheduledTask -TaskName 'IoT-*' | Select-Object TaskName, State
