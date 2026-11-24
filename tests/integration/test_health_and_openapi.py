"""Tests para verificar que los endpoints del buscador aparecen en OpenAPI y el healthcheck."""

import pytest
from fastapi.testclient import TestClient

from source.api.integridad.task import TareaIntegridad
from source.api.main import app


@pytest.fixture(autouse=True)
def _aislar_tarea_integridad(monkeypatch):
    """Evita que la tarea de integridad descargue el PDF real o purgue data/pdfs.

    Al arrancar la app real, ``TareaIntegridad.iniciar`` puede adelantar la
    comprobación del día y descargar el PDF de difusión real o purgar
    ``data/pdfs``. Se sustituye por una función vacía para que el ``lifespan``
    no arranque ningún hilo de trabajo.
    """
    monkeypatch.setattr(TareaIntegridad, "iniciar", lambda self: None)


def test_health_endpoint_responde_200():
    """El endpoint /health responde 200 con status healthy."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": "healthy"}


def test_health_endpoint_contenido_json():
    """El endpoint /health devuelve JSON válido con la clave 'status'."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"


def test_buscador_run_aparece_en_openapi():
    """El endpoint POST /buscador/run aparece en el schema OpenAPI."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/buscador/run" in schema["paths"]
        assert "post" in schema["paths"]["/buscador/run"]


def test_buscador_status_aparece_en_openapi():
    """El endpoint GET /buscador/status aparece en el schema OpenAPI."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/buscador/status" in schema["paths"]
        assert "get" in schema["paths"]["/buscador/status"]


def test_buscador_routes_tienen_tag():
    """Los endpoints del buscador tienen el tag 'buscador' en OpenAPI."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        schema = response.json()
        
        # Verificar POST /buscador/run
        run_endpoint = schema["paths"]["/buscador/run"]["post"]
        assert "buscador" in run_endpoint.get("tags", [])
        
        # Verificar GET /buscador/status
        status_endpoint = schema["paths"]["/buscador/status"]["get"]
        assert "buscador" in status_endpoint.get("tags", [])


def test_todas_las_rutas_registradas():
    """Todas las rutas esperadas están registradas en la app."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        schema = response.json()
        paths = list(schema["paths"].keys())
        
        # Rutas esperadas
        assert "/health" in paths
        assert "/parse" in paths
        assert "/buscador/run" in paths
        assert "/buscador/status" in paths
