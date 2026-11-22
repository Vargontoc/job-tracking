"""Pruebas de la conexion SQLite del historico de altas y cierres."""

import sqlite3
import threading
from pathlib import Path

import pytest

from source.api.historico.connection import (
    BUSY_TIMEOUT_MS,
    abrir_conexion,
    lock_modulo,
    transaccion,
)


def test_abrir_conexion_crea_directorio_y_fichero(tmp_path: Path) -> None:
    """Con una ruta inexistente se crea el directorio y el fichero .db."""
    ruta = tmp_path / "subdir" / "historico.db"
    assert not ruta.exists()

    conexion = abrir_conexion(ruta)
    try:
        assert ruta.exists()
        assert ruta.parent.is_dir()
        # Solo un fichero .db en el directorio.
        ficheros_db = list(ruta.parent.glob("*.db"))
        assert len(ficheros_db) == 1
        assert ficheros_db[0].name == "historico.db"
    finally:
        conexion.close()


def test_journal_mode_es_wal(tmp_path: Path) -> None:
    """PRAGMA journal_mode devuelve 'wal' tras abrir la conexion."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        cursor = conexion.execute("PRAGMA journal_mode;")
        modo = cursor.fetchone()[0]
        assert modo.lower() == "wal"
    finally:
        conexion.close()


def test_busy_timeout_mayor_que_cero(tmp_path: Path) -> None:
    """PRAGMA busy_timeout devuelve un valor mayor que cero."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        cursor = conexion.execute("PRAGMA busy_timeout;")
        timeout = cursor.fetchone()[0]
        assert timeout > 0
        assert timeout == BUSY_TIMEOUT_MS
    finally:
        conexion.close()


def test_row_factory_permite_acceso_por_nombre(tmp_path: Path) -> None:
    """row_factory = sqlite3.Row permite acceder a las columnas por nombre."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        conexion.execute("CREATE TABLE prueba (id INTEGER, nombre TEXT);")
        conexion.execute("INSERT INTO prueba VALUES (1, 'test');")
        conexion.commit()
        fila = conexion.execute("SELECT * FROM prueba WHERE id = 1;").fetchone()
        assert fila["id"] == 1
        assert fila["nombre"] == "test"
    finally:
        conexion.close()


def test_transaccion_confirmada_persiste(tmp_path: Path) -> None:
    """Una transaccion confirmada deja los cambios persistidos."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        conexion.execute("CREATE TABLE prueba (valor INTEGER);")
        conexion.commit()

        with transaccion(conexion) as cx:
            cx.execute("INSERT INTO prueba VALUES (42);")

        fila = conexion.execute("SELECT valor FROM prueba;").fetchone()
        assert fila[0] == 42
    finally:
        conexion.close()


def test_transaccion_deshecha_no_persiste(tmp_path: Path) -> None:
    """Una transaccion deshecha no deja los cambios."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        conexion.execute("CREATE TABLE prueba (valor INTEGER);")
        conexion.commit()

        with pytest.raises(ValueError):
            with transaccion(conexion) as cx:
                cx.execute("INSERT INTO prueba VALUES (42);")
                raise ValueError("error simulado")

        fila = conexion.execute("SELECT COUNT(*) FROM prueba;").fetchone()
        assert fila[0] == 0
    finally:
        conexion.close()


def test_no_abre_conexion_sobre_ruta_persistencia(tmp_path: Path) -> None:
    """El componente no abre ninguna conexion sobre la ruta de persistencia."""
    ruta_historico = tmp_path / "historico.db"
    ruta_persistencia = tmp_path / "persistencia.db"

    # Crear un fichero de persistencia para verificar que no se modifica.
    ruta_persistencia.write_bytes(b"")
    marca_inicial = ruta_persistencia.stat().st_mtime_ns

    conexion = abrir_conexion(ruta_historico)
    try:
        # Verificar que la conexion principal apunta al historico, no a persistencia.
        filas = conexion.execute("PRAGMA database_list;").fetchall()
        fila_main = next(f for f in filas if f["name"] == "main")
        assert Path(fila_main["file"]).resolve() == ruta_historico.resolve()

        # Escribir algo en el historico y verificar que persistencia no cambia.
        conexion.execute("CREATE TABLE prueba (valor INTEGER);")
        conexion.commit()
    finally:
        conexion.close()

    marca_final = ruta_persistencia.stat().st_mtime_ns
    assert marca_final == marca_inicial


def test_check_same_thread_false(tmp_path: Path) -> None:
    """La conexion permite uso desde distintos hilos."""
    ruta = tmp_path / "historico.db"
    conexion = abrir_conexion(ruta)
    try:
        # Verificar que no lanza excepcion al acceder desde otro hilo.
        errores = []

        def usar_conexion():
            try:
                conexion.execute("SELECT 1;").fetchone()
            except Exception as e:
                errores.append(e)

        hilo = threading.Thread(target=usar_conexion)
        hilo.start()
        hilo.join()
        assert not errores
    finally:
        conexion.close()


def test_lock_modulo_devuelve_lock() -> None:
    """lock_modulo() devuelve un threading.Lock utilizable."""
    lk = lock_modulo()
    assert isinstance(lk, type(threading.Lock()))
