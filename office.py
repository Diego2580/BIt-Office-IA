import os
import sys
import json
import time
import socket
import shutil
import argparse
import urllib.request
import urllib.error
from pathlib import Path

ENV_FILE = Path(".env")
DEFAULT_PROJECTS_DIR = Path.cwd() / "proyectos"

def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key

    print("\n[CONFIGURACION] No se encontro GEMINI_API_KEY.")
    key = input("Pega tu Gemini API Key aqui: ").strip().strip('"').strip("'")
    if not key:
        print("[ERROR] La clave de API es obligatoria.")
        sys.exit(1)
    
    ENV_FILE.write_text(f'GEMINI_API_KEY="{key}"\n', encoding="utf-8")
    print("[OK] Clave guardada en .env para futuras ejecuciones.\n")
    return key

def resolve_target_project() -> Path:
    print("\n--- GESTOR DE PROYECTOS ---")
    print("1. Trabajar en un proyecto existente")
    print("2. Crear un proyecto nuevo")
    opcion = input("Selecciona una opcion (1/2) [Default 1]: ").strip() or "1"

    if opcion == "2":
        nombre = input("Nombre del nuevo proyecto (ej: mi_api): ").strip()
        while not nombre:
            nombre = input("El nombre no puede estar vacio: ").strip()

        print(f"\nDonde deseas ubicar el proyecto?")
        print(f"  [Enter] Ubicacion predeterminada: {DEFAULT_PROJECTS_DIR / nombre}")
        print(f"  [O ingresa una ruta personalizada]")
        custom_path = input("Ruta de destino: ").strip()

        if custom_path:
            if not (len(custom_path) >= 2 and custom_path[1] == ":"):
                custom_path = custom_path.lstrip("/\\")
                target = (Path.cwd() / custom_path).resolve()
            else:
                target = Path(custom_path).resolve()
        else:
            target = DEFAULT_PROJECTS_DIR / nombre

        target.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Proyecto inicializado en: {target}")
        return target

    else:
        ruta_raw = input("Ruta del proyecto (ej: ./proyectos/mi_api o nombre): ").strip()
        while not ruta_raw:
            ruta_raw = input("Ingresa una ruta valida: ").strip()

        if not (len(ruta_raw) >= 2 and ruta_raw[1] == ":"):
            ruta_limpia = ruta_raw.lstrip("/\\")
            posible_path = (Path.cwd() / ruta_limpia).resolve()
            if not posible_path.exists() and (DEFAULT_PROJECTS_DIR / ruta_limpia).exists():
                posible_path = (DEFAULT_PROJECTS_DIR / ruta_limpia).resolve()
            target = posible_path
        else:
            target = Path(ruta_raw).resolve()

        if not target.exists():
            print(f"[AVISO] Carpeta no encontrada. Se creara en: {target}")
            target.mkdir(parents=True, exist_ok=True)

        return target

def validate_python_syntax(files: list) -> tuple[bool, list]:
    errors = []
    for item in files:
        rel_path = item.get("relative_path", "")
        content = item.get("content", "")
        if rel_path.endswith(".py"):
            try:
                compile(content, rel_path, "exec")
            except SyntaxError as e:
                errors.append(f"'{rel_path}' linea {e.lineno}: {e.msg}")
            except Exception as e:
                errors.append(f"'{rel_path}': error ({str(e)})")
    return len(errors) == 0, errors

def call_gemini_api(api_key: str, system_prompt: str, user_prompt: str, max_retries: int = 4) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [{
            "parts": [{
                "text": f"SYSTEM_INSTRUCTION:\n{system_prompt}\n\nUSER_DATA:\n{user_prompt}"
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    data_bytes = json.dumps(payload).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)

                # 1. Manejo seguro de filtros de seguridad de Google
                if "candidates" not in res_json or not res_json["candidates"]:
                    feedback = res_json.get("promptFeedback", {})
                    block_reason = feedback.get("blockReason", "DESCONOCIDO")
                    raise RuntimeError(f"Google bloqueo la peticion por politicas de seguridad (Motivo: {block_reason}). Evita solicitar explicitamente crear vulnerabilidades.")

                candidate = res_json["candidates"][0]
                finish_reason = candidate.get("finishReason", "")
                if finish_reason == "SAFETY":
                    raise RuntimeError("La generacion fue interrumpida por los filtros de seguridad de Google (FinishReason: SAFETY).")

                parts = candidate.get("content", {}).get("parts", [])
                if not parts:
                    raise RuntimeError("La API respondio sin contenido utilizable.")

                raw_text = parts[0].get("text", "")
                return json.loads(raw_text)

        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8")
            if e.code in (503, 429) and attempt < max_retries:
                wait_time = attempt * 4
                print(f"[AVISO] Servidor ocupado ({e.code}). Reintentando en {wait_time}s... (Intento {attempt}/{max_retries})")
                time.sleep(wait_time)
                continue
            raise RuntimeError(f"HTTP Error {e.code}: {error_msg}")

        except (socket.timeout, TimeoutError):
            if attempt < max_retries:
                wait_time = attempt * 3
                print(f"[AVISO] Timeout de socket. Reintentando en {wait_time}s...")
                time.sleep(wait_time)
                continue
            raise TimeoutError("Gemini excedio el tiempo de espera.")

        except Exception as e:
            if attempt < max_retries and "Google bloqueo" not in str(e):
                time.sleep(2)
                continue
            raise RuntimeError(str(e))

    raise RuntimeError("No se obtuvo respuesta del modelo tras agotar reintentos.")

def execute_qa_audit(api_key: str, user_requirement: str, plan_executed: str, files: list) -> dict:
    system_prompt = (
        "ACTUA COMO: Principal Security Architect & Lead DevSecOps Auditor.\n"
        "POSTURA: Extremadamente critico, pesimista, sin cortesias ni elogios. Tu mision es vetar codigo deficiente.\n\n"
        "MATRIZ DE EVALUACION OBLIGATORIA:\n"
        "1. SEGURIDAD OWASP:\n"
        "   - Path Traversal (LFI/RFI): Uso de open() o Path() con inputs de usuario sin sanitizar.\n"
        "   - Inyecciones (SQL/Comandos): Concatenacion de cadenas en queries o llamadas a shell.\n"
        "   - Secretos hardcodeados: Claves, tokens o contraseñas en texto plano.\n"
        "   - Criptografia: Uso de algoritmos obsoletos (MD5, SHA1) o fallos en bcrypt/hashing.\n"
        "2. CUMPLIMIENTO FUNCIONAL:\n"
        "   - ¿Se omitio algun requisito pedido explicitamente por el usuario?\n"
        "   - ¿Hay mocks vacios o sentencias pass que rompen la logica esperada?\n"
        "3. TIPADO Y RESILIENCIA:\n"
        "   - Manejo de excepciones nulas o try/except genericos que silencian errores reales.\n\n"
        "REGLA DE VETO: Si existe un fallo critico de seguridad o no cumple el requerimiento, approved DEBE ser false.\n"
        "FORMATO DE SALIDA (JSON ESTRICTO):\n"
        "{\n"
        '  "approved": true,\n'
        '  "security_score": 9,\n'
        '  "verdict_summary": "Evaluacion ejecutiva en 1 frase",\n'
        '  "findings": [\n'
        '    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "ruta/archivo.py", "issue": "Descripcion del problema"}\n'
        "  ]\n"
        "}"
    )

    code_dump = "\n\n".join([f"=== ARCHIVO: {f['relative_path']} ===\n{f['content']}" for f in files])
    user_data = (
        f"REQUERIMIENTO ORIGINAL:\n{user_requirement}\n\n"
        f"PLAN DECLARADO:\n{plan_executed}\n\n"
        f"CODIGO COMPLETO PROPUESTO:\n{code_dump}"
    )

    return call_gemini_api(api_key, system_prompt, user_data)

def run_pipeline(project_path: str = None, user_prompt: str = None):
    api_key = get_api_key()

    if project_path:
        raw = project_path.strip()
        if not (len(raw) >= 2 and raw[1] == ":"):
            target_dir = (Path.cwd() / raw.lstrip("/\\")).resolve()
        else:
            target_dir = Path(raw).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = resolve_target_project()

    task = user_prompt or input("\nInstruccion para la oficina: ").strip()

    existing_files = [str(p.relative_to(target_dir)) for p in target_dir.rglob("*") if p.is_file() and not p.name.endswith(".bak")]
    existing_files_summary = "\n".join(existing_files) if existing_files else "Directorio vacio."

    memory_file = target_dir / "PROJECT_MEMORY.md"
    memory_content = memory_file.read_text(encoding="utf-8") if memory_file.exists() else "Sin historial previo."

    print(f"\n========================================================")
    print(f"[CENTRO DE MANDO] Proyecto activo: {target_dir}")
    print(f"[CENTRO DE MANDO] Requerimiento: {task}")
    print(f"========================================================\n")

    # 1. Líder
    print("[LIDER - GEMINI] Disenando arquitectura y generando codigo...")
    leader_system = (
        "Eres el Tech Lead de una software factory. Genera codigo de produccion funcional y completo. "
        "Responde UNICAMENTE en JSON con este esquema exacto:\n"
        "{\n"
        '  "plan": "Plan conciso",\n'
        '  "files_to_modify": [{"relative_path": "ruta/archivo.ext", "content": "codigo completo"}],\n'
        '  "memory_update": "Resumen para el log"\n'
        "}"
    )
    leader_input = f"MEMORIA:\n{memory_content}\n\nARCHIVOS EXISTENTES:\n{existing_files_summary}\n\nREQUERIMIENTO:\n{task}"

    try:
        plan_data = call_gemini_api(api_key, leader_system, leader_input)
    except Exception as e:
        print(f"[LIDER - ERROR] {e}")
        return

    print(f"[LIDER] Plan: {plan_data.get('plan')}\n")
    files = plan_data.get("files_to_modify", [])

    # 2. QA Filtro Local
    print(f"[QA - LOCAL] Validando sintaxis preliminar...")
    is_valid, syntax_errors = validate_python_syntax(files)
    if not is_valid:
        print("[QA - ERROR SINTACTICO] No compila en memoria:")
        for err in syntax_errors:
            print(f"  [X] {err}")
        print("[QA] Pipeline detenido. No se altero el disco.")
        return
    print("[QA - LOCAL] Sintaxis aprobada (0 errores).\n")

    # 3. QA Auditoría Profunda
    print(f"[QA - DEVSECOPS] Ejecutando auditoria profunda de seguridad y logica...")
    try:
        audit = execute_qa_audit(api_key, task, plan_data.get("plan", ""), files)
        score = audit.get("security_score", 10)
        approved = audit.get("approved", True)
        findings = audit.get("findings", [])

        print(f"[QA - AUDITORIA] Score: {score}/10 | Veredicto: {audit.get('verdict_summary')}")

        if findings:
            for item in findings:
                sev = item.get("severity", "INFO")
                print(f"  [{sev}] {item.get('file')}: {item.get('issue')}")

        if not approved:
            print("\n[QA - VETO CRITICO] Codigo rechazado por el auditor de seguridad.")
            print("[QA] La operacion se cancelo. Ningun archivo fue escrito en disco.")
            return

        print("[QA] Auditoria aprobada sin objeciones criticas.\n")

    except Exception as e:
        print(f"[QA - ADVERTENCIA] No se pudo completar la auditoria profunda ({e}). Procediendo con precaucion.")

    # 4. Coder
    print(f"[CODER] Aplicando cambios en {len(files)} archivo(s)...")
    for item in files:
        rel_path = item["relative_path"]
        file_path = target_dir / rel_path

        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copyfile(file_path, backup_path)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(item["content"], encoding="utf-8")
        print(f"  -> Archivo generado/actualizado: {rel_path}")

    # 5. DevOps / Persistencia
    print("\n[DEV-OPS] Actualizando memoria persistente...")
    memory_entry = (
        f"\n\n## Tarea Completada\n"
        f"- **Requerimiento:** {task}\n"
        f"- **Plan:** {plan_data.get('plan')}\n"
        f"- **Score QA:** {score}/10\n"
        f"- **Detalles:** {plan_data.get('memory_update')}\n"
    )
    with open(memory_file, "a", encoding="utf-8") as f:
        f.write(memory_entry)

    print(f"[DEV-OPS] Historial registrado en: {memory_file.name}")
    print("\n[OK] Ciclo de ejecucion completado satisfactoriamente.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Office Core - Single Script")
    parser.add_argument("--path", type=str, help="Ruta de la carpeta del proyecto")
    parser.add_argument("--prompt", type=str, help="Instruccion o tarea a desarrollar")
    args = parser.parse_args()

    run_pipeline(args.path, args.prompt)
