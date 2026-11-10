# Arranca LicitApp.exe sin ventana en un puerto de prueba y comprueba que Streamlit responde 200.
# Usa una carpeta de datos temporal para no iniciar la prueba de 7 dias del usuario.
param([Parameter(Mandatory = $true)][string]$Exe, [int]$Puerto = 8777, [int]$Segundos = 120)

$datos = Join-Path $env:TEMP "licitapp_verificacion"
New-Item -ItemType Directory -Force -Path $datos | Out-Null
$env:LICITAPP_DATA_DIR = $datos
$env:LICITAPP_PUERTO = "$Puerto"
$env:LICITAPP_EXPEDIENTES = Join-Path $datos "expedientes"

$p = Start-Process -FilePath $Exe -ArgumentList "--sin-ventana" -PassThru -WindowStyle Hidden
$ok = $false
for ($i = 0; $i -lt $Segundos; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Puerto/" -UseBasicParsing -TimeoutSec 3
        $h = Invoke-WebRequest -Uri "http://127.0.0.1:$Puerto/_stcore/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200 -and $h.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
    if ($p.HasExited) { break }
}
& taskkill.exe /PID $p.Id /T /F *> $null
Remove-Item -Recurse -Force $datos -ErrorAction SilentlyContinue
if ($ok) { Write-Output "VERIFICACION_OK: la app respondio HTTP 200 en el puerto $Puerto"; exit 0 }
Write-Output "VERIFICACION_FALLO: la app no respondio en $Segundos segundos"
exit 1
