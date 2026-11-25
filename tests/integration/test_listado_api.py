"""Pruebas de integración del endpoint ``GET /listado`` (TASK-008).

Montan una aplicación FastAPI mínima con el router del listado y un SQLite
temporal que simula el esquema real de api-persistencia, e inyectan la
configuración y el repositorio en ``app_state`` como hará el arranque de la
aplicación. Cubren los filtros combinables, la visibilidad por estado, el
orden, la paginación, el recorte del tamaño de página, los parámetros
inválidos, la base inaccesible, los campos purgados y la ausencia de
autenticación.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.listado.config import ConfigListado
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado
from source.api.listado.routes import router
from source.api.main import app_state

# Misma tabla `ofertas` que tests/unit/test_listado_repository.py: replica el
# esquema real de api-persistencia.
_SCHEMA = """\
CREATE TABLE ofertas (
    comunidad TEXT NOT NULL,
    provincia TEXT,
    codigo TEXT NOT NULL,
    ocupacion TEXT,
    municipio TEXT,
    sector TEXT DEFAULT '',
    nivel TEXT DEFAULT '',
    contrato TEXT DEFAULT '',
    fecha_inicio_difusion TEXT,
    fecha_fin_difusion TEXT,
    estado TEXT NOT NULL,
    texto_libre TEXT,
    contacto TEXT,
    embedding BLOB,
    embedding_model_name TEXT,
    embedding_model_version TEXT,
    embedding_dim INTEGER,
    interesada INTEGER DEFAULT 0,
    fecha_alta TEXT NOT NULL,
    fecha_cierre TEXT,
    fecha_ultima_actualizacion TEXT NOT NULL,
    PRIMARY KEY (comunidad, codigo)
);
"""

_SQL_INSERT = """\
INSERT INTO ofertas
    (comunidad, provincia, codigo, ocupacion, municipio, sector, nivel,
     contrato, fecha_inicio_difusion, fecha_fin_difusion, estado, texto_libre,
     contacto, embedding, embedding_model_name, embedding_model_version,
     embedding_dim, interesada, fecha_alta, fecha_cierre,
     fecha_ultima_actualizacion)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

#: Campos que exige REQ-008 en cada oferta devuelta.
_CAMPOS_OFERTA = {
    "comunidad",
    "codigo",
    "ocupacion",
    "municipio",
    "provincia",
    "sector",
    "fecha_inicio_difusion",
    "fecha_fin_difusion",
    "estado",
    "contacto",
    "texto_libre",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insertar(
    conexion: sqlite3.Connection,
    codigo: str,
    *,
    ocupacion: str = "Programador",
    municipio: str = "Santander",
    provincia: str = "Cantabria",
    sector: str = "",
    estado: str = "vigente",
    fecha_inicio: str = "15/11/2026",
    fecha_fin: str = "31/12/2026",
    texto_libre: str = "Texto libre de la oferta",
    contacto: str = "contacto@test.com",
) -> None:
    """Inserta una oferta con los valores por defecto del esquema simulado."""
    conexion.execute(
        _SQL_INSERT,
        (
            "Cantabria",
            provincia,
            codigo,
            ocupacion,
            municipio,
            sector,
            "",
            "",
            fecha_inicio,
            fecha_fin,
            estado,
            texto_libre,
            contacto,
            None,
            None,
            None,
            None,
            0,
            "2026-11-15T10:00:00+00:00",
            None,
            "2026-11-15T10:00:00+00:00",
        ),
    )


def _crear_bd(ruta: str | Path, ofertas: list[dict[str, Any]]) -> str:
    """Crea el SQLite temporal y puebla las ofertas indicadas."""
    conexion = sqlite3.connect(str(ruta))
    try:
        conexion.execute(_SCHEMA)
        for oferta in ofertas:
            _insertar(conexion, **oferta)
        conexion.commit()
    finally:
        conexion.close()
    return str(ruta)


def _cliente(ruta_bd: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Monta la app de prueba con la configuración y el repositorio inyectados.

    Reproduce lo que hará el arranque (TASK-010): la configuración y el
    repositorio viven en ``app_state`` y los lee el propio endpoint.
    """
    monkeypatch.setitem(app_state, "config_listado", ConfigListado(ruta_bd=ruta_bd))
    monkeypatch.setitem(
        app_state,
        "repositorio_listado",
        RepositorioListado(AdaptadorLecturaListado(ruta_bd)),
    )
    app_prueba = FastAPI()
    app_prueba.include_router(router)
    return TestClient(app_prueba)


#: Ofertas de prueba: vigentes, cerrada y sin_ficha, con tildes, mayúsculas,
#: campos purgados y una fecha de inicio vacía.
_OFERTAS_POR_DEFECTO: list[dict[str, Any]] = [
    {
        "codigo": "061234567890",
        "ocupacion": "Programador",
        "municipio": "Santander",
        "fecha_inicio": "30/11/2026",
        "texto_libre": "Buscamos desarrollador Python",
        "contacto": "rrhh@test.com",
    },
    {
        "codigo": "061234567891",
        "ocupacion": "Técnico de sistemas",
        "municipio": "SANTANDER",
        "fecha_inicio": "20/11/2026",
        "texto_libre": "Soporte técnico",
        "contacto": "tec@test.com",
    },
    {
        "codigo": "061234567892",
        "ocupacion": "Administrativo",
        "municipio": "Torrelavega",
        "estado": "cerrada",
        "fecha_inicio": "10/11/2026",
        "texto_libre": "",
        "contacto": "",
    },
    {
        "codigo": "061234567893",
        "ocupacion": "Auxiliar",
        "municipio": "Castro",
        "estado": "sin_ficha",
        "fecha_inicio": "05/11/2026",
    },
    {
        "codigo": "061234567894",
        "ocupacion": "Albañil",
        "municipio": "Laredo",
        "fecha_inicio": "",
        "texto_libre": "",
        "contacto": "",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ruta_bd(tmp_path: Path) -> str:
    """SQLite temporal con las ofertas por defecto."""
    return _crear_bd(tmp_path / "job_emcan.db", _OFERTAS_POR_DEFECTO)


@pytest.fixture()
def cliente(ruta_bd: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Cliente de prueba sobre el SQLite por defecto."""
    return _cliente(ruta_bd, monkeypatch)


# ---------------------------------------------------------------------------
# Pruebas: consulta sin filtros (REQ-006, REQ-008)
# ---------------------------------------------------------------------------

class TestConsultaSinFiltros:
    """Por defecto solo se ven las ofertas vigentes con los once campos."""

    def test_devuelve_las_vigentes_con_los_once_campos(
        self, cliente: TestClient
    ) -> None:
        respuesta = cliente.get("/listado")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "061234567890",
            "061234567891",
            "061234567894",
        ]
        assert datos["total"] == 3
        oferta = datos["items"][0]
        assert set(oferta) == _CAMPOS_OFERTA
        assert oferta["comunidad"] == "Cantabria"
        assert oferta["ocupacion"] == "Programador"
        assert oferta["municipio"] == "Santander"
        assert oferta["provincia"] == "Cantabria"
        assert oferta["sector"] == ""
        assert oferta["fecha_inicio_difusion"] == "30/11/2026"
        assert oferta["fecha_fin_difusion"] == "31/12/2026"
        assert oferta["estado"] == "vigente"
        assert oferta["contacto"] == "rrhh@test.com"
        assert oferta["texto_libre"] == "Buscamos desarrollador Python"

    def test_metadatos_de_paginacion_y_filtros(self, cliente: TestClient) -> None:
        datos = cliente.get(
            "/listado", params={"tamano_pagina": 2, "offset": 2}
        ).json()

        assert datos["total"] == 3
        assert datos["pagina"] == 2
        assert datos["tamano_pagina"] == 2
        assert datos["filtros_aplicados"] == {}
        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "061234567894"
        ]

    def test_fecha_vacia_queda_al_final(self, cliente: TestClient) -> None:
        datos = cliente.get("/listado").json()

        assert datos["items"][-1]["codigo"] == "061234567894"
        assert datos["items"][-1]["fecha_inicio_difusion"] == ""


# ---------------------------------------------------------------------------
# Pruebas: filtros combinables (REQ-001, REQ-002, REQ-004, REQ-005)
# ---------------------------------------------------------------------------

class TestFiltros:
    """Los filtros se combinan con AND y respetan la visibilidad por estado."""

    def test_filtros_combinados_aplican_and(self, cliente: TestClient) -> None:
        respuesta = cliente.get(
            "/listado",
            params={
                "texto": "programador",
                "municipio": "santander",
                "fecha_desde": "25/11/2026",
            },
        )

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "061234567890"
        ]
        assert datos["total"] == 1
        assert datos["filtros_aplicados"] == {
            "texto": "programador",
            "municipio": "santander",
            "fecha_desde": "25/11/2026",
        }

    def test_municipio_en_minusculas_encuentra_el_almacenado_en_mayusculas(
        self, cliente: TestClient
    ) -> None:
        datos = cliente.get("/listado", params={"municipio": "santander"}).json()

        assert {oferta["codigo"] for oferta in datos["items"]} == {
            "061234567890",
            "061234567891",
        }
        assert datos["total"] == 2

    def test_texto_con_tildes_recupera_la_ocupacion(self, cliente: TestClient) -> None:
        datos = cliente.get("/listado", params={"texto": "tecnico"}).json()

        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "061234567891"
        ]
        assert datos["total"] == 1

    def test_sector_sin_datos_devuelve_lista_vacia_valida(
        self, cliente: TestClient
    ) -> None:
        respuesta = cliente.get("/listado", params={"sector": "Informática"})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 0
        assert datos["filtros_aplicados"] == {"sector": "Informática"}


# ---------------------------------------------------------------------------
# Pruebas: visibilidad por estado (REQ-006, SUP-003)
# ---------------------------------------------------------------------------

class TestVisibilidad:
    """Por defecto solo ``vigente``; con ``incluir_cerradas`` también ``cerrada``."""

    def test_por_defecto_no_aparece_la_cerrada_ni_la_sin_ficha(
        self, cliente: TestClient
    ) -> None:
        codigos = {
            oferta["codigo"] for oferta in cliente.get("/listado").json()["items"]
        }

        assert "061234567892" not in codigos
        assert "061234567893" not in codigos

    def test_incluir_cerradas_anade_vigentes_y_cerradas(
        self, cliente: TestClient
    ) -> None:
        datos = cliente.get("/listado", params={"incluir_cerradas": True}).json()

        codigos = {oferta["codigo"] for oferta in datos["items"]}
        assert codigos == {
            "061234567890",
            "061234567891",
            "061234567892",
            "061234567894",
        }
        assert "061234567893" not in codigos
        assert datos["filtros_aplicados"] == {"incluir_cerradas": True}


# ---------------------------------------------------------------------------
# Pruebas: rango de fechas (REQ-005, ALT-004)
# ---------------------------------------------------------------------------

class TestRangoDeFechas:
    """Rango inclusive sobre ``fecha_inicio_difusion`` y sus variantes de cota."""

    @pytest.fixture()
    def cliente_fechas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> TestClient:
        ruta = _crear_bd(
            tmp_path / "fechas.db",
            [
                {"codigo": "000000000001", "fecha_inicio": "01/11/2026"},
                {"codigo": "000000000002", "fecha_inicio": "15/11/2026"},
                {"codigo": "000000000003", "fecha_inicio": "30/11/2026"},
            ],
        )
        return _cliente(ruta, monkeypatch)

    def test_rango_de_10_a_20_devuelve_solo_el_15(
        self, cliente_fechas: TestClient
    ) -> None:
        datos = cliente_fechas.get(
            "/listado",
            params={"fecha_desde": "10/11/2026", "fecha_hasta": "20/11/2026"},
        ).json()

        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "000000000002"
        ]
        assert datos["total"] == 1

    def test_solo_fecha_desde_incluye_igual_o_posterior(
        self, cliente_fechas: TestClient
    ) -> None:
        datos = cliente_fechas.get(
            "/listado", params={"fecha_desde": "10/11/2026"}
        ).json()

        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "000000000003",
            "000000000002",
        ]
        assert datos["total"] == 2

    def test_solo_fecha_hasta_incluye_igual_o_anterior(
        self, cliente_fechas: TestClient
    ) -> None:
        datos = cliente_fechas.get(
            "/listado", params={"fecha_hasta": "20/11/2026"}
        ).json()

        assert [oferta["codigo"] for oferta in datos["items"]] == [
            "000000000002",
            "000000000001",
        ]
        assert datos["total"] == 2


# ---------------------------------------------------------------------------
# Pruebas: paginación y recorte del tamaño (NFR-001, DEC-004, ALT-003)
# ---------------------------------------------------------------------------

class TestPaginacion:
    """El tamaño se recorta al máximo y un offset fuera del total es válido."""

    def test_tamano_150_se_recorta_al_maximo(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/listado", params={"tamano_pagina": 150})

        assert respuesta.status_code == 200
        assert respuesta.json()["tamano_pagina"] == 100

    def test_tamano_50_se_respeta(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/listado", params={"tamano_pagina": 50})

        assert respuesta.status_code == 200
        assert respuesta.json()["tamano_pagina"] == 50

    def test_offset_mayor_que_el_total_devuelve_pagina_vacia(
        self, cliente: TestClient
    ) -> None:
        respuesta = cliente.get("/listado", params={"offset": 100})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 3


# ---------------------------------------------------------------------------
# Pruebas: parámetros inválidos (REQ-009, ALT-002)
# ---------------------------------------------------------------------------

class TestParametrosInvalidos:
    """Se rechazan con 400 identificando el parámetro, sin tocar la base."""

    @pytest.mark.parametrize("tamano", [0, -1])
    def test_tamano_de_pagina_no_positivo(
        self, cliente: TestClient, tamano: int
    ) -> None:
        respuesta = cliente.get("/listado", params={"tamano_pagina": tamano})

        assert respuesta.status_code == 400
        assert "tamano_pagina" in respuesta.json()["detail"]

    def test_offset_negativo(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/listado", params={"offset": -1})

        assert respuesta.status_code == 400
        assert "offset" in respuesta.json()["detail"]

    def test_fecha_mal_formada_indica_el_formato(self, cliente: TestClient) -> None:
        respuesta = cliente.get(
            "/listado", params={"fecha_desde": "32/13/2026"}
        )

        assert respuesta.status_code == 400
        detalle = respuesta.json()["detail"]
        assert "dd/mm/aaaa" in detalle
        assert "fecha_desde" in detalle

    def test_rango_invertido(self, cliente: TestClient) -> None:
        respuesta = cliente.get(
            "/listado",
            params={"fecha_desde": "21/11/2026", "fecha_hasta": "20/11/2026"},
        )

        assert respuesta.status_code == 400
        assert "rango" in respuesta.json()["detail"].lower()

    def test_parametro_invalido_no_llega_a_la_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta_inexistente = str(tmp_path / "no_existe.db")
        cliente = _cliente(ruta_inexistente, monkeypatch)

        respuesta = cliente.get("/listado", params={"fecha_desde": "32/13/2026"})

        # Si hubiera llegado a la base, el adaptador habría devuelto 503.
        assert respuesta.status_code == 400
        assert not Path(ruta_inexistente).exists()


# ---------------------------------------------------------------------------
# Pruebas: sin coincidencias (REQ-009)
# ---------------------------------------------------------------------------

class TestSinCoincidencias:
    """Un filtro sin resultados devuelve lista vacía con total 0 y sin error."""

    def test_texto_sin_coincidencias(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/listado", params={"texto": "astronauta"})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 0


# ---------------------------------------------------------------------------
# Pruebas: base inaccesible (ALT-001)
# ---------------------------------------------------------------------------

class TestAccesoADatos:
    """Una base inexistente o sin la tabla ``ofertas`` devuelve 503 controlado."""

    def test_base_inexistente(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta_inexistente = str(tmp_path / "no_existe.db")
        cliente = _cliente(ruta_inexistente, monkeypatch)

        respuesta = cliente.get("/listado")

        assert respuesta.status_code == 503
        assert "No se puede acceder a los datos" in respuesta.json()["detail"]
        assert not Path(ruta_inexistente).exists()

    def test_base_sin_tabla_ofertas(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta = str(tmp_path / "sin_ofertas.db")
        conexion = sqlite3.connect(ruta)
        try:
            conexion.execute("CREATE TABLE otra (dato TEXT)")
            conexion.commit()
        finally:
            conexion.close()
        cliente = _cliente(ruta, monkeypatch)

        respuesta = cliente.get("/listado")

        assert respuesta.status_code == 503
        assert "No se puede acceder a los datos" in respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# Pruebas: campos purgados (REQ-008, ALT-006)
# ---------------------------------------------------------------------------

class TestCamposPurgados:
    """Una oferta purgada se devuelve con texto y contacto vacíos."""

    def test_campos_vacios_y_resto_intacto(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ruta = _crear_bd(
            tmp_path / "purgada.db",
            [
                {
                    "codigo": "061234567890",
                    "ocupacion": "Programador",
                    "municipio": "Santander",
                    "texto_libre": "",
                    "contacto": "",
                }
            ],
        )
        cliente = _cliente(ruta, monkeypatch)

        respuesta = cliente.get("/listado")

        assert respuesta.status_code == 200
        oferta = respuesta.json()["items"][0]
        assert oferta["texto_libre"] == ""
        assert oferta["contacto"] == ""
        assert oferta["ocupacion"] == "Programador"
        assert oferta["municipio"] == "Santander"
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Pruebas: disponibilidad de la feature y autenticación
# ---------------------------------------------------------------------------

class TestDisponibilidadYAutenticacion:
    """Sin estado en ``app_state`` la feature no está disponible (503)."""

    def test_sin_configuracion_devuelve_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delitem(app_state, "config_listado", raising=False)
        monkeypatch.delitem(app_state, "repositorio_listado", raising=False)
        app_prueba = FastAPI()
        app_prueba.include_router(router)

        respuesta = TestClient(app_prueba).get("/listado")

        assert respuesta.status_code == 503

    def test_sin_repositorio_devuelve_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(app_state, "config_listado", ConfigListado())
        monkeypatch.delitem(app_state, "repositorio_listado", raising=False)
        app_prueba = FastAPI()
        app_prueba.include_router(router)

        respuesta = TestClient(app_prueba).get("/listado")

        assert respuesta.status_code == 503

    def test_no_exige_autenticacion(self, cliente: TestClient) -> None:
        respuesta = cliente.get("/listado")

        assert respuesta.status_code == 200
        assert respuesta.status_code not in (401, 403)
        assert "www-authenticate" not in respuesta.headers
