"""Pruebas de importación del subpaquete de integridad y sus dependencias."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Módulos hosting creados en TASK-001; uno por componente del diseño.
MODULOS_HOSTING = [
    "source.api.integridad.config",
    "source.api.integridad.pdf_store",
    "source.api.integridad.purger",
    "source.api.integridad.downloader_adapter",
    "source.api.integridad.parser_adapter",
    "source.api.integridad.buscador_client",
    "source.api.integridad.comparador",
    "source.api.integridad.avisos",
    "source.api.integridad.ejecuciones",
    "source.api.integridad.task",
    "source.api.integridad.routes",
]

# Motores de BD servidor, módulo sqlite y extensiones vectoriales de SQLite.
_PREFIJOS_PROHIBIDOS = [
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "mysql",
    "pymysql",
    "sqlite3",
    "sqlite_vec",
    "sqlite_vss",
]

# Rutas que el subpaquete no debe escribir ni modificar (SUP-005, SUP-003).
RUTAS_PROTEGIDAS = [
    "source/api/buscador",
    "source/api/persistencia",
    "source/api/historico",
    "source/api/parser.py",
    "source/api/downloader.py",
    "source/api/assembler.py",
    "data/job_emcan.db",
]

_PROBE = """
import importlib
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))

PROTEGIDAS = {rutas!r}
MODULOS = {modulos!r}
SUFIJOS_SQLITE = (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm")


def instantanea():
    resultado = {{}}
    for relativa in PROTEGIDAS:
        ruta = repo / relativa
        if ruta.is_dir():
            for fichero in sorted(ruta.rglob("*")):
                if fichero.is_file():
                    resultado[fichero.relative_to(repo).as_posix()] = (
                        fichero.stat().st_mtime_ns
                    )
        elif ruta.is_file():
            resultado[relativa] = ruta.stat().st_mtime_ns
    return resultado


def ficheros_sqlite():
    carpeta = repo / "data"
    if not carpeta.is_dir():
        return []
    return sorted(
        fichero.relative_to(repo).as_posix()
        for fichero in carpeta.rglob("*")
        if fichero.is_file() and fichero.name.lower().endswith(SUFIJOS_SQLITE)
    )


antes_ficheros = instantanea()
antes_sqlite = ficheros_sqlite()
antes_modulos = set(sys.modules)

for nombre in ["source.api.integridad"] + MODULOS:
    importlib.import_module(nombre)

despues_ficheros = instantanea()
despues_sqlite = ficheros_sqlite()

print(json.dumps({{
    "modificados": sorted(
        ruta
        for ruta, mtime in antes_ficheros.items()
        if despues_ficheros.get(ruta) != mtime
    ),
    "sqlite_nuevos": sorted(set(despues_sqlite) - set(antes_sqlite)),
    "sqlite3_importado": "sqlite3" in sys.modules,
    "modulos_nuevos": sorted(set(sys.modules) - antes_modulos),
}}))
""".format(rutas=RUTAS_PROTEGIDAS, modulos=MODULOS_HOSTING)


@pytest.fixture(scope="module")
def sondas() -> dict:
    """Importa el paquete en un intérprete limpio y devuelve lo observado."""
    proceso = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proceso.returncode == 0, proceso.stderr
    return json.loads(proceso.stdout)


def test_integridad_subpackage_imports_without_error() -> None:
    """Importar source.api.integridad no lanza error."""
    assert importlib.import_module("source.api.integridad") is not None


@pytest.mark.parametrize("nombre_modulo", MODULOS_HOSTING)
def test_integridad_hosting_modules_import_without_error(nombre_modulo: str) -> None:
    """Cada módulo hosting del subpaquete se importa sin error."""
    assert importlib.import_module(nombre_modulo) is not None


@pytest.mark.parametrize("nombre_modulo", ["httpx", "pdfplumber", "yaml", "zoneinfo"])
def test_required_dependencies_are_available(nombre_modulo: str) -> None:
    """Las dependencias que exige el diseño están disponibles (sin declarar nuevas)."""
    assert importlib.import_module(nombre_modulo) is not None


def test_zoneinfo_resolves_iana_timezone() -> None:
    """Una zona IANA como Europe/Madrid resuelve con el soporte de zona horaria."""
    assert str(ZoneInfo("Europe/Madrid")) == "Europe/Madrid"


def test_integridad_does_not_import_database_engines(sondas: dict) -> None:
    """El paquete no importa motores de BD servidor ni extensiones vectoriales."""
    for modulo in sondas["modulos_nuevos"]:
        minusculas = modulo.lower()
        for prefijo in _PREFIJOS_PROHIBIDOS:
            assert not (minusculas == prefijo or minusculas.startswith(prefijo + ".")), (
                f"source.api.integridad no debe importar '{prefijo}': {modulo}"
            )


def test_integridad_does_not_modify_protected_paths(sondas: dict) -> None:
    """Importar el paquete no escribe ni modifica ficheros de rutas protegidas."""
    assert sondas["modificados"] == [], (
        f"Ficheros modificados por el paquete: {sondas['modificados']}"
    )


def test_integridad_does_not_create_or_open_sqlite(sondas: dict) -> None:
    """El paquete no crea ni abre ningún fichero propio de base de datos."""
    assert sondas["sqlite3_importado"] is False, (
        "El paquete no debe importar sqlite3"
    )
    assert sondas["sqlite_nuevos"] == [], (
        f"Ficheros de base de datos creados: {sondas['sqlite_nuevos']}"
    )
