"""Pruebas de integración del endpoint ``GET /listado/filtros`` (TASK-009).

Montan una aplicación FastAPI mínima con el router del listado para comprobar
que la respuesta anuncia los seis filtros soportados con su tipo, formato y
ejemplo, que ``sector`` figura pese a no tener datos, que ``oficina`` no
aparece, que las fechas anuncian ``dd/mm/aaaa``, que el endpoint no toca el
SQLite de api-persistencia (ni siquiera necesita que exista) y que no exige
autenticación.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.listado.config import ConfigListado
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado
from source.api.listado.routes import router
from source.api.main import app_state

#: Filtros que debe anunciar el endpoint, en el orden de la respuesta.
_NOMBRES_ESPERADOS = [
    "texto",
    "sector",
    "municipio",
    "fecha_desde",
    "fecha_hasta",
    "incluir_cerradas",
]

#: Metadatos que debe llevar cada filtro anunciado (DEC-005).
_CAMPOS_FILTRO = {"nombre", "tipo", "formato", "ejemplo"}

#: Tabla mínima que replica el esquema real de api-persistencia.
_SCHEMA = """\
CREATE TABLE ofertas (
    comunidad TEXT NOT NULL,
    provincia TEXT,
    codigo TEXT NOT NULL,
    ocupacion TEXT,
    municipio TEXT,
    sector TEXT DEFAULT '',
    fecha_inicio_difusion TEXT,
    fecha_fin_difusion TEXT,
    estado TEXT NOT NULL,
    texto_libre TEXT,
    contacto TEXT,
    PRIMARY KEY (comunidad, codigo)
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cliente() -> TestClient:
    """Cliente de prueba con el router del listado y sin estado inyectado."""
    app_prueba = FastAPI()
    app_prueba.include_router(router)
    return TestClient(app_prueba)


def _crear_bd(ruta: Path) -> str:
    """Crea un SQLite temporal con la tabla ``ofertas`` y una oferta."""
    conexion = sqlite3.connect(str(ruta))
    try:
        conexion.execute(_SCHEMA)
        conexion.execute(
            "INSERT INTO ofertas (comunidad, provincia, codigo, ocupacion, "
            "municipio, sector, fecha_inicio_difusion, fecha_fin_difusion, "
            "estado, texto_libre, contacto) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "Cantabria",
                "Cantabria",
                "061234567890",
                "Programador",
                "Santander",
                "",
                "15/11/2026",
                "31/12/2026",
                "vigente",
                "Buscamos desarrollador Python",
                "rrhh@test.com",
            ),
        )
        conexion.commit()
    finally:
        conexion.close()
    return str(ruta)


# ---------------------------------------------------------------------------
# Pruebas: filtros anunciados (REQ-003, REQ-005, DEC-005, SUP-002, ALT-007)
# ---------------------------------------------------------------------------

class TestFiltrosAnunciados:
    """La respuesta lista los seis filtros soportados con sus metadatos."""

    def test_contiene_los_seis_filtros(self) -> None:
        respuesta = _cliente().get("/listado/filtros")

        assert respuesta.status_code == 200
        nombres = [filtro["nombre"] for filtro in respuesta.json()["filtros"]]
        assert nombres == _NOMBRES_ESPERADOS

    def test_cada_filtro_lleva_tipo_formato_y_ejemplo(self) -> None:
        filtros = _cliente().get("/listado/filtros").json()["filtros"]

        assert len(filtros) == len(_NOMBRES_ESPERADOS)
        for filtro in filtros:
            assert set(filtro) == _CAMPOS_FILTRO
            assert filtro["tipo"]
            assert filtro["formato"]
            assert filtro["ejemplo"]

    def test_sector_figura_aunque_no_haya_datos(self) -> None:
        filtros = _cliente().get("/listado/filtros").json()["filtros"]

        sector = next(
            (filtro for filtro in filtros if filtro["nombre"] == "sector"), None
        )
        assert sector is not None
        assert sector["tipo"]
        assert sector["formato"]
        assert sector["ejemplo"]

    def test_no_anuncia_oficina(self) -> None:
        respuesta = _cliente().get("/listado/filtros")

        nombres = [filtro["nombre"] for filtro in respuesta.json()["filtros"]]
        assert "oficina" not in nombres
        assert "oficina" not in respuesta.text.lower()

    def test_las_fechas_anuncian_el_formato_dd_mm_aaaa(self) -> None:
        filtros = _cliente().get("/listado/filtros").json()["filtros"]

        for nombre in ("fecha_desde", "fecha_hasta"):
            filtro = next(f for f in filtros if f["nombre"] == nombre)
            assert "dd/mm/aaaa" in filtro["formato"]


# ---------------------------------------------------------------------------
# Pruebas: solo lectura y autenticación (REQ-010)
# ---------------------------------------------------------------------------

class TestSoloLecturaYAutenticacion:
    """El endpoint no lee ni escribe la base y no exige autenticación."""

    def test_no_modifica_la_base_ni_su_marca_de_modificacion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta_bd = _crear_bd(tmp_path / "job_emcan.db")
        monkeypatch.setitem(
            app_state, "config_listado", ConfigListado(ruta_bd=ruta_bd)
        )
        monkeypatch.setitem(
            app_state,
            "repositorio_listado",
            RepositorioListado(AdaptadorLecturaListado(ruta_bd)),
        )
        marca_antes = Path(ruta_bd).stat().st_mtime_ns

        respuesta = _cliente().get("/listado/filtros")

        assert respuesta.status_code == 200
        assert Path(ruta_bd).stat().st_mtime_ns == marca_antes

    def test_no_necesita_que_la_base_exista(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta_inexistente = str(tmp_path / "no_existe.db")
        monkeypatch.setitem(
            app_state, "config_listado", ConfigListado(ruta_bd=ruta_inexistente)
        )
        monkeypatch.setitem(
            app_state,
            "repositorio_listado",
            RepositorioListado(AdaptadorLecturaListado(ruta_inexistente)),
        )

        respuesta = _cliente().get("/listado/filtros")

        assert respuesta.status_code == 200
        assert not Path(ruta_inexistente).exists()

    def test_responde_sin_estado_inyectado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(app_state, "config_listado", raising=False)
        monkeypatch.delitem(app_state, "repositorio_listado", raising=False)

        respuesta = _cliente().get("/listado/filtros")

        assert respuesta.status_code == 200

    def test_no_exige_autenticacion(self) -> None:
        respuesta = _cliente().get("/listado/filtros")

        assert respuesta.status_code == 200
        assert respuesta.status_code not in (401, 403)
        assert "www-authenticate" not in respuesta.headers
