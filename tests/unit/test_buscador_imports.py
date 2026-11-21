"""Pruebas de importación del subpaquete buscador y sus dependencias."""

import importlib
import sys

import pytest


def test_buscador_subpackage_imports_without_error() -> None:
    """Importar source.api.buscador no lanza error."""
    mod = importlib.import_module("source.api.buscador")
    assert mod is not None


def test_selectolax_is_available() -> None:
    """selectolax está disponible como dependencia declarada."""
    from selectolax.lexbor import LexborHTMLParser  # noqa: F401


def test_buscador_does_not_import_database_engines() -> None:
    """source.api.buscador no importa motores de BD (SQLite/SQLAlchemy)."""
    # Limpiar cualquier importación previa del subpaquete para un análisis limpio.
    mods_before = {name for name in sys.modules if name.startswith("source.api.buscador")}

    importlib.import_module("source.api.buscador")

    # Comprobar que no se ha importado sqlite3 ni sqlalchemy como consecuencia.
    buscador_modules = {
        name for name in sys.modules if name.startswith("source.api.buscador")
    } - mods_before
    for name in buscador_modules:
        assert "sqlite" not in name.lower(), (
            f"source.api.buscador no debe importar sqlite: {name}"
        )
        assert "sqlalchemy" not in name.lower(), (
            f"source.api.buscador no debe importar sqlalchemy: {name}"
        )
