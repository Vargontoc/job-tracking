"""Pruebas de importación del subpaquete histórico y sus dependencias."""

import importlib
import os
import sys
from pathlib import Path

import pytest


def test_historico_subpackage_imports_without_error() -> None:
    """Importar source.api.historico no lanza error."""
    mod = importlib.import_module("source.api.historico")
    assert mod is not None


@pytest.mark.parametrize("module_name", ["httpx", "pdfplumber", "zoneinfo"])
def test_required_dependencies_are_available(module_name: str) -> None:
    """Las dependencias requeridas por el histórico se pueden importar."""
    assert importlib.import_module(module_name) is not None


# Motores de BD servidor y extensiones vectoriales de SQLite prohibidos.
_FORBIDDEN_IMPORT_PREFIXES = [
    "sqlalchemy",
    "psycopg2",
    "psycopg",
    "mysql.connector",
    "mysql",
    "pymysql",
    "sqlite_vec",
    "sqlite_vss",
    "sqlite-vec",
    "sqlite-vss",
]


def test_historico_does_not_import_database_engines() -> None:
    """El histórico no importa motores de BD servidor ni extensiones vectoriales."""
    mods_before = {
        name for name in sys.modules if name.startswith("source.api.historico")
    }

    importlib.import_module("source.api.historico")

    newly_imported = {
        name for name in sys.modules if name.startswith("source.api.historico")
    } - mods_before

    for name in newly_imported:
        lower = name.lower()
        for forbidden in _FORBIDDEN_IMPORT_PREFIXES:
            assert forbidden not in lower, (
                f"source.api.historico no debe importar '{forbidden}': {name}"
            )


def test_historico_does_not_write_to_protected_paths() -> None:
    """Los módulos del histórico no referencian escritura en rutas protegidas."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    historico_dir = repo_root / "source" / "api" / "historico"

    protected_paths = [
        os.path.normpath(repo_root / "source" / "api" / "buscador"),
        os.path.normpath(repo_root / "source" / "api" / "persistencia"),
        os.path.normpath(repo_root / "source" / "api" / "parser.py"),
        os.path.normpath(repo_root / "source" / "api" / "downloader.py"),
        os.path.normpath(repo_root / "source" / "api" / "assembler.py"),
    ]

    source_files = sorted(historico_dir.glob("*.py"))
    assert source_files, "Debe haber módulos .py en source/api/historico/"

    for source_file in source_files:
        content = source_file.read_text(encoding="utf-8")
        for protected in protected_paths:
            # Normalizamos la ruta protegida para compararla con los literales del fuente.
            # Aceptamos tanto la forma con separadores POSIX como la del sistema.
            posix_path = Path(protected).as_posix()
            assert protected not in content and posix_path not in content, (
                f"{source_file.name} no debe referenciar la ruta protegida "
                f"'{protected}'"
            )


def test_historico_does_not_import_protected_modules() -> None:
    """Los módulos del histórico no importan los módulos protegidos del API."""
    # Forzamos una recarga limpia importando cada módulo del subpaquete.
    historico_modules = [
        "source.api.historico.config",
        "source.api.historico.connection",
        "source.api.historico.migrations",
        "source.api.historico.presencia_repository",
        "source.api.historico.abstenciones_repository",
        "source.api.historico.ejecucion_repository",
        "source.api.historico.buscador_client",
        "source.api.historico.persistencia_client",
        "source.api.historico.read_adapter",
        "source.api.historico.pdf_adapter",
        "source.api.historico.cierre_fecha",
        "source.api.historico.desaparicion",
        "source.api.historico.recuento_guardian",
        "source.api.historico.task",
        "source.api.historico.routes",
    ]

    mods_before = set(sys.modules.keys())

    for mod_name in historico_modules:
        importlib.import_module(mod_name)

    newly_imported = set(sys.modules.keys()) - mods_before

    forbidden_modules = {
        "source.api.buscador",
        "source.api.persistencia",
        "source.api.parser",
        "source.api.downloader",
        "source.api.assembler",
    }

    for name in newly_imported:
        for forbidden in forbidden_modules:
            assert not (name == forbidden or name.startswith(forbidden + ".")), (
                f"El histórico no debe importar '{forbidden}': {name}"
            )
