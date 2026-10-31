param (
    [switch]$Docker,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "          AI OFFICE - STARTUP ORCHESTRATOR             " -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

# 1. Comprobar existencia de .env
if (-not (Test-Path ".env")) {
    Write-Host "[!] Archivo .env no detectado." -ForegroundColor Yellow
    $key = Read-Host "Ingresa tu GEMINI_API_KEY"
    if (-not $key) {
        Write-Host "[ERROR] La clave de API es obligatoria." -ForegroundColor Red
        exit 1
    }
    Set-Content -Path ".env" -Value "GEMINI_API_KEY=`"$key`"" -Encoding utf8
    Write-Host "[+] Archivo .env generado exitosamente.`n" -ForegroundColor Green
}

# 2. Modo Docker
if ($Docker) {
    Write-Host "[*] Iniciando AI Office en modo Docker Container..." -ForegroundColor Yellow
    docker compose up -d --build
    Write-Host "`n[+] Contenedor activo y en ejecucion." -ForegroundColor Green
    Write-Host "[*] Acceso web: http://localhost:8080" -ForegroundColor Cyan
    Write-Host "[*] Para ver logs en tiempo real: docker compose logs -f" -ForegroundColor Gray
    exit 0
}

# 3. Modo Local
Write-Host "[*] Verificando dependencias en Python local..." -ForegroundColor Yellow
python -m pip install -q -r requirements.txt

Write-Host "[*] Levantando servidor local en http://127.0.0.1:$Port..." -ForegroundColor Green
python office.py --port $Port
