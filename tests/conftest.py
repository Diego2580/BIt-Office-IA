import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Asegurar path de raiz para imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Clave simulada para pruebas sin input interactivo
os.environ["GEMINI_API_KEY"] = "mock_test_key_ai_office_ci_cd_12345"

import office


@pytest.fixture
def client():
    return TestClient(office.app)


@pytest.fixture
def isolated_projects_dir(tmp_path, monkeypatch):
    test_dir = tmp_path / "sandbox_proyectos"
    test_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(office, "DEFAULT_PROJECTS_DIR", test_dir)
    return test_dir
