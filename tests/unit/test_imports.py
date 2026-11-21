"""Pruebas de disponibilidad del paquete y sus dependencias declaradas."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    ["source.api", "fastapi", "httpx", "pdfplumber", "yaml"],
)
def test_package_and_dependencies_are_importable(module_name: str) -> None:
    """El paquete de la API y sus dependencias se pueden importar."""
    assert importlib.import_module(module_name) is not None
