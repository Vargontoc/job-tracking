"""Verificación de integración de extremo a extremo del listado (TASK-011).

Monta la aplicación real de ``source/api/main.py`` con ``TestClient`` y un
entorno temporal (configuraciones de buscador, persistencia, histórico,
integridad y listado en ``tmp_path``). El SQLite de persistencia se crea en
``tmp_path`` replicando la ``CREATE TABLE ofertas`` de
``source/api/persistencia/migrations.py`` (más ``schema_version`` en la versión
1, para que el arranque no vuelva a aplicar la migración) y se puebla con
ofertas ``vigente``, ``cerrada`` y ``sin_ficha``, ``sector`` vacío, fechas en
``dd/mm/aaaa`` y alguna ``fecha_inicio_difusion`` vacía.

Se recorre la cadena completa (configuración, adaptador ``mode=ro``, parser de
fechas, normalizador, constructor de filtros, repositorio y endpoints) con los
escenarios de la ficha: campos de REQ-008, filtros AND, texto con tildes y su
``total`` filtrado, texto más desplazamiento, desempate por código, visibilidad
por estado, sector inerte, ``offset`` fuera del total, parámetros inválidos sin
llegar a la base, base inexistente o sin tabla, fecha vacía al final y fuera de
rango, campos purgados, lectura concurrente con una escritura simulada
(ALT-005), base con contenido y ``st_mtime_ns`` intactos y no regresión de los
endpoints de los sprints 02–05.

Los hilos reales de las tareas de fondo no ejecutan trabajo: el planificador
del buscador no arranca y la ingesta, la purga, el histórico y la integridad
tienen sus métodos de ejecución sustituidos por dobles, de modo que no hay red
real ni escrituras en ``data/``.
"""

from __future__ import annotations

import hashlib
import importlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from source.api.buscador.scheduler import Scheduler
from source.api.historico.task import TareaHistorico
from source.api.integridad.task import AccionArranque, TareaIntegridad
from source.api.listado.config import ConfigListado
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga

#: SQLite real de api-persistencia: la integración no debe tocarlo (REQ-010).
RUTA_BD_REAL = Path("data/job_emcan.db")

#: Campos que exige REQ-008 en cada oferta devuelta.
_CAMPOS_OFERTA = frozenset(
    {
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
)

#: Esquema que replica ``CREATE TABLE ofertas`` de api-persistencia.
#:
#: ``schema_version`` queda en la versión 1 para que el arranque de la
#: aplicación no reaplique la migración 001 sobre una tabla ya creada.
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
CREATE INDEX idx_ofertas_estado_fecha_fin ON ofertas(estado, fecha_fin_difusion);
CREATE INDEX idx_ofertas_embedding_model
    ON ofertas(embedding_model_name, embedding_model_version);
CREATE TABLE ingesta_log (
    id INTEGER PRIMARY KEY,
    ultimo_timestamp TEXT,
    actualizado_en TEXT NOT NULL
);
INSERT INTO ingesta_log (id, ultimo_timestamp, actualizado_en)
    VALUES (1, NULL, '2026-11-01T00:00:00+00:00');
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
INSERT INTO schema_version (version, applied_at)
    VALUES (1, '2026-11-01T00:00:00+00:00');
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


# ---------------------------------------------------------------------------
# Datos de prueba
# ---------------------------------------------------------------------------

#: Ofertas del SQLite temporal.
#:
#: Orden esperado por defecto (fecha de inicio descendente, nulos al final y
#: desempate por código ascendente): ``890`` (30/11), ``899`` (25/11), ``891``
#: (20/11), ``896`` (18/11), ``897`` (18/11), ``898`` (12/11) y ``894`` (fecha
#: vacía). La ``cerrada`` (``892``) y la ``sin_ficha`` (``893``) quedan fuera
#: del listado por defecto.
_OFERTAS: list[dict[str, Any]] = [
    {
        "codigo": "061234567890",
        "ocupacion": "Programador",
        "municipio": "Santander",
        "fecha_inicio": "30/11/2026",
        "texto_libre": "Buscamos desarrollador Python",
        "contacto": "rrhh@test.com",
    },
    {
        # Oferta con texto y contacto purgados (ALT-006).
        "codigo": "061234567899",
        "ocupacion": "Comercial",
        "municipio": "Santander",
        "fecha_inicio": "25/11/2026",
        "texto_libre": "",
        "contacto": "",
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
        "codigo": "061234567896",
        "ocupacion": "Analista",
        "municipio": "Torrelavega",
        "fecha_inicio": "18/11/2026",
        "texto_libre": "Conocimientos de Python",
    },
    {
        # Misma fecha que la anterior: desempata por código ascendente.
        "codigo": "061234567897",
        "ocupacion": "Analista funcional",
        "municipio": "Torrelavega",
        "fecha_inicio": "18/11/2026",
        "texto_libre": "Sin requisitos",
    },
    {
        "codigo": "061234567898",
        "ocupacion": "Becario",
        "municipio": "Reinosa",
        "fecha_inicio": "12/11/2026",
        "texto_libre": "Python y SQL",
    },
    {
        # Fecha de inicio vacía: al final y fuera de los filtros de rango.
        "codigo": "061234567894",
        "ocupacion": "Albañil",
        "municipio": "Laredo",
        "fecha_inicio": "",
    },
    {
        "codigo": "061234567892",
        "ocupacion": "Administrativo",
        "municipio": "Torrelavega",
        "estado": "cerrada",
        "fecha_inicio": "10/11/2026",
    },
    {
        "codigo": "061234567893",
        "ocupacion": "Auxiliar",
        "municipio": "Castro",
        "estado": "sin_ficha",
        "fecha_inicio": "05/11/2026",
    },
]

#: Códigos del listado por defecto, en el orden esperado (REQ-006, REQ-007).
_CODIGOS_VIGENTES = [
    "061234567890",
    "061234567899",
    "061234567891",
    "061234567896",
    "061234567897",
    "061234567898",
    "061234567894",
]


# ---------------------------------------------------------------------------
# SQLite temporal que replica el esquema real
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
    texto_libre: str = "",
    contacto: str = "",
) -> None:
    """Inserta una oferta con los valores por defecto del esquema simulado."""
    conexion.execute(
        _SQL_INSERT,
        (
            "Cantabria",  # comunidad
            provincia,  # provincia
            codigo,  # codigo
            ocupacion,  # ocupacion
            municipio,  # municipio
            sector,  # sector
            "",  # nivel
            "",  # contrato
            fecha_inicio,  # fecha_inicio_difusion
            fecha_fin,  # fecha_fin_difusion
            estado,  # estado
            texto_libre,  # texto_libre
            contacto,  # contacto
            None,  # embedding
            None,  # embedding_model_name
            None,  # embedding_model_version
            None,  # embedding_dim
            0,  # interesada
            "2026-11-15T10:00:00+00:00",  # fecha_alta
            None,  # fecha_cierre
            "2026-11-15T10:00:00+00:00",  # fecha_ultima_actualizacion
        ),
    )


def _crear_bd(ruta: str | Path, ofertas: list[dict[str, Any]]) -> str:
    """Crea el SQLite temporal con el esquema real simulado y sus ofertas."""
    conexion = sqlite3.connect(str(ruta))
    try:
        conexion.executescript(_SCHEMA)
        for oferta in ofertas:
            _insertar(conexion, **oferta)
        conexion.commit()
    finally:
        conexion.close()
    return str(ruta)


# ---------------------------------------------------------------------------
# Entorno temporal
# ---------------------------------------------------------------------------


@dataclass
class Entorno:
    """Rutas del entorno de prueba dentro de ``tmp_path``."""

    tmp_path: Path
    ruta_bd: str
    ruta_bd_historico: str
    pdfs_dir: Path
    seen_codes_path: str
    config_persistencia_path: Path
    config_historico_path: Path
    config_integridad_path: Path
    config_listado_path: Path


def _crear_entorno(tmp_path: Path) -> Entorno:
    """Crea las configuraciones y el SQLite temporal para montar la app real."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    pdfs_dir = data_dir / "pdfs"

    ruta_bd = _crear_bd(data_dir / "persistencia.db", _OFERTAS)
    ruta_bd_historico = str(data_dir / "historico.db")

    seen_codes_path = data_dir / "seen_codes.json"
    seen_codes_path.write_text("[]", encoding="utf-8")

    config_persistencia = config_dir / "persistencia.yaml"
    config_persistencia.write_text(
        "base_de_datos:\n"
        f"  ruta: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "ingesta:\n"
        "  cadencia_segundos: 3600\n"
        "purga:\n"
        "  dias_retencion: 7\n"
        "  frecuencia_segundos: 86400\n",
        encoding="utf-8",
    )

    config_historico = config_dir / "historico.yaml"
    config_historico.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "ausencias_consecutivas: 2\n"
        "umbral_caida_pct: 30\n"
        "recuento_minimo: 70\n"
        "rutas:\n"
        f"  sqlite_historico: {ruta_bd_historico}\n"
        f"  sqlite_persistencia: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "persistencia:\n"
        "  url_base: http://localhost:19999\n"
        "pdf:\n"
        "  comunidad: Cantabria\n"
        "  identificador: cantabria\n",
        encoding="utf-8",
    )

    config_integridad = config_dir / "integridad.yaml"
    config_integridad.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "margen_catchup: 60\n"
        "dias_retencion: 30\n"
        "tolerancia_absoluta: 1\n"
        "tolerancia_relativa_pct: 5\n"
        "umbral_cordura: 70\n"
        "rutas:\n"
        f"  base_pdfs: {pdfs_dir}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "comunidades:\n"
        "  - identificador: cantabria\n"
        "    url_pdf: http://localhost:19999/cantabria.pdf\n",
        encoding="utf-8",
    )

    # El listado lee el mismo SQLite de persistencia en modo solo lectura.
    # Sin comillas: la ruta de Windows conserva sus separadores como literal.
    config_listado = config_dir / "listado.yaml"
    config_listado.write_text(
        f"ruta_bd: {ruta_bd}\n"
        "tamano_pagina_por_defecto: 20\n"
        "tamano_pagina_maximo: 100\n",
        encoding="utf-8",
    )

    return Entorno(
        tmp_path=tmp_path,
        ruta_bd=ruta_bd,
        ruta_bd_historico=ruta_bd_historico,
        pdfs_dir=pdfs_dir,
        seen_codes_path=str(seen_codes_path),
        config_persistencia_path=config_persistencia,
        config_historico_path=config_historico,
        config_integridad_path=config_integridad,
        config_listado_path=config_listado,
    )


def _parchear(monkeypatch: pytest.MonkeyPatch, entorno: Entorno) -> None:
    """Aísla las tareas de fondo y apunta la configuración a ``tmp_path``."""
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=entorno.seen_codes_path,
    )
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )

    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_persistencia_path),
    )
    monkeypatch.setattr(
        "source.api.historico.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_historico_path),
    )
    monkeypatch.setattr(
        "source.api.integridad.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_integridad_path),
    )
    monkeypatch.setattr(
        "source.api.listado.config.DEFAULT_CONFIG_PATH",
        Path(entorno.config_listado_path),
    )

    # Evitar que el planificador del buscador arranque un hilo real.
    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)

    # Los hilos de las tareas existentes siguen vivos, pero no ejecutan trabajo
    # real: ni peticiones HTTP ni escrituras en sus bases de datos.
    monkeypatch.setattr(TareaIngesta, "_ejecutar_ciclo", lambda self: None)
    monkeypatch.setattr(
        TareaPurga, "_ejecutar_purga_si_posible", lambda self: None
    )
    monkeypatch.setattr(
        TareaHistorico, "ejecutar_cierre_diario", lambda self: None
    )
    monkeypatch.setattr(
        TareaHistorico,
        "_esperar_hora_configurada",
        lambda self: self._evento_parada.wait(timeout=0.05),
    )

    # La integridad espera su hora y no descarga ningún PDF.
    monkeypatch.setattr(
        TareaIntegridad,
        "_decidir_arranque",
        lambda self, ahora, hay_meta_hoy: AccionArranque.ESPERAR_NORMAL,
    )
    monkeypatch.setattr(TareaIntegridad, "_ejecutar_dia", lambda self: None)


@pytest.fixture
def app_listado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App real arrancada contra el SQLite temporal poblado."""
    entorno = _crear_entorno(tmp_path)
    _parchear(monkeypatch, entorno)
    import source.api.main as main_mod

    main_mod = importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno


# ---------------------------------------------------------------------------
# Utilidades de comprobación
# ---------------------------------------------------------------------------


def _huella(ruta: Path):
    """Tamaño, SHA-256 y ``st_mtime_ns`` de un fichero, o ``None`` si no existe."""
    if not ruta.exists():
        return None
    contenido = ruta.read_bytes()
    return (
        len(contenido),
        hashlib.sha256(contenido).hexdigest(),
        ruta.stat().st_mtime_ns,
    )


def _codigos(datos: dict[str, Any]) -> list[str]:
    """Códigos de las ofertas de una respuesta, en el orden devuelto."""
    return [oferta["codigo"] for oferta in datos["items"]]


def _apuntar_listado(
    main_mod, monkeypatch: pytest.MonkeyPatch, ruta_bd: str
) -> None:
    """Redirige el listado a otra base sin reiniciar la aplicación.

    Sustituye la configuración y el repositorio de ``app_state`` como haría el
    arranque, para los escenarios de base inexistente o sin la tabla
    ``ofertas`` (ALT-001).
    """
    monkeypatch.setitem(
        main_mod.app_state,
        "config_listado",
        ConfigListado(ruta_bd=ruta_bd),
    )
    monkeypatch.setitem(
        main_mod.app_state,
        "repositorio_listado",
        RepositorioListado(AdaptadorLecturaListado(ruta_bd)),
    )


# ---------------------------------------------------------------------------
# Consulta sin filtros (REQ-006, REQ-007, REQ-008)
# ---------------------------------------------------------------------------


class TestConsultaSinFiltros:
    """El listado devuelve las vigentes, ordenadas y con los once campos."""

    def test_devuelve_las_vigentes_con_los_once_campos(self, app_listado):
        """Solo las ``vigente``, con los campos y valores de REQ-008."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get("/listado")

        assert respuesta.status_code == 200
        assert respuesta.status_code not in (401, 403)
        datos = respuesta.json()
        assert _codigos(datos) == _CODIGOS_VIGENTES
        assert datos["total"] == len(_CODIGOS_VIGENTES)

        oferta = datos["items"][0]
        assert set(oferta) == _CAMPOS_OFERTA
        assert oferta["comunidad"] == "Cantabria"
        assert oferta["codigo"] == "061234567890"
        assert oferta["ocupacion"] == "Programador"
        assert oferta["municipio"] == "Santander"
        assert oferta["provincia"] == "Cantabria"
        assert oferta["sector"] == ""
        assert oferta["fecha_inicio_difusion"] == "30/11/2026"
        assert oferta["fecha_fin_difusion"] == "31/12/2026"
        assert oferta["estado"] == "vigente"
        assert oferta["contacto"] == "rrhh@test.com"
        assert oferta["texto_libre"] == "Buscamos desarrollador Python"

        for oferta in datos["items"]:
            assert set(oferta) == _CAMPOS_OFERTA

    def test_metadatos_de_paginacion_y_filtros(self, app_listado):
        """La respuesta trae ``total``, ``pagina``, ``tamano_pagina`` y filtros."""
        client, _main_mod, _entorno = app_listado

        datos = client.get("/listado").json()

        assert datos["total"] == 7
        assert datos["pagina"] == 1
        assert datos["tamano_pagina"] == 20
        assert datos["filtros_aplicados"] == {}

    def test_desempate_por_codigo_ascendente(self, app_listado):
        """Con la misma fecha, el código menor aparece primero (REQ-007)."""
        client, _main_mod, _entorno = app_listado

        codigos = _codigos(client.get("/listado").json())

        assert codigos.index("061234567896") < codigos.index("061234567897")


# ---------------------------------------------------------------------------
# Filtros combinados (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
# ---------------------------------------------------------------------------


class TestFiltrosCombinados:
    """Varios filtros activos a la vez se combinan con AND."""

    def test_municipio_rango_y_texto_aplican_and(self, app_listado):
        """Cada filtro reduce el conjunto: solo queda la oferta que cumple los tres."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get(
            "/listado",
            params={
                "municipio": "santander",
                "fecha_desde": "18/11/2026",
                "fecha_hasta": "26/11/2026",
                "texto": "comercial",
            },
        )

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert _codigos(datos) == ["061234567899"]
        assert datos["total"] == 1
        assert datos["filtros_aplicados"] == {
            "municipio": "santander",
            "fecha_desde": "18/11/2026",
            "fecha_hasta": "26/11/2026",
            "texto": "comercial",
        }

    def test_municipio_sector_y_rango_aplican_and(self, app_listado):
        """El sector inerte deja vacío el conjunto que los tres filtros exigen."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get(
            "/listado",
            params={
                "municipio": "santander",
                "sector": "Informática",
                "fecha_desde": "18/11/2026",
                "fecha_hasta": "26/11/2026",
            },
        )

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 0

    def test_filtro_por_sector_devuelve_lista_vacia_valida(self, app_listado):
        """Sin datos de sector, el filtro responde vacío y válido (ALT-007)."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get("/listado", params={"sector": "Informática"})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 0
        assert datos["filtros_aplicados"] == {"sector": "Informática"}

    def test_municipio_en_minusculas_encuentra_el_almacenado_en_mayusculas(
        self, app_listado
    ):
        """El municipio compara sin distinguir mayúsculas (REQ-004)."""
        client, _main_mod, _entorno = app_listado

        datos = client.get("/listado", params={"municipio": "santander"}).json()

        assert set(_codigos(datos)) == {
            "061234567890",
            "061234567899",
            "061234567891",
        }
        assert datos["total"] == 3


# ---------------------------------------------------------------------------
# Filtro de texto (REQ-002, NFR-003, DEC-002)
# ---------------------------------------------------------------------------


class TestFiltroDeTexto:
    """El texto filtra en memoria y el total es el del conjunto filtrado."""

    def test_tecnico_recupera_la_ocupacion_con_tilde(self, app_listado):
        """``tecnico`` encuentra ``Técnico`` y el total es el filtrado."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get("/listado", params={"texto": "tecnico"})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert _codigos(datos) == ["061234567891"]
        assert datos["total"] == 1

    def test_texto_y_offset_recorta_el_conjunto_filtrado(self, app_listado):
        """La página se recorta tras filtrar, no sobre las filas de SQL."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get(
            "/listado",
            params={"texto": "python", "offset": 1, "tamano_pagina": 1},
        )

        assert respuesta.status_code == 200
        datos = respuesta.json()
        # "python" coincide con 890 (30/11), 896 (18/11) y 898 (12/11); el
        # desplazamiento 1 sobre 7 filas candidatas de SQL daría 899.
        assert _codigos(datos) == ["061234567896"]
        assert datos["total"] == 3
        assert datos["pagina"] == 2

    def test_texto_sin_coincidencias(self, app_listado):
        """Un término que solo estaba en un texto purgado no coincide (ALT-006)."""
        client, _main_mod, _entorno = app_listado

        respuesta = client.get("/listado", params={"texto": "marketing"})

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["items"] == []
        assert datos["total"] == 0


# ---------------------------------------------------------------------------
# Visibilidad por estado (REQ-006, SUP-003)
# ---------------------------------------------------------------------------


class TestVisibilidad:
    """Por defecto solo ``vigente``; con ``incluir_cerradas`` también ``cerrada``."""

    def test_por_defecto_no_aparece_cerrada_ni_sin_ficha(self, app_listado):
        """La cerrada y la sin ficha quedan fuera del listado por defecto."""
        client, _main_mod, _entorno = app_listado

        codigos = _codigos(client.get("/listado").json())

        assert "061234567892" not in codigos
        assert "061234567893" not in codigos

    def test_incluir_cerradas_anade_la_cerrada(self, app_listado):
        """Con ``incluir_cerradas`` aparecen vigentes y cerradas; nunca sin ficha."""
        client, _main_mod, _entorno = app_listado

        datos = client.get(
            "/listado", params={"incluir_cerradas": True}
        ).json()

        codigos = _codigos(datos)
        assert "061234567892" in codigos
        assert "061234567893" not in codigos
        assert datos["total"] == 8
        assert datos["filtros_aplicados"] == {"incluir_cerradas": True}


# ---------------------------------------------------------------------------
# Fecha vacía al final y fuera de los rangos (ALT-004, SUP-004)
# ---------------------------------------------------------------------------


class TestFechaVacia:
    """La oferta sin fecha de inicio va al final y fuera de los rangos."""

    def test_fecha_vacia_queda_al_final(self, app_listado):
        """La última oferta del listado es la de fecha vacía."""
        client, _main_mod, _entorno = app_listado

        datos = client.get("/listado").json()

        assert datos["items"][-1]["codigo"] == "061234567894"
        assert datos["items"][-1]["fecha_inicio_difusion"] == ""

    def test_fecha_vacia_queda_fuera_del_rango(self, app_listado):
        """Un rango que cubre 2026 no incluye la oferta sin fecha."""
        client, _main_mod, _entorno = app_listado

        datos = client.get(
            "/listado",
            params={"fecha_desde": "01/11/2026", "fecha_hasta": "31/12/2026"},
        ).json()

        assert "061234567894" not in _codigos(datos)
        assert datos["total"] == 6


# ---------------------------------------------------------------------------
# Paginación y offset fuera del total (REQ-007, ALT-003)
# ---------------------------------------------------------------------------


class TestPaginacion:
    """Un desplazamiento mayor o igual que el total devuelve página vacía."""

    def test_offset_mayor_o_igual_que_el_total(self, app_listado):
        """La respuesta es 200, con lista vacía y el total real."""
        client, _main_mod, _entorno = app_listado

        for offset in (7, 50):
            respuesta = client.get("/listado", params={"offset": offset})

            assert respuesta.status_code == 200
            datos = respuesta.json()
            assert datos["items"] == []
            assert datos["total"] == 7


# ---------------------------------------------------------------------------
# Campos purgados (REQ-008, ALT-006)
# ---------------------------------------------------------------------------


class TestCamposPurgados:
    """La oferta purgada se devuelve con texto y contacto vacíos."""

    def test_campos_vacios_y_resto_intacto(self, app_listado):
        """El registro mínimo aparece con el resto de campos intactos."""
        client, _main_mod, _entorno = app_listado

        datos = client.get("/listado").json()
        oferta = next(
            item for item in datos["items"] if item["codigo"] == "061234567899"
        )

        assert oferta["texto_libre"] == ""
        assert oferta["contacto"] == ""
        assert oferta["ocupacion"] == "Comercial"
        assert oferta["municipio"] == "Santander"
        assert oferta["fecha_inicio_difusion"] == "25/11/2026"
        assert oferta["estado"] == "vigente"


# ---------------------------------------------------------------------------
# Parámetros inválidos sin llegar a la base (REQ-009, ALT-002)
# ---------------------------------------------------------------------------


class TestParametrosInvalidos:
    """Se rechazan con 400 y la base no se consulta."""

    @pytest.fixture()
    def sin_consulta(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Sustituye la consulta al SQLite por un fallo ruidoso.

        Si la validación no cortase antes de la base, el test vería la
        excepción en lugar de la respuesta ``400``.
        """
        llamadas: list[str] = []

        def _no_consultar(self, *args, **kwargs):
            """Registra el acceso y falla: no debería ejecutarse."""
            llamadas.append(self._ruta_bd)
            raise AssertionError("la base de datos no debe consultarse")

        monkeypatch.setattr(
            AdaptadorLecturaListado, "consultar", _no_consultar
        )
        return llamadas

    def test_fecha_mal_formada(self, app_listado, sin_consulta):
        """``32/13/2026`` se rechaza indicando el formato ``dd/mm/aaaa``."""
        client, _main_mod, entorno = app_listado
        antes = _huella(Path(entorno.ruta_bd))

        respuesta = client.get(
            "/listado", params={"fecha_desde": "32/13/2026"}
        )

        assert respuesta.status_code == 400
        detalle = respuesta.json()["detail"]
        assert "dd/mm/aaaa" in detalle
        assert "fecha_desde" in detalle
        assert sin_consulta == []
        assert _huella(Path(entorno.ruta_bd)) == antes

    def test_rango_invertido(self, app_listado, sin_consulta):
        """Un rango con "desde" posterior a "hasta" se rechaza."""
        client, _main_mod, entorno = app_listado
        antes = _huella(Path(entorno.ruta_bd))

        respuesta = client.get(
            "/listado",
            params={"fecha_desde": "26/11/2026", "fecha_hasta": "18/11/2026"},
        )

        assert respuesta.status_code == 400
        assert "rango" in respuesta.json()["detail"].lower()
        assert sin_consulta == []
        assert _huella(Path(entorno.ruta_bd)) == antes


# ---------------------------------------------------------------------------
# Base inaccesible (ALT-001)
# ---------------------------------------------------------------------------


class TestAccesoADatos:
    """Una base inexistente o sin la tabla ``ofertas`` devuelve 503 controlado."""

    def test_base_inexistente(self, app_listado, monkeypatch):
        """La respuesta indica que no se puede acceder a los datos."""
        client, main_mod, _entorno = app_listado
        ruta = Path(_entorno.tmp_path) / "no_existe.db"
        _apuntar_listado(main_mod, monkeypatch, str(ruta))

        respuesta = client.get("/listado")

        assert respuesta.status_code == 503
        assert "No se puede acceder a los datos" in respuesta.json()["detail"]
        assert not ruta.exists()

    def test_base_sin_la_tabla_ofertas(self, app_listado, monkeypatch):
        """Un SQLite válido sin ``ofertas`` también produce el error controlado."""
        client, main_mod, entorno = app_listado
        ruta = Path(entorno.tmp_path) / "sin_ofertas.db"
        conexion = sqlite3.connect(str(ruta))
        try:
            conexion.execute("CREATE TABLE otra (dato TEXT)")
            conexion.commit()
        finally:
            conexion.close()
        _apuntar_listado(main_mod, monkeypatch, str(ruta))

        respuesta = client.get("/listado")

        assert respuesta.status_code == 503
        assert "No se puede acceder a los datos" in respuesta.json()["detail"]


# ---------------------------------------------------------------------------
# Lectura concurrente con una escritura simulada (ALT-005)
# ---------------------------------------------------------------------------


class TestLecturaConcurrente:
    """La lectura ``mode=ro`` es consistente y no bloquea al escritor."""

    def test_escritura_concurrente_no_bloquea_ni_altera_la_lectura(
        self, app_listado
    ):
        """Durante la transacción abierta se lee lo confirmado y el escritor sigue."""
        client, _main_mod, entorno = app_listado
        ruta = entorno.ruta_bd

        escritor = sqlite3.connect(ruta, isolation_level=None)
        escritor.execute("PRAGMA busy_timeout = 5000;")
        try:
            escritor.execute("BEGIN;")
            _insertar(
                escritor,
                "061234567900",
                ocupacion="Nueva oferta",
                fecha_inicio="01/12/2026",
            )

            # La lectura no ve la escritura no confirmada, pero tampoco se
            # bloquea ni aborta la transacción del escritor.
            inicio = time.perf_counter()
            durante = client.get("/listado")
            transcurrido = time.perf_counter() - inicio

            assert durante.status_code == 200
            datos = durante.json()
            assert datos["total"] == 7
            assert "061234567900" not in _codigos(datos)
            assert transcurrido < 2.0
            assert escritor.in_transaction

            escritor.execute("COMMIT;")
        finally:
            escritor.close()

        despues = client.get("/listado").json()
        assert despues["total"] == 8
        assert _codigos(despues)[0] == "061234567900"


# ---------------------------------------------------------------------------
# Solo lectura y no regresión (REQ-010, SUP-001, SUP-005)
# ---------------------------------------------------------------------------


class TestBaseIntacta:
    """La integración no altera el SQLite de api-persistencia."""

    def test_contenido_y_mtime_intactos_tras_las_consultas(self, app_listado):
        """Tamaño, SHA-256 y ``st_mtime_ns`` no cambian; las filas tampoco."""
        client, _main_mod, entorno = app_listado
        ruta = Path(entorno.ruta_bd)
        antes = _huella(ruta)

        consultas = [
            {"texto": "python"},
            {"municipio": "santander", "fecha_desde": "18/11/2026"},
            {"sector": "Informática"},
            {"incluir_cerradas": True},
            {"texto": "tecnico", "offset": 1, "tamano_pagina": 1},
        ]
        for params in consultas:
            assert client.get("/listado", params=params).status_code == 200
        assert client.get("/listado/filtros").status_code == 200

        assert _huella(ruta) == antes

        ruta_uri = str(ruta).replace("\\", "/")
        conexion = sqlite3.connect(f"file:{ruta_uri}?mode=ro", uri=True)
        try:
            filas = conexion.execute("SELECT COUNT(*) FROM ofertas").fetchone()
        finally:
            conexion.close()
        assert filas[0] == len(_OFERTAS)

    def test_bd_real_conserva_contenido_y_mtime(self, app_listado):
        """La base real ``data/job_emcan.db`` no se toca (REQ-010, SUP-005)."""
        client, _main_mod, _entorno = app_listado

        assert client.get("/listado").status_code == 200

        # La huella real ya se tomó al importar el módulo de la prueba.
        assert _huella(RUTA_BD_REAL) == _HUELLA_BD_REAL


# ---------------------------------------------------------------------------
# No regresión de los sprints 02–05 (SUP-001)
# ---------------------------------------------------------------------------


class TestNoRegresion:
    """Los endpoints existentes siguen respondiendo igual tras integrar el listado."""

    def test_endpoints_de_los_sprints_02_05_responden(self, app_listado):
        """Buscador, persistencia, histórico e integridad responden 200."""
        client, _main_mod, _entorno = app_listado

        assert client.get("/health").status_code == 200
        assert client.get("/buscador/status").status_code == 200
        assert (
            client.get("/persistencia/ofertas/vigentes").status_code == 200
        )
        assert (
            client.get(
                "/historico/resumen",
                params={"desde": "2026-11-01", "hasta": "2026-11-02"},
            ).status_code
            == 200
        )
        assert client.get("/integridad/ultimo").status_code == 200
        assert client.get("/integridad/pdfs").status_code == 200
        # El listado sigue operativo en el mismo proceso.
        assert client.get("/listado").status_code == 200
        assert client.get("/listado/filtros").status_code == 200


#: Huella de ``data/job_emcan.db`` tomada al importar la prueba, antes de que
#: arranque ninguna aplicación: sirve de referencia para la no regresión.
_HUELLA_BD_REAL = _huella(RUTA_BD_REAL)
