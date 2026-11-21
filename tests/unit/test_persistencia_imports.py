"""Pruebas de importación del subpaquete persistencia y sus dependencias."""

import importlib
import sys

import pytest


def test_persistencia_subpackage_imports_without_error() -> None:
    """Importar source.api.persistencia no lanza error."""
    mod = importlib.import_module("source.api.persistencia")
    assert mod is not None


def test_httpx_is_available() -> None:
    """httpx está disponible como dependencia declarada."""
    import httpx  # noqa: F401


def test_numpy_is_available() -> None:
    """numpy está disponible como dependencia declarada."""
    import numpy  # noqa: F401


def test_persistencia_does_not_import_server_database_engines() -> None:
    """source.api.persistencia no importa motores de BD servidor ni extensiones vectoriales."""
    # Limpiar cualquier importación previa del subpaquete para un análisis limpio.
    mods_before = {
        name for name in sys.modules if name.startswith("source.api.persistencia")
    }

    importlib.import_module("source.api.persistencia")

    # Comprobar que no se ha importado sqlalchemy, psycopg, mysql ni extensiones vectoriales.
    persistencia_modules = {
        name for name in sys.modules if name.startswith("source.api.persistencia")
    } - mods_before
    forbidden = ("sqlalchemy", "psycopg", "postgres", "mysql", "sqlite-vss", "sqlite-vec")
    for name in persistencia_modules:
        lower = name.lower()
        for token in forbidden:
            assert token not in lower, (
                f"source.api.persistencia no debe importar {token}: {name}"
            )


def test_persistencia_does_not_reference_vector_extensions_in_source() -> None:
    """El __init__.py del subpaquete no referencia extensiones vectoriales de SQLite."""
    import inspect

    import source.api.persistencia as pkg

    source_text = inspect.getsource(pkg)
    lower = source_text.lower()
    for token in ("sqlite-vss", "sqlite-vec", "sqlite_vec", "sqlite_vss"):
        assert token not in lower, (
            f"source.api.persistencia no debe referenciar {token}"
        )
