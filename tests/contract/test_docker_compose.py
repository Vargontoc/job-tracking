"""Contratos de los artefactos de contenedor de la API."""

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def cargar_compose() -> dict[str, object]:
    with (ROOT / "docker-compose.yaml").open(encoding="utf-8") as compose_file:
        return yaml.safe_load(compose_file)


def test_compose_define_unicamente_la_api_en_el_puerto_8000() -> None:
    compose = cargar_compose()

    assert set(compose["services"]) == {"api"}
    api = compose["services"]["api"]
    assert api["build"] == "."
    assert api["ports"] == ["8000:8000"]
    assert "volumes" not in compose
    assert "volumes" not in api


def test_dockerfile_usa_python_312_y_arranca_la_api() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.startswith("FROM python:3.12-slim")
    assert '"--host", "0.0.0.0"' in dockerfile
    assert '"--port", "8000"' in dockerfile
    assert "source.api.main:app" in dockerfile


def test_docker_compose_config_es_valido() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker no está disponible en el entorno de pruebas.")

    resultado = subprocess.run(
        [docker, "compose", "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert resultado.returncode == 0, resultado.stderr
