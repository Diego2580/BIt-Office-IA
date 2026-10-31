from office import classify_task_complexity


def test_classify_task_lite():
    prompt = "agrega un campo status: str a la respuesta"
    result = classify_task_complexity(prompt, existing_files_count=3)
    assert result["tier"] == "TIER_LITE"
    assert "gemini-3.5-flash-lite" in result["primary_model"]
    assert len(result["models_chain"]) > 1


def test_classify_task_standard():
    prompt = "Crea un router modular para productos con endpoints GET, POST y validaciones"
    result = classify_task_complexity(prompt, existing_files_count=4)
    assert result["tier"] == "TIER_STANDARD"
    assert "gemini-3.5-flash" in result["primary_model"]


def test_classify_task_pro_by_keywords():
    prompt = "Rediseña la arquitectura del sistema aplicando el patron repositorio y microservicios"
    result = classify_task_complexity(prompt, existing_files_count=5)
    assert result["tier"] == "TIER_PRO"
    assert "Complejidad estructural alta" in result["reason"]


def test_classify_task_pro_by_prompt_length():
    long_prompt = " ".join(["requerimiento detallado para reconfigurar el servicio"] * 10)
    result = classify_task_complexity(long_prompt, existing_files_count=2)
    assert result["tier"] == "TIER_PRO"


def test_classify_task_pro_by_files_volume():
    result = classify_task_complexity("Actualiza la importacion en main", existing_files_count=20)
    assert result["tier"] == "TIER_PRO"
