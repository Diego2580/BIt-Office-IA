#!/usr/bin/env bash
set -e

PORT=8000
USE_DOCKER=false

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --docker) USE_DOCKER=true ;;
        --port) PORT="$2"; shift ;;
        *) echo "Parametro desconocido: $1"; exit 1 ;;
    esac
    shift
done

echo -e "\n\033[1;36m========================================================\033[0m"
echo -e "\033[1;36m          AI OFFICE - STARTUP ORCHESTRATOR             \033[0m"
echo -e "\033[1;36m========================================================\n\033[0m"

if [ ! -f ".env" ]; then
    echo -e "\033[1;33m[!] Archivo .env no detectado.\033[0m"
    read -p "Ingresa tu GEMINI_API_KEY: " KEY
    if [ -z "$KEY" ]; then
        echo -e "\033[1;31m[ERROR] La clave de API es obligatoria.\033[0m"
        exit 1
    fi
    echo "GEMINI_API_KEY=\"$KEY\"" > .env
    echo -e "\033[1;32m[+] Archivo .env generado exitosamente.\n\033[0m"
fi

if [ "$USE_DOCKER" = true ]; then
    echo -e "\033[1;33m[*] Levantando contenedor con Docker Compose...\033[0m"
    docker compose up -d --build
    echo -e "\033[1;32m[+] Servicio Docker levantado en http://localhost:8080\033[0m"
    exit 0
fi

echo -e "\033[1;33m[*] Verificando dependencias locales...\033[0m"
pip install -q -r requirements.txt

echo -e "\033[1;32m[*] Levantando servidor local en http://127.0.0.1:$PORT...\033[0m"
python office.py --port "$PORT"
