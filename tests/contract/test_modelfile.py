from pathlib import Path


RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


def test_modelfile_existe_y_define_un_modelo_de_referencia() -> None:
    modelfile = RAIZ_PROYECTO / "Modelfile"

    assert modelfile.is_file()
    contenido = modelfile.read_text(encoding="utf-8").strip()
    assert contenido
    assert "FROM " in contenido


def test_api_no_referencia_ollama_ni_inferencia() -> None:
    codigo_api = RAIZ_PROYECTO / "source" / "api"
    contenido = "\n".join(
        fichero.read_text(encoding="utf-8").lower()
        for fichero in codigo_api.rglob("*.py")
    )

    assert "ollama" not in contenido
    assert "api/generate" not in contenido
    assert "api/chat" not in contenido


def test_dependencias_no_incluyen_cliente_de_ollama() -> None:
    pyproject = (RAIZ_PROYECTO / "pyproject.toml").read_text(encoding="utf-8").lower()

    assert "ollama" not in pyproject
