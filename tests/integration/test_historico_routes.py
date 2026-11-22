"""Tests de integración de los endpoints de consulta del histórico (TASK-017).

Verifica que:
- Los 4 endpoints responden correctamente con datos válidos.
- Los parámetros de fecha se validan (formato y rango).
- Los datos devueltos tienen la estructura correcta.
- El endpoint ``/resumen`` agrupa correctamente por día.
- Los endpoints no exigen autenticación.
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.historico.read_adapter import AdaptadorLecturaHistorica
from source.api.historico.routes import router


# ---------------------------------------------------------------------------
# Fijtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bd_persistencia(tmp_path: Path) -> str:
    """Crea un SQLite temporal con el esquema de ``ofertas`` y datos de prueba."""
    ruta = str(tmp_path / "test_job_emcan.db")
    conn = sqlite3.connect(ruta)
    conn.execute(
        """
        CREATE TABLE ofertas (
            comunidad TEXT NOT NULL,
            codigo TEXT NOT NULL,
            ocupacion TEXT,
            municipio TEXT,
            estado TEXT NOT NULL DEFAULT 'vigente',
            fecha_alta TEXT NOT NULL,
            fecha_fin_difusion TEXT,
            fecha_cierre TEXT,
            texto TEXT,
            contacto TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO ofertas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # Alta el 10/11
            (
                "Cantabria",
                "062026001111",
                "Ingeniero",
                "Santander",
                "vigente",
                "2026-11-10",
                None,
                None,
                "",
                "",
            ),
            # Alta el 12/11, cerrada el 15/11
            (
                "Cantabria",
                "062026002222",
                "Técnico",
                "Torrelavega",
                "cerrada",
                "2026-11-12",
                "2026-11-15",
                "2026-11-15",
                "",
                "",
            ),
            # Alta el 14/11, cerrada el 16/11, fecha_fin_difusion 2026-11-14
            (
                "Cantabria",
                "062026003333",
                "Administrativo",
                "Castro",
                "cerrada",
                "2026-11-14",
                "2026-11-14",
                "2026-11-16",
                "",
                "",
            ),
            # Alta el 18/11, sin cierre (vigente)
            (
                "Cantabria",
                "062026004444",
                "Auxiliar",
                "Laredo",
                "vigente",
                "2026-11-18",
                None,
                None,
                "",
                "",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return ruta


@pytest.fixture()
def app(bd_persistencia: str) -> FastAPI:
    """Crea una app FastAPI de prueba con el adaptador inyectado."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state._bd_persistencia = bd_persistencia
    return test_app


@pytest.fixture()
def client(app: FastAPI, bd_persistencia: str) -> TestClient:
    """Cliente de prueba con el adaptador de lectura inyectado vía monkeypatch."""
    adaptador = AdaptadorLecturaHistorica(bd_persistencia)
    with patch("source.api.historico.routes._obtener_adaptador", return_value=adaptador):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Tests de GET /historico/altas
# ---------------------------------------------------------------------------


class TestAltas:
    def test_altas_rango_completo(self, client: TestClient) -> None:
        """Las 4 ofertas tienen fecha_alta entre el 10 y el 18 de noviembre."""
        resp = client.get(
            "/historico/altas", params={"desde": "2026-11-10", "hasta": "2026-11-18"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4

    def test_altas_rango_parcial(self, client: TestClient) -> None:
        """Solo dos ofertas tienen fecha_alta entre el 10 y el 12."""
        resp = client.get(
            "/historico/altas", params={"desde": "2026-11-10", "hasta": "2026-11-12"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        codigos = {o["codigo"] for o in data}
        assert codigos == {"062026001111", "062026002222"}

    def test_altas_rango_vacio(self, client: TestClient) -> None:
        """Un rango sin ofertas devuelve lista vacía sin error."""
        resp = client.get(
            "/historico/altas", params={"desde": "2027-01-01", "hasta": "2027-01-31"}
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_altas_campos_minimos(self, client: TestClient) -> None:
        """Cada oferta contiene los campos mínimos: comunidad, codigo, etc."""
        resp = client.get(
            "/historico/altas", params={"desde": "2026-11-10", "hasta": "2026-11-10"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        oferta = data[0]
        for campo in ("comunidad", "codigo", "ocupacion", "municipio", "fecha_alta"):
            assert campo in oferta, f"Falta el campo '{campo}'"
        assert oferta["comunidad"] == "Cantabria"
        assert oferta["codigo"] == "062026001111"
        assert oferta["fecha_alta"] == "2026-11-10"


# ---------------------------------------------------------------------------
# Tests de GET /historico/cierres
# ---------------------------------------------------------------------------


class TestCierres:
    def test_cierres_rango(self, client: TestClient) -> None:
        """Dos ofertas cerradas con fecha_cierre entre el 15 y el 16."""
        resp = client.get(
            "/historico/cierres", params={"desde": "2026-11-15", "hasta": "2026-11-16"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        codigos = {o["codigo"] for o in data}
        assert codigos == {"062026002222", "062026003333"}

    def test_cierres_sin_resultados(self, client: TestClient) -> None:
        """Rango sin cierres devuelve lista vacía."""
        resp = client.get(
            "/historico/cierres", params={"desde": "2026-11-01", "hasta": "2026-11-09"}
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cierres_solo_cerradas(self, client: TestClient) -> None:
        """Las ofertas vigentes no aparecen en cierres."""
        resp = client.get(
            "/historico/cierres", params={"desde": "2026-11-10", "hasta": "2026-11-30"}
        )
        data = resp.json()
        codigos = {o["codigo"] for o in data}
        # Las ofertas 001111 y 004444 son vigentes (sin fecha_cierre).
        assert "062026001111" not in codigos
        assert "062026004444" not in codigos


# ---------------------------------------------------------------------------
# Tests de GET /historico/cierres-por-fin-difusion
# ---------------------------------------------------------------------------


class TestCierresPorFinDifusion:
    def test_cierres_fin_difusion_rango(self, client: TestClient) -> None:
        """Solo la oferta 003333 tiene fecha_fin_difusion en el rango."""
        resp = client.get(
            "/historico/cierres-por-fin-difusion",
            params={"desde": "2026-11-14", "hasta": "2026-11-14"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["codigo"] == "062026003333"

    def test_cierres_fin_difusion_sin_resultados(self, client: TestClient) -> None:
        """Rango sin fecha_fin_difusion devuelve lista vacía."""
        resp = client.get(
            "/historico/cierres-por-fin-difusion",
            params={"desde": "2026-12-01", "hasta": "2026-12-31"},
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Tests de GET /historico/resumen
# ---------------------------------------------------------------------------


class TestResumen:
    def test_resumen_un_dia(self, client: TestClient) -> None:
        """Resumen de un día con una alta y cero cierres."""
        resp = client.get(
            "/historico/resumen", params={"desde": "2026-11-10", "hasta": "2026-11-10"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["fecha"] == "2026-11-10"
        assert data[0]["altas"] == 1
        assert data[0]["cierres"] == 0

    def test_resumen_rango_varios_dias(self, client: TestClient) -> None:
        """Resumen de 3 días devuelve 3 entradas."""
        resp = client.get(
            "/historico/resumen",
            params={"desde": "2026-11-10", "hasta": "2026-11-12"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        fechas = [d["fecha"] for d in data]
        assert fechas == ["2026-11-10", "2026-11-11", "2026-11-12"]

    def test_resumen_agrupa_altas_y_cierres(self, client: TestClient) -> None:
        """El día 15 tiene 0 altas y 1 cierre; el 16 tiene 0 altas y 1 cierre."""
        resp = client.get(
            "/historico/resumen",
            params={"desde": "2026-11-14", "hasta": "2026-11-16"},
        )
        data = resp.json()
        # Día 14: 1 alta, 0 cierres.
        assert data[0] == {"fecha": "2026-11-14", "altas": 1, "cierres": 0}
        # Día 15: 0 altas, 1 cierre.
        assert data[1] == {"fecha": "2026-11-15", "altas": 0, "cierres": 1}
        # Día 16: 0 altas, 1 cierre.
        assert data[2] == {"fecha": "2026-11-16", "altas": 0, "cierres": 1}

    def test_resumen_sin_datos(self, client: TestClient) -> None:
        """Un rango sin datos devuelve recuentos a 0."""
        resp = client.get(
            "/historico/resumen",
            params={"desde": "2027-01-01", "hasta": "2027-01-02"},
        )
        data = resp.json()
        assert len(data) == 2
        for dia in data:
            assert dia["altas"] == 0
            assert dia["cierres"] == 0


# ---------------------------------------------------------------------------
# Tests de validación de parámetros
# ---------------------------------------------------------------------------


class TestValidacionParametros:
    def test_fecha_desde_invalida(self, client: TestClient) -> None:
        """Fecha 'desde' con formato inválido devuelve 400."""
        resp = client.get(
            "/historico/altas", params={"desde": "no-es-fecha", "hasta": "2026-11-10"}
        )
        assert resp.status_code == 400
        assert "desde" in resp.json()["detail"]

    def test_fecha_hasta_invalida(self, client: TestClient) -> None:
        """Fecha 'hasta' con formato inválido devuelve 400."""
        resp = client.get(
            "/historico/altas", params={"desde": "2026-11-10", "hasta": "11/10/2026"}
        )
        assert resp.status_code == 400
        assert "hasta" in resp.json()["detail"]

    def test_desde_posterior_a_hasta(self, client: TestClient) -> None:
        """``desde > hasta`` devuelve 400."""
        resp = client.get(
            "/historico/altas", params={"desde": "2026-11-20", "hasta": "2026-11-10"}
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "posterior" in detail

    def test_validacion_en_todos_los_endpoints(self, client: TestClient) -> None:
        """La validación se aplica en los 4 endpoints."""
        endpoints = [
            "/historico/altas",
            "/historico/cierres",
            "/historico/cierres-por-fin-difusion",
            "/historico/resumen",
        ]
        for endpoint in endpoints:
            resp = client.get(
                endpoint, params={"desde": "invalido", "hasta": "2026-11-10"}
            )
            assert resp.status_code == 400, f"Fallo en {endpoint}"


# ---------------------------------------------------------------------------
# Tests de no-autenticación
# ---------------------------------------------------------------------------


class TestSinAutenticacion:
    def test_sin_cabeceras_de_autenticacion(self, client: TestClient) -> None:
        """Los endpoints responden 200 sin cabeceras de autenticación."""
        endpoints = [
            "/historico/altas",
            "/historico/cierres",
            "/historico/cierres-por-fin-difusion",
            "/historico/resumen",
        ]
        for endpoint in endpoints:
            resp = client.get(
                endpoint, params={"desde": "2026-11-10", "hasta": "2026-11-18"}
            )
            assert resp.status_code not in (401, 403), (
                f"{endpoint} exige autenticación"
            )
