import json


def test_list_projects_empty(client, isolated_projects_dir):
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == {"projects": []}


def test_create_project_success(client, isolated_projects_dir):
    response = client.post("/api/projects", json={"name": "auth_service"})
    assert response.status_code == 200
    assert response.json()["name"] == "auth_service"
    assert (isolated_projects_dir / "auth_service").is_dir()


def test_create_project_invalid_name(client, isolated_projects_dir):
    response = client.post("/api/projects", json={"name": "   "})
    assert response.status_code == 400


def test_project_memory_retrieval(client, isolated_projects_dir):
    proj_dir = isolated_projects_dir / "core_api"
    proj_dir.mkdir()
    memory_file = proj_dir / "PROJECT_MEMORY.md"
    memory_file.write_text("# Memoria de prueba", encoding="utf-8")

    response = client.get("/api/projects/core_api/memory")
    assert response.status_code == 200
    assert "# Memoria de prueba" in response.json()["memory"]


def test_project_security_audit_retrieval(client, isolated_projects_dir):
    proj_dir = isolated_projects_dir / "core_api"
    proj_dir.mkdir()
    sec_file = proj_dir / "SECURITY_AUDIT.json"
    audit_data = {"security_score": 9, "approved": True, "verdict_summary": "Excelente"}
    sec_file.write_text(json.dumps(audit_data), encoding="utf-8")

    response = client.get("/api/projects/core_api/security")
    assert response.status_code == 200
    data = response.json()
    assert data["has_audit"] is True
    assert data["audit"]["security_score"] == 9


def test_path_traversal_protection(client, isolated_projects_dir):
    proj_dir = isolated_projects_dir / "core_api"
    proj_dir.mkdir()

    malicious_paths = [
        "../../.env",
        "../sandbox_proyectos/../../windows/win.ini",
        "/etc/passwd",
    ]
    for p in malicious_paths:
        response = client.get(f"/api/projects/core_api/file?path={p}")
        assert response.status_code in (403, 404)


def test_read_single_valid_file(client, isolated_projects_dir):
    proj_dir = isolated_projects_dir / "core_api"
    proj_dir.mkdir()
    target_file = proj_dir / "main.py"
    target_file.write_text("print('test_ok')", encoding="utf-8")

    response = client.get("/api/projects/core_api/file?path=main.py")
    assert response.status_code == 200
    assert response.json()["content"] == "print('test_ok')"
