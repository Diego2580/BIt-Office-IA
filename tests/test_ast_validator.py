from office import validate_python_syntax


def test_ast_valid_python_files():
    files = [
        {"relative_path": "app/main.py", "content": "from fastapi import FastAPI\napp = FastAPI()\n"},
        {"relative_path": "app/models.py", "content": "class User:\n    id: int\n"},
    ]
    is_valid, errors = validate_python_syntax(files)
    assert is_valid is True
    assert len(errors) == 0


def test_ast_detects_syntax_errors():
    files = [
        {"relative_path": "app/broken.py", "content": "def bad_function(\n    print('falta parentesis')\n"},
    ]
    is_valid, errors = validate_python_syntax(files)
    assert is_valid is False
    assert len(errors) == 1
    assert "app/broken.py" in errors[0]
    assert "linea" in errors[0]


def test_ast_ignores_non_python_files():
    files = [
        {"relative_path": "README.md", "content": "# Titulo con texto invalido en python: ::::"},
        {"relative_path": "config.json", "content": "{'clave_invalida_para_py_compiler': true}"},
    ]
    is_valid, errors = validate_python_syntax(files)
    assert is_valid is True
    assert len(errors) == 0
