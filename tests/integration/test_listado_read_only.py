"""Verificación de solo lectura, rendimiento y aislamiento del listado (TASK-014).

Monta la aplicación real de ``source/api/main.py`` con ``TestClient`` y un
entorno temporal (configuraciones de buscador, persistencia, histórico,
integridad y listado en ``tmp_path``) sobre un SQLite que replica la
``CREATE TABLE ofertas`` de ``source/api/persistencia/migrations.py`` y se
puebla con 500 ofertas vigentes.

Comprueba las garantías transversales de la feature:

- (a) rendimiento: con 500 ofertas vigentes, la respuesta completa de
  ``GET /listado`` sin filtros y con filtro textual llega en menos de 2 segundos
  (NFR-002, DEC-002), medido con ``time.perf_counter``;
- (b) solo lectura: una tanda de consultas no altera el número de filas de
  ``ofertas``, ni la marca de modificación ni el contenido (hash) del fichero
  SQLite (REQ-010, SUP-005);
- (c) concurrencia: una escritura concurrente simulada no se bloquea ni aborta
  por la lectura ``mode=ro`` con ``busy_timeout`` (ALT-005);
- (d) aislamiento del código: ``source/api/listado/`` no contiene operaciones de
  escritura sobre ``ofertas`` (DEC-001);
- (e) aislamiento de las features previas: los ficheros de
  ``source/api/buscador/``, ``source/api/persistencia/``,
  ``source/api/historico/``, ``source/api/integridad/`` y
  ``source/api/parser.py`` conservan su huella antes y después de las consultas
  (SUP-001).

Los hilos reales de las tareas de fondo no ejecutan trabajo: el planificador del
buscador no arranca y la ingesta, la purga, el histórico y la integridad tienen
sus métodos de ejecución sustituidos por dobles, de modo que no hay red real ni
escrituras en ``data/pdfs`` ni en ``data/job_emcan.db``.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import re
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
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga

#: Número de ofertas vigentes de la base de prueba (NFR-002).
NUMERO_OFERTAS = 500

#: Límite de tiempo de respuesta del listado, en segundos (NFR-002).
LIMITE_SEGUNDOS = 2.0

#: Código de la oferta que inserta el escritor concurrente (ALT-005).
CODIGO_CONCURRENTE = "069999999999"

#: Paquete cuyo código se inspecciona para descartar escrituras (DEC-001).
_PAQUETE_LISTADO = Path("source/api/listado")

#: Paquetes y ficheros de las features previas que no se deben modificar
#: (SUP-001).
_DIRECTORIOS_PROTEGIDOS = (
    "source/api/buscador",
    "source/api/persistencia",
    "source/api/historico",
    "source/api/integridad",
)
_FICHEROS_PROTEGIDOS = ("source/api/parser.py",)

#: Operaciones SQL de escritura que no deben aparecer en el paquete (DEC-001).
_PATRON_ESCRITURA = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE"
    r"|DELETE\s+FROM|DROP\s+(?:TABLE|INDEX))\b",
    re.IGNORECASE,
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
# Datos de prueba: 500 ofertas vigentes
# ---------------------------------------------------------------------------


def _ofertas_vigentes() -> list[dict[str, Any]]:
    """Genera las 500 ofertas vigentes de la base de prueba.

    Todas comparten un ``texto_libre`` con "Python" (el filtro textual por
    "python" recorre las 500 filas candidatas) y una de cada cinco tiene la
    ocupación "Técnico de sistemas" (el filtro por "tecnico" devuelve 100).
    Las fechas se reparten de enero a diciembre de 2026 y el código es un texto
    único de 12 dígitos.
    """
    ofertas: list[dict[str, Any]] = []
    for indice in range(NUMERO_OFERTAS):
        dia = indice % 28 + 1
        mes = indice % 12 + 1
        ofertas.append(
            {
                "codigo": f"06{indice:010d}",
                "ocupacion": (
                    "Técnico de sistemas"
                    if indice % 5 == 0
                    else "Programador"
                ),
                "municipio": (
                    "Santander" if indice % 2 == 0 else "Torrelavega"
                ),
                "fecha_inicio": f"{dia:02d}/{mes:02d}/2026",
                "texto_libre": "Buscamos desarrollador Python",
            }
        )
    return ofertas


_OFERTAS = _ofertas_vigentes()

#: Códigos de las ofertas que coinciden con el filtro "tecnico" (REQ-002).
_CODIGOS_TECNICO = [
    oferta["codigo"]
    for oferta in _OFERTAS
    if oferta["ocupacion"].startswith("Técnico")
]


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
def app_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App real arrancada contra el SQLite temporal con 500 vigentes."""
    entorno = _crear_entorno(tmp_path)
    _parchear(monkeypatch, entorno)
    import source.api.main as main_mod

    main_mod = importlib.reload(main_mod)
    with TestClient(main_mod.app) as client:
        # Calentamiento: la primera petición compila los modelos de respuesta de
        # FastAPI y deja la app lista antes de medir tiempos.
        assert client.get("/listado").status_code == 200
        yield client, main_mod, entorno


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _huella(ruta: str | Path):
    """Tamaño, SHA-256 y ``st_mtime_ns`` de un fichero, o ``None`` si no existe."""
    fichero = Path(ruta)
    if not fichero.exists():
        return None
    contenido = fichero.read_bytes()
    return (
        len(contenido),
        hashlib.sha256(contenido).hexdigest(),
        fichero.stat().st_mtime_ns,
    )


def _contar_filas(ruta_bd: str) -> int:
    """Cuenta las filas de ``ofertas`` con una conexión de solo lectura."""
    ruta_uri = str(ruta_bd).replace("\\", "/")
    uri = f"file:{ruta_uri}?mode=ro"
    conexion = sqlite3.connect(uri, uri=True)
    try:
        fila = conexion.execute("SELECT COUNT(*) FROM ofertas").fetchone()
    finally:
        conexion.close()
    return int(fila[0])


def _ronda_de_consultas(client: TestClient) -> None:
    """Ejecuta una tanda de consultas representativas del listado."""
    consultas: list[dict[str, Any]] = [
        {},
        {"texto": "tecnico"},
        {"texto": "python", "offset": 480, "tamano_pagina": 50},
        {
            "municipio": "santander",
            "fecha_desde": "01/01/2026",
            "fecha_hasta": "31/12/2026",
        },
        {"sector": "Informática"},
        {"incluir_cerradas": True},
        {"offset": NUMERO_OFERTAS + 10},
    ]
    for params in consultas:
        respuesta = client.get("/listado", params=params)
        assert respuesta.status_code == 200


def _medir(client: TestClient, params: dict[str, Any]) -> tuple[float, dict]:
    """Mide con ``perf_counter`` una respuesta completa de ``GET /listado``."""
    inicio = time.perf_counter()
    respuesta = client.get("/listado", params=params)
    transcurrido = time.perf_counter() - inicio
    assert respuesta.status_code == 200
    return transcurrido, respuesta.json()


def _huella_codigo() -> dict[str, tuple[int, str]]:
    """Tamaño y SHA-256 de los ``.py`` de los paquetes protegidos (SUP-001)."""
    huellas: dict[str, tuple[int, str]] = {}
    for directorio in _DIRECTORIOS_PROTEGIDOS:
        for ruta in Path(directorio).rglob("*.py"):
            if "__pycache__" in ruta.parts:
                continue
            huellas[str(ruta)] = (
                ruta.stat().st_size,
                hashlib.sha256(ruta.read_bytes()).hexdigest(),
            )
    for fichero in _FICHEROS_PROTEGIDOS:
        ruta = Path(fichero)
        if ruta.exists():
            huellas[str(ruta)] = (
                ruta.stat().st_size,
                hashlib.sha256(ruta.read_bytes()).hexdigest(),
            )
    return huellas


def _cadenas_del_paquete() -> list[tuple[str, str]]:
    """Devuelve (ruta, literal) de cada cadena de los módulos del paquete."""
    cadenas: list[tuple[str, str]] = []
    for ruta in sorted(_PAQUETE_LISTADO.rglob("*.py")):
        if "__pycache__" in ruta.parts:
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
                cadenas.append((str(ruta), nodo.value))
    return cadenas


# ---------------------------------------------------------------------------
# Rendimiento con 500 ofertas vigentes (NFR-002, DEC-002)
# ---------------------------------------------------------------------------


class TestRendimiento:
    """Con 500 vigentes, la respuesta completa llega en menos de 2 segundos."""

    def test_sin_filtros(self, app_500):
        """El listado sin filtros responde en menos de 2 s (NFR-002)."""
        client, _main_mod, _entorno = app_500

        transcurrido, datos = _medir(client, {})

        assert datos["total"] == NUMERO_OFERTAS
        assert len(datos["items"]) == 20
        assert transcurrido < LIMITE_SEGUNDOS

    def test_con_filtro_textual(self, app_500):
        """Con filtro textual responde en menos de 2 s y filtra (DEC-002)."""
        client, _main_mod, _entorno = app_500

        transcurrido, datos = _medir(client, {"texto": "tecnico"})

        assert datos["total"] == len(_CODIGOS_TECNICO)
        assert {
            oferta["codigo"] for oferta in datos["items"]
        } <= set(_CODIGOS_TECNICO)
        assert transcurrido < LIMITE_SEGUNDOS

    def test_filtrado_sobre_500_candidatas(self, app_500):
        """Filtrar en memoria las 500 candidatas no supera el límite (DEC-002)."""
        client, _main_mod, _entorno = app_500

        transcurrido, datos = _medir(client, {"texto": "python"})

        # "python" está en el texto de las 500 ofertas: el filtrado en memoria
        # recorre todas las filas candidatas de SQL.
        assert datos["total"] == NUMERO_OFERTAS
        assert len(datos["items"]) == 20
        assert transcurrido < LIMITE_SEGUNDOS


# ---------------------------------------------------------------------------
# Solo lectura: filas, marca de modificación y contenido (REQ-010, SUP-005)
# ---------------------------------------------------------------------------


class TestSoloLectura:
    """La tanda de consultas no altera el SQLite de la base de prueba."""

    def test_numero_de_filas_identico(self, app_500):
        """El número de filas de ``ofertas`` es el mismo antes y después."""
        client, _main_mod, entorno = app_500

        antes = _contar_filas(entorno.ruta_bd)
        _ronda_de_consultas(client)
        despues = _contar_filas(entorno.ruta_bd)

        assert antes == NUMERO_OFERTAS
        assert despues == antes

    def test_marca_de_modificacion_intacta(self, app_500):
        """La marca de modificación del fichero no cambia (REQ-010, SUP-005)."""
        client, _main_mod, entorno = app_500
        ruta = Path(entorno.ruta_bd)

        antes = ruta.stat().st_mtime_ns
        _ronda_de_consultas(client)

        assert ruta.stat().st_mtime_ns == antes

    def test_contenido_sin_diferencias(self, app_500):
        """El hash del contenido del fichero es idéntico antes y después."""
        client, _main_mod, entorno = app_500

        antes = _huella(entorno.ruta_bd)
        _ronda_de_consultas(client)

        assert antes is not None
        assert antes[0] > 0
        assert _huella(entorno.ruta_bd) == antes


# ---------------------------------------------------------------------------
# Lectura concurrente con una escritura simulada (ALT-005)
# ---------------------------------------------------------------------------


class TestLecturaConcurrente:
    """La lectura ``mode=ro`` no bloquea ni aborta al escritor."""

    def test_escritura_concurrente_no_se_bloquea_ni_aborta(self, app_500):
        """Durante la transacción abierta se lee lo confirmado y el escritor sigue."""
        client, _main_mod, entorno = app_500

        escritor = sqlite3.connect(entorno.ruta_bd, isolation_level=None)
        escritor.execute("PRAGMA busy_timeout = 5000;")
        try:
            escritor.execute("BEGIN;")
            _insertar(
                escritor,
                CODIGO_CONCURRENTE,
                ocupacion="Nueva oferta",
                fecha_inicio="31/12/2026",
            )

            # La lectura no ve la escritura no confirmada, pero tampoco se
            # bloquea ni aborta la transacción del escritor.
            inicio = time.perf_counter()
            durante = client.get("/listado")
            transcurrido = time.perf_counter() - inicio

            assert durante.status_code == 200
            datos = durante.json()
            assert datos["total"] == NUMERO_OFERTAS
            assert CODIGO_CONCURRENTE not in {
                oferta["codigo"] for oferta in datos["items"]
            }
            assert transcurrido < LIMITE_SEGUNDOS
            assert escritor.in_transaction

            escritor.execute("COMMIT;")
        finally:
            escritor.close()

        despues = client.get("/listado").json()
        assert despues["total"] == NUMERO_OFERTAS + 1
        assert despues["items"][0]["codigo"] == CODIGO_CONCURRENTE
        assert _contar_filas(entorno.ruta_bd) == NUMERO_OFERTAS + 1


# ---------------------------------------------------------------------------
# Inspección estática del paquete (DEC-001)
# ---------------------------------------------------------------------------


class TestInspeccionEstatica:
    """El código del listado no contiene escrituras sobre ``ofertas``."""

    def test_el_paquete_tiene_modulos(self):
        """Hay módulos que inspeccionar: la comprobación no es vacía."""
        assert list(_PAQUETE_LISTADO.glob("*.py"))

    def test_sin_operaciones_de_escritura(self):
        """Ningún literal SQL del paquete escribe sobre ``ofertas`` (DEC-001)."""
        escrituras = [
            (ruta, cadena)
            for ruta, cadena in _cadenas_del_paquete()
            if _PATRON_ESCRITURA.search(cadena)
        ]

        assert escrituras == [], escrituras


# ---------------------------------------------------------------------------
# Aislamiento de las features previas (SUP-001)
# ---------------------------------------------------------------------------


class TestAislamiento:
    """Los paquetes de los sprints 01–05 no cambian con las consultas."""

    def test_paquetes_previos_conservan_su_huella(self, app_500):
        """Tamaño y SHA-256 de los ficheros protegidos son los mismos."""
        client, _main_mod, _entorno = app_500

        antes = _huella_codigo()
        assert antes

        _ronda_de_consultas(client)

        assert _huella_codigo() == antes
