"""Pruebas unitarias del módulo state (fichero local de códigos vistos)."""

import json
from pathlib import Path

import pytest

from source.api.buscador.state import (
    ErrorEstado,
    guardar_codigos_vistos,
    leer_codigos_vistos,
)


def test_fichero_con_3_codigos_devuelve_3(tmp_path):
    """Un fichero con 3 códigos devuelve un conjunto de 3 elementos."""
    ruta = tmp_path / "seen_codes.json"
    codigos = ["062026003633", "062026003484", "062026003123"]
    ruta.write_text(json.dumps(codigos), encoding="utf-8")

    resultado = leer_codigos_vistos(ruta)

    assert resultado == set(codigos)
    assert len(resultado) == 3


def test_fichero_inexistente_crea_fichero_vacio(tmp_path):
    """Si el fichero no existe, lo crea vacío y devuelve conjunto vacío."""
    ruta = tmp_path / "subdir" / "seen_codes.json"

    resultado = leer_codigos_vistos(ruta)

    assert resultado == set()
    assert ruta.exists()
    assert ruta.read_text(encoding="utf-8") == "[]"


def test_guardar_codigo_nuevo_conserva_anteriores(tmp_path):
    """Guardar un código nuevo conserva los anteriores (recarga devuelve 4)."""
    ruta = tmp_path / "seen_codes.json"
    iniciales = {"062026003633", "062026003484", "062026003123"}
    ruta.write_text(json.dumps(sorted(iniciales)), encoding="utf-8")

    guardar_codigos_vistos(ruta, {"062026003999"})
    resultado = leer_codigos_vistos(ruta)

    assert resultado == iniciales | {"062026003999"}
    assert len(resultado) == 4


def test_guardar_codigo_ya_presente_no_duplica(tmp_path):
    """Guardar un código ya presente no lo duplica en el fichero."""
    ruta = tmp_path / "seen_codes.json"
    codigos = ["062026003633", "062026003484"]
    ruta.write_text(json.dumps(codigos), encoding="utf-8")

    guardar_codigos_vistos(ruta, {"062026003633"})
    resultado = leer_codigos_vistos(ruta)

    assert resultado == set(codigos)
    assert len(resultado) == 2

    # Verificar que el fichero no tiene duplicados
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(datos) == 2
    assert len(set(datos)) == 2


def test_json_invalido_lanza_error_controlado(tmp_path):
    """Un fichero con JSON inválido lanza ErrorEstado identificando el fichero."""
    ruta = tmp_path / "seen_codes.json"
    ruta.write_text("{ invalid json }", encoding="utf-8")

    with pytest.raises(ErrorEstado) as exc_info:
        leer_codigos_vistos(ruta)

    assert str(ruta) in str(exc_info.value)
    assert "JSON inválido" in str(exc_info.value)


def test_json_no_es_lista_lanza_error_controlado(tmp_path):
    """Un JSON que no es una lista lanza ErrorEstado."""
    ruta = tmp_path / "seen_codes.json"
    ruta.write_text('{"codigos": []}', encoding="utf-8")

    with pytest.raises(ErrorEstado) as exc_info:
        leer_codigos_vistos(ruta)

    assert str(ruta) in str(exc_info.value)
    assert "no contiene una lista" in str(exc_info.value)


def test_no_abre_ninguna_base_de_datos(tmp_path):
    """El módulo no importa ni usa SQLite, SQLAlchemy ni cualquier BD."""
    import sys
    import importlib

    # Limpiar imports previos si los hubiera
    mod_name = "source.api.buscador.state"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    # Importar el módulo
    importlib.import_module(mod_name)

    # Verificar que no se importaron motores de BD
    bd_modules = {"sqlite3", "sqlalchemy", "psycopg2", "pymysql"}
    importados = set(sys.modules.keys())
    interseccion = importados & bd_modules

    assert len(interseccion) == 0, (
        f"El módulo state no debe importar bases de datos, pero importó: {interseccion}"
    )


def test_guardar_en_fichero_nuevo_lo_crea(tmp_path):
    """Guardar en un fichero que no existe lo crea con los códigos."""
    ruta = tmp_path / "nuevo" / "seen_codes.json"

    guardar_codigos_vistos(ruta, {"062026003633", "062026003484"})

    assert ruta.exists()
    resultado = leer_codigos_vistos(ruta)
    assert resultado == {"062026003633", "062026003484"}


def test_codigos_se_guardan_ordenados(tmp_path):
    """Los códigos se guardan ordenados alfabéticamente."""
    ruta = tmp_path / "seen_codes.json"

    guardar_codigos_vistos(ruta, {"062026003999", "062026003123", "062026003633"})

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos == sorted(datos)


def test_union_de_conjuntos_sin_duplicados(tmp_path):
    """La escritura une los códigos nuevos a los anteriores sin duplicados."""
    ruta = tmp_path / "seen_codes.json"
    ruta.write_text(json.dumps(["A", "B", "C"]), encoding="utf-8")

    guardar_codigos_vistos(ruta, {"B", "C", "D", "E"})
    resultado = leer_codigos_vistos(ruta)

    assert resultado == {"A", "B", "C", "D", "E"}
    assert len(resultado) == 5
