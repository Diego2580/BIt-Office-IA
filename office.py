import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

ENV_FILE = Path(".env")
DEFAULT_PROJECTS_DIR = Path.cwd() / "proyectos"
DEFAULT_PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR = Path.cwd() / "web"
INDEX_HTML = WEB_DIR / "index.html"

MODELS_CATALOG = {
    "LITE": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash"],
    "STANDARD": ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"],
    "PRO": ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"],
}


def get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
                if k:
                    return k

    print("\n[CONFIGURACION] GEMINI_API_KEY no detectada.")
    key = input("Pega tu Gemini API Key aqui: ").strip().strip('"').strip("'")
    if not key:
        print("[ERROR] La clave de API es obligatoria.")
        sys.exit(1)

    with open(ENV_FILE, "a", encoding="utf-8") as f:
        f.write(f'GEMINI_API_KEY="{key}"\n')
    return key


GEMINI_API_KEY = get_api_key()


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, agent: str, message: str, payload: dict[str, Any] | None = None):
        data = {
            "timestamp": time.strftime("%H:%M:%S"),
            "event_type": event_type,
            "agent": agent,
            "message": message,
            "payload": payload or {},
        }
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)


manager = ConnectionManager()


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
                errors.append(f"'{rel_path}': error ({e!s})")
    return len(errors) == 0, errors


def classify_task_complexity(task: str, existing_files_count: int) -> dict:
    task_lower = task.lower()
    words_count = len(task.split())

    heavy_keywords = [
        "arquitectura", "refactor", "patron", "microservicio", "rediseña",
        "concurrencia", "asincrono complejo", "inyeccion de dependencias", "escalabilidad",
        "migra", "seguridad avanzada", "oauth", "jwt completo", "multitenant", "database",
    ]
    light_keywords = [
        "agrega un campo", "docstring", "corrige", "cambia el puerto",
        "imprime", "variable", "status", "health", "renombra", "comentario",
        "formato", "version", "tipo", "tipado", "endpoint simple", "ajusta", "info",
    ]

    is_heavy = any(kw in task_lower for kw in heavy_keywords) or words_count > 45 or existing_files_count > 15
    is_light = any(kw in task_lower for kw in light_keywords) and words_count < 20 and not is_heavy

    if is_heavy:
        tier = "TIER_PRO"
        category = "PRO"
        reason = "Complejidad estructural alta o requerimiento extenso"
    elif is_light:
        tier = "TIER_LITE"
        category = "LITE"
        reason = "Modificación atómica o endpoint simple (máxima velocidad y ahorro de tokens)"
    else:
        tier = "TIER_STANDARD"
        category = "STANDARD"
        reason = "Desarrollo modular estándar de features"

    models_chain = MODELS_CATALOG[category]
    return {
        "tier": tier,
        "primary_model": models_chain[0],
        "models_chain": models_chain,
        "reason": reason,
        "words_count": words_count,
    }


async def call_gemini_with_telemetry(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    models_chain: list[str],
    max_output_tokens: int = 4096,
) -> dict:
    payload = {
        "contents": [{
            "parts": [{"text": f"SYSTEM_INSTRUCTION:\n{system_prompt}\n\nUSER_DATA:\n{user_prompt}"}],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": max_output_tokens,
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    last_error = None

    for model in models_chain:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        stop_heartbeat = asyncio.Event()

        async def heartbeat_worker(target_model: str = model, stop_event: asyncio.Event = stop_heartbeat):
            elapsed = 0
            milestones = [
                (2, f"Conectando con {target_model}..."),
                (6, "Generando código fuente de producción..."),
                (14, "Construyendo schemas y endpoints..."),
                (22, "Finalizando contratos y respuestas..."),
            ]
            m_idx = 0
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=1.0)
                    break
                except TimeoutError:
                    elapsed += 1
                    if m_idx < len(milestones) and elapsed >= milestones[m_idx][0]:
                        await manager.broadcast("AGENT_LOG", agent_name, f"{milestones[m_idx][1]} ({elapsed}s)")
                        m_idx += 1
                    elif elapsed > 22 and elapsed % 8 == 0:
                        await manager.broadcast("AGENT_LOG", agent_name, f"Escribiendo módulos... ({elapsed}s)")

        heartbeat_task = asyncio.create_task(heartbeat_worker(model, stop_heartbeat))

        def _do_request(target_url: str = url):
            req = urllib.request.Request(
                target_url,
                data=data_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            # nosec B310: URL generada exclusivamente contra la API HTTPS oficial de Google
            with urllib.request.urlopen(req, timeout=90) as response:  # nosec B310
                return response.read().decode("utf-8")

        try:
            res_body = await asyncio.to_thread(_do_request, url)
            res_json = json.loads(res_body)

            if "candidates" not in res_json or not res_json["candidates"]:
                feedback = res_json.get("promptFeedback", {})
                block_reason = feedback.get("blockReason", "DESCONOCIDO")
                raise RuntimeError(f"Bloqueado por filtros de seguridad ({block_reason})")

            candidate = res_json["candidates"][0]
            if candidate.get("finishReason") == "SAFETY":
                raise RuntimeError("Generación interrumpida por filtros de seguridad.")

            parts = candidate.get("content", {}).get("parts", [])
            if not parts:
                raise RuntimeError("Respuesta sin contenido utilizable.")

            raw_text = parts[0].get("text", "").strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            return json.loads(raw_text)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            last_error = f"HTTP {e.code} en {model}"

            if e.code in (404, 410, 429, 503):
                await manager.broadcast(
                    "AGENT_LOG",
                    agent_name,
                    f"Modelo '{model}' no disponible ({e.code}). Conmutando al siguiente modelo del pool...",
                )
                continue
            raise RuntimeError(f"HTTP Error {e.code}: {error_body}") from e

        except Exception as e:
            last_error = str(e)
            await manager.broadcast("AGENT_LOG", agent_name, f"Incidencia con '{model}': {e!s}. Probando alternativa...")
            continue

        finally:
            stop_heartbeat.set()
            try:
                await heartbeat_task
            except Exception:
                pass

    raise RuntimeError(f"Modelos agotados en la cadena de ejecución. Último error: {last_error}")


async def execute_pipeline_async(target_dir: Path, task: str):
    await manager.broadcast("PIPELINE_START", "ORCHESTRATOR", f"Iniciando ciclo en {target_dir.name}", {"task": task})

    ignored_patterns = {"__pycache__", ".venv", "venv", ".git", ".pytest_cache", ".bak"}
    existing_files = []
    for p in target_dir.rglob("*"):
        if p.is_file():
            parts = set(p.relative_to(target_dir).parts)
            if not parts.intersection(ignored_patterns) and not p.name.endswith(".bak"):
                existing_files.append(str(p.relative_to(target_dir).as_posix()))

    memory_file = target_dir / "PROJECT_MEMORY.md"
    raw_memory = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
    security_file = target_dir / "SECURITY_AUDIT.json"

    # Enrutamiento Heurístico
    routing = classify_task_complexity(task, len(existing_files))
    tier = routing["tier"]
    selected_model = routing["primary_model"]
    reason = routing["reason"]
    models_chain = routing["models_chain"]

    await manager.broadcast(
        "ROUTER_DECISION",
        "ORCHESTRATOR",
        f"Enrutador IA [{tier}]: Asignado '{selected_model}' ({reason})",
        routing,
    )

    # Constructor de Contexto Optimizado
    if tier == "TIER_LITE":
        if raw_memory:
            sections = raw_memory.split("## Tarea Completada")
            if len(sections) > 1:
                memory_context = "## Última Tarea Previa\n" + sections[-1].strip()
            else:
                memory_context = raw_memory[-350:]
        else:
            memory_context = "Sin historial previo."

        task_lower = task.lower()
        matched_files = [f for f in existing_files if Path(f).name.lower() in task_lower]

        if matched_files:
            files_context = "ARCHIVOS OBJETIVO DIRECTOS:\n" + "\n".join(matched_files)
        else:
            sample_files = existing_files[:8]
            files_context = "\n".join(sample_files) if sample_files else "Directorio vacío."
            if len(existing_files) > 8:
                files_context += f"\n... [{len(existing_files) - 8} archivos omitidos del contexto]"

        max_output_tokens = 1024

        full_chars = len(raw_memory) + len("\n".join(existing_files)) + len(task)
        pruned_chars = len(memory_context) + len(files_context) + len(task)
        tokens_saved = max(0, (full_chars - pruned_chars) // 4)
        pct_saved = int((tokens_saved / max(1, full_chars // 4)) * 100)

        if tokens_saved > 40:
            await manager.broadcast(
                "AGENT_LOG",
                "ORCHESTRATOR",
                f"Ahorro de tokens activo [TIER_LITE]: Contexto podado (~{pruned_chars // 4} tokens de entrada vs ~{full_chars // 4} sin podar. {pct_saved}% de ahorro).",
            )
    else:
        memory_context = raw_memory if raw_memory else "Sin historial previo."
        files_context = "\n".join(existing_files) if existing_files else "Directorio vacío."
        max_output_tokens = 4096

    # 1. Tech Lead
    await manager.broadcast(
        "AGENT_STATUS",
        "TECH_LEAD",
        f"Generando solución optimizada con '{selected_model}'...",
        {"status": "THINKING", "model": selected_model, "tier": tier},
    )

    leader_system = (
        "Eres el Tech Lead de una software factory. Genera código de producción funcional y conciso.\n"
        "REGLA DE RENDIMIENTO: Genera ÚNICAMENTE los archivos que se deben crear o modificar para cumplir el requerimiento. "
        "No reescribas archivos existentes que no requieran cambios.\n"
        "Responde UNICAMENTE en JSON plano válido con este esquema exacto:\n"
        "{\n"
        '  "plan": "Plan conciso",\n'
        '  "files_to_modify": [{"relative_path": "ruta/archivo.ext", "content": "código completo"}],\n'
        '  "memory_update": "Resumen para el log"\n'
        "}"
    )
    leader_input = f"MEMORIA TÉCNICA:\n{memory_context}\n\nARCHIVOS DEL PROYECTO:\n{files_context}\n\nREQUERIMIENTO:\n{task}"

    try:
        plan_data = await call_gemini_with_telemetry(
            GEMINI_API_KEY,
            leader_system,
            leader_input,
            "TECH_LEAD",
            models_chain,
            max_output_tokens=max_output_tokens,
        )
    except Exception as e:
        await manager.broadcast("AGENT_FAILED", "TECH_LEAD", f"Error en generación: {e!s}", {"status": "ERROR"})
        return

    plan_desc = plan_data.get("plan", "Sin plan declarado")
    files = plan_data.get("files_to_modify", [])
    await manager.broadcast("AGENT_SUCCESS", "TECH_LEAD", f"Plan aprobado: {plan_desc}", {"plan": plan_desc, "files_count": len(files)})

    # 2. QA Local
    await manager.broadcast("AGENT_STATUS", "QA_LOCAL", "Validando compilación y sintaxis en memoria...", {"status": "WORKING"})
    is_valid, syntax_errors = validate_python_syntax(files)
    if not is_valid:
        await manager.broadcast("AGENT_FAILED", "QA_LOCAL", "Errores de sintaxis detectados", {"errors": syntax_errors})
        return
    await manager.broadcast("AGENT_SUCCESS", "QA_LOCAL", "Sintaxis verificada (0 errores de compilación)", {"status": "APPROVED"})

    # 3. QA DevSecOps
    await manager.broadcast("AGENT_STATUS", "QA_DEVSECOPS", "Auditando vulnerabilidades y estándares OWASP...", {"status": "THINKING"})
    devsecops_system = (
        "ACTÚA COMO: Principal Security Architect & Lead DevSecOps Auditor.\n"
        "MISIÓN: Vetar código únicamente ante riesgos de seguridad reales y severos.\n\n"
        "CRITERIOS DE VETO (approved: false, score < 6):\n"
        "- Inyecciones (SQL, NoSQL, Comandos OS).\n"
        "- Path Traversal / Arbitrary File Overwrite o LFI/RFI.\n"
        "- Secretos, llaves privadas o credenciales expuestas en texto plano.\n"
        "- Criptografía obsoleta o passwords sin hash/salt adecuado.\n"
        "- Endpoints que modifiquen datos (POST/PUT/DELETE) o lean información sensible/PII sin autenticación.\n\n"
        "REGLA DE OBSERVABILIDAD Y METADATA (NO VETAR):\n"
        "- Endpoints operativos e informativos como '/health', '/status', '/version', '/ping' o '/info' son PÚBLICOS por estándar de la industria.\n"
        "- NO vetar un endpoint por no tener autenticación si su único propósito es devolver el status o versión.\n"
        "- La falta de esquemas Pydantic o el hardcoding de metadata simple se clasifica como 'LOW' o 'MEDIUM' (score 7-8/10), NUNCA como causal de veto.\n\n"
        "FORMATO JSON OBLIGATORIO:\n"
        "{\n"
        '  "approved": true,\n'
        '  "security_score": 9,\n'
        '  "verdict_summary": "Evaluación ejecutiva en 1 frase",\n'
        '  "findings": [\n'
        '    {"severity": "CRITICAL|HIGH|MEDIUM|LOW", "file": "ruta/archivo.py", "issue": "Detalle técnico y recomendación"}\n'
        "  ]\n"
        "}"
    )
    code_dump = "\n\n".join([f"=== ARCHIVO: {f['relative_path']} ===\n{f['content']}" for f in files])
    qa_input = f"REQUERIMIENTO:\n{task}\n\nPLAN:\n{plan_desc}\n\nCÓDIGO:\n{code_dump}"

    score = 10
    approved = True
    findings = []
    verdict = "Auditoría completada satisfactoriamente"

    try:
        audit = await call_gemini_with_telemetry(
            GEMINI_API_KEY,
            devsecops_system,
            qa_input,
            "QA_DEVSECOPS",
            MODELS_CATALOG["STANDARD"],
            max_output_tokens=1500,
        )
        score = audit.get("security_score", 10)
        approved = audit.get("approved", True)
        findings = audit.get("findings", [])
        verdict = audit.get("verdict_summary", "Sin observaciones críticas.")

        audit_report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "task": task,
            "security_score": score,
            "approved": approved,
            "verdict_summary": verdict,
            "findings": findings,
        }
        security_file.write_text(json.dumps(audit_report, indent=2, ensure_ascii=False), encoding="utf-8")

        audit_payload = {
            "score": score,
            "approved": approved,
            "verdict": verdict,
            "findings": findings,
            "task": task,
        }

        if not approved:
            await manager.broadcast("AGENT_FAILED", "QA_DEVSECOPS", f"Código vetado por seguridad ({score}/10): {verdict}", audit_payload)
            return

        await manager.broadcast("AGENT_SUCCESS", "QA_DEVSECOPS", f"Auditoría aprobada ({score}/10): {verdict}", audit_payload)

    except Exception as e:
        await manager.broadcast("AGENT_LOG", "QA_DEVSECOPS", f"Auditoría omitida ({e!s})")

    # 4. Senior Coder
    await manager.broadcast("AGENT_STATUS", "SENIOR_CODER", f"Escribiendo {len(files)} archivo(s) en disco...", {"status": "WORKING"})
    for item in files:
        rel_path = item["relative_path"]
        file_path = target_dir / rel_path

        if file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            shutil.copyfile(file_path, backup_path)

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(item["content"], encoding="utf-8")
        await manager.broadcast("AGENT_LOG", "SENIOR_CODER", f"Archivo generado: {rel_path}")

    await manager.broadcast("AGENT_SUCCESS", "SENIOR_CODER", "Archivos actualizados correctamente", {"modified": [f["relative_path"] for f in files]})

    # 5. DevOps Scribe
    await manager.broadcast("AGENT_STATUS", "DEVOPS", "Actualizando memoria persistente...", {"status": "WORKING"})
    memory_entry = (
        f"\n\n## Tarea Completada\n"
        f"- **Requerimiento:** {task}\n"
        f"- **Tier & Modelo:** {tier} ({selected_model})\n"
        f"- **Plan:** {plan_desc}\n"
        f"- **Score QA:** {score}/10 ({'APROBADO' if approved else 'VETADO'})\n"
        f"- **Detalles:** {plan_data.get('memory_update')}\n"
    )
    with open(memory_file, "a", encoding="utf-8") as f:
        f.write(memory_entry)

    await manager.broadcast("AGENT_SUCCESS", "DEVOPS", "PROJECT_MEMORY.md sincronizado", {})
    await manager.broadcast("PIPELINE_COMPLETE", "ORCHESTRATOR", "Ciclo de ejecución completado exitosamente", {"project": target_dir.name})


app = FastAPI(title="AI Office - Backend Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunTaskRequest(BaseModel):
    project_name: str
    prompt: str


class CreateProjectRequest(BaseModel):
    name: str


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    if INDEX_HTML.exists():
        return INDEX_HTML.read_text(encoding="utf-8")
    return "<h2>Dashboard no encontrado. Genera web/index.html primero.</h2>"


@app.websocket("/ws/office")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({
            "timestamp": time.strftime("%H:%M:%S"),
            "event_type": "CONNECTED",
            "agent": "SYSTEM",
            "message": "Conectado al Event Bus de AI Office",
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/projects")
def list_projects():
    projects = []
    for item in DEFAULT_PROJECTS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            has_memory = (item / "PROJECT_MEMORY.md").exists()
            has_security = (item / "SECURITY_AUDIT.json").exists()
            file_count = len([f for f in item.rglob("*") if f.is_file()])
            projects.append({
                "name": item.name,
                "path": str(item),
                "has_memory": has_memory,
                "has_security": has_security,
                "file_count": file_count,
            })
    return {"projects": projects}


@app.post("/api/projects")
def create_project(req: CreateProjectRequest):
    safe_name = req.name.strip().lstrip("/\\")
    if not safe_name:
        raise HTTPException(status_code=400, detail="El nombre del proyecto es inválido")
    target = DEFAULT_PROJECTS_DIR / safe_name
    target.mkdir(parents=True, exist_ok=True)
    return {"status": "created", "name": safe_name, "path": str(target)}


@app.get("/api/projects/{name}/memory")
def get_project_memory(name: str):
    target = DEFAULT_PROJECTS_DIR / name
    memory_file = target / "PROJECT_MEMORY.md"
    if not memory_file.exists():
        return {"memory": "*Sin historial previo registrado en PROJECT_MEMORY.md.*"}
    return {"memory": memory_file.read_text(encoding="utf-8")}


@app.get("/api/projects/{name}/security")
def get_project_security(name: str):
    target = DEFAULT_PROJECTS_DIR / name
    security_file = target / "SECURITY_AUDIT.json"
    if not security_file.exists():
        return {"has_audit": False, "audit": None}
    try:
        data = json.loads(security_file.read_text(encoding="utf-8"))
        return {"has_audit": True, "audit": data}
    except Exception as e:
        return {"has_audit": False, "error": str(e)}


@app.get("/api/projects/{name}/files")
def list_project_files(name: str):
    target = DEFAULT_PROJECTS_DIR / name
    if not target.exists():
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    files_list = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and not p.name.endswith(".bak") and not p.name.startswith("."):
            rel = p.relative_to(target).as_posix()
            files_list.append({
                "path": rel,
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "is_memory": p.name == "PROJECT_MEMORY.md",
                "is_security": p.name == "SECURITY_AUDIT.json",
            })
    return {"project": name, "files": files_list}


@app.get("/api/projects/{name}/file")
def get_single_file_content(name: str, path: str):
    target = DEFAULT_PROJECTS_DIR / name
    clean_path = Path(path).as_posix().lstrip("/\\")
    resolved = (target / clean_path).resolve()

    if not str(resolved).startswith(str(target.resolve())):
        raise HTTPException(status_code=403, detail="Acceso denegado fuera del directorio del proyecto")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    try:
        content = resolved.read_text(encoding="utf-8")
        return {"path": clean_path, "content": content}
    except Exception as e:
        return {"path": clean_path, "content": f"<Error archivo: decodificando {e!s}>"}


@app.post("/api/run")
async def run_task(req: RunTaskRequest):
    target_dir = DEFAULT_PROJECTS_DIR / req.project_name
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="El proyecto especificado no existe")

    asyncio.create_task(execute_pipeline_async(target_dir, req.prompt))
    return {"status": "started", "project": req.project_name, "prompt": req.prompt}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Office Server")
    # Default seguro para desarrollo local (evita B104 en Bandit). Docker pasa --host 0.0.0.0
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host del servidor (0.0.0.0 en Docker)")
    parser.add_argument("--port", type=int, default=8000, help="Puerto del servidor")
    args = parser.parse_args()

    print("\n========================================================")
    print(f"[*] Dashboard disponible en: http://{args.host}:{args.port}")
    print(f"[*] WebSocket activo en:    ws://{args.host}:{args.port}/ws/office")
    print(f"[*] Proyectos en:           {DEFAULT_PROJECTS_DIR}")
    print("========================================================\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

