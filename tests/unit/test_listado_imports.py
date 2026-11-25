"""Pruebas de importación del subpaquete del listado y sus dependencias.

Comprueban que ``source.api.listado`` se importa sin error, que las
dependencias que exige el diseño están disponibles (PyYAML), que el paquete no
introduce motores de base de datos servidor, extensiones vectoriales de SQLite
ni FTS5, y que no escribe ni modifica los ficheros de los módulos ajenos.
"""

import hashlib
import importlib
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PAQUETE_LISTADO = _REPO_ROOT / "source" / "api" / "listado"

_MODULOS_LISTADO = [
    "source.api.listado",
    "source.api.listado.config",
    "source.api.listado.read_adapter",
    "source.api.listado.date_parser",
    "source.api.listado.text_normalizer",
    "source.api.listado.filter_builder",
    "source.api.listado.repository",
    "source.api.listado.routes",
]

# Motores de BD servidor, extensiones vectoriales y motores de texto prohibidos
# por DEC-002: el listado lee el SQLite de api-persistencia con la stdlib.
_PREFIJOS_IMPORT_PROHIBIDOS = [
    "sqlalchemy",
    "psycopg2",
    "psycopg",
    "asyncpg",
    "mysql.connector",
    "mysql",
    "pymysql",
    "sqlite_vec",
    "sqlite_vss",
    "sqlite-vec",
    "sqlite-vss",
]

_TOKENS_FUENTE_PROHIBIDOS = [
    "sqlalchemy",
    "psycopg",
    "pymysql",
    "mysql",
    "postgres",
    "sqlite_vec",
    "sqlite_vss",
    "sqlite-vec",
    "sqlite-vss",
    "fts5",
    "fts4",
    "using fts",
]

_MODULOS_PROTEGIDOS = [
    "source.api.buscador",
    "source.api.persistencia",
    "source.api.historico",
    "source.api.integridad",
    "source.api.parser",
    "source.api.downloader",
    "source.api.assembler",
]

_RUTAS_PROTEGIDAS = [
    _REPO_ROOT / "source" / "api" / "buscador",
    _REPO_ROOT / "source" / "api" / "persistencia",
    _REPO_ROOT / "source" / "api" / "historico",
    _REPO_ROOT / "source" / "api" / "integridad",
    _REPO_ROOT / "source" / "api" / "parser.py",
    _REPO_ROOT / "source" / "api" / "downloader.py",
    _REPO_ROOT / "source" / "api" / "assembler.py",
]


def _importar_listado() -> None:
    """Importa el subpaquete y todos sus módulos hosting."""
    for nombre in _MODULOS_LISTADO:
        importlib.import_module(nombre)


def _ficheros_protegidos() -> list[Path]:
    """Lista los ficheros de los módulos ajenos que el listado no debe tocar."""
    ficheros: list[Path] = []
    for ruta in _RUTAS_PROTEGIDAS:
        if ruta.is_dir():
            ficheros.extend(
                ordenado
                for ordenado in sorted(ruta.rglob("*"))
                if ordenado.is_file() and "__pycache__" not in ordenado.parts
            )
        elif ruta.is_file():
            ficheros.append(ruta)
    return ficheros


def _huella(fichero: Path) -> tuple[str, int]:
    """Hash del contenido y marca de modificación de un fichero."""
    return (
        hashlib.sha256(fichero.read_bytes()).hexdigest(),
        fichero.stat().st_mtime_ns,
    )


def _fuentes_del_paquete() -> list[Path]:
    """Ficheros .py del subpaquete del listado."""
    ficheros = sorted(_PAQUETE_LISTADO.glob("*.py"))
    assert ficheros, "Debe haber módulos .py en source/api/listado/"
    return ficheros


def test_listado_subpackage_imports_without_error() -> None:
    """Importar source.api.listado no lanza error."""
    modulo = importlib.import_module("source.api.listado")
    assert modulo is not None


def test_listado_hosting_modules_import_without_error() -> None:
    """Los módulos hosting de los componentes del diseño importan sin error."""
    for nombre in _MODULOS_LISTADO:
        assert importlib.import_module(nombre) is not None


@pytest.mark.parametrize("module_name", ["yaml"])
def test_required_dependencies_are_available(module_name: str) -> None:
    """Las dependencias que exige el diseño se pueden importar."""
    assert importlib.import_module(module_name) is not None


def test_listado_does_not_import_database_engines() -> None:
    """El listado no importa motores de BD servidor ni extensiones vectoriales."""
    modulos_antes = set(sys.modules.keys())

    _importar_listado()

    for nombre in set(sys.modules.keys()) - modulos_antes:
        minusculas = nombre.lower()
        for prohibido in _PREFIJOS_IMPORT_PROHIBIDOS:
            assert not (
                minusculas == prohibido
                or minusculas.startswith(prohibido + ".")
                or minusculas.startswith(prohibido + "-")
                or minusculas.startswith(prohibido + "_")
            ), f"source.api.listado no debe importar '{prohibido}': {nombre}"


def test_listado_sources_do_not_reference_forbidden_engines() -> None:
    """El código del listado no referencia motores servidor, vectores ni FTS5."""
    for fuente in _fuentes_del_paquete():
        contenido = fuente.read_text(encoding="utf-8").lower()
        for token in _TOKENS_FUENTE_PROHIBIDOS:
            assert token not in contenido, (
                f"{fuente.name} no debe referenciar '{token}' conforme a DEC-002"
            )


def test_listado_does_not_import_protected_modules() -> None:
    """Los módulos del listado no importan los módulos protegidos del API."""
    modulos_antes = set(sys.modules.keys())

    _importar_listado()

    nuevos = set(sys.modules.keys()) - modulos_antes

    for nombre in nuevos:
        for protegido in _MODULOS_PROTEGIDOS:
            assert not (nombre == protegido or nombre.startswith(protegido + ".")), (
                f"source.api.listado no debe importar '{protegido}': {nombre}"
            )


def test_listado_does_not_reference_protected_paths() -> None:
    """El código del listado no referencia las rutas de los módulos ajenos."""
    rutas = []
    for ruta in _RUTAS_PROTEGIDAS:
        rutas.append(ruta.as_posix())
        rutas.append(str(ruta))

    for fuente in _fuentes_del_paquete():
        contenido = fuente.read_text(encoding="utf-8")
        for ruta in rutas:
            assert ruta not in contenido, (
                f"{fuente.name} no debe referenciar la ruta protegida '{ruta}'"
            )


def test_listado_import_does_not_modify_protected_files() -> None:
    """Importar el listado no escribe ni modifica los ficheros de los módulos ajenos."""
    ficheros = _ficheros_protegidos()
    assert ficheros, "Deben existir ficheros en los módulos protegidos"

    huellas_antes = {fichero: _huella(fichero) for fichero in ficheros}

    _importar_listado()

    huellas_despues = {fichero: _huella(fichero) for fichero in ficheros}
    assert huellas_despues == huellas_antes, (
        "Importar source.api.listado no debe escribir ni modificar ficheros de "
        "los módulos ajenos"
    )
