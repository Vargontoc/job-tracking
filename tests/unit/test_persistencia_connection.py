"""Pruebas de la conexión SQLite con WAL, pragmas y contexto de transacción."""

import sqlite3
import threading
import tempfile
from pathlib import Path

import pytest

from source.api.persistencia.connection import (
    abrir_conexion,
    transaccion,
    lock_modulo,
    BUSY_TIMEOUT_MS,
)


@pytest.fixture
def ruta_temporal(tmp_path):
    """Devuelve una ruta inexistente dentro de un directorio temporal."""
    return tmp_path / "subdir" / "test.db"


@pytest.fixture
def conexion(ruta_temporal):
    """Abre una conexión y la cierra al terminar."""
    conn = abrir_conexion(ruta_temporal)
    yield conn, ruta_temporal
    conn.close()


def _contar_ficheros_db(directorio: Path) -> int:
    """Cuenta los ficheros .db en un directorio (no recursivo)."""
    return len(list(directorio.glob("*.db")))


class TestAbrirConexion:
    """Pruebas de abrir_conexion."""

    def test_crea_directorio_y_fichero(self, ruta_temporal):
        """Con una ruta temporal inexistente, crea el directorio y el fichero .db."""
        assert not ruta_temporal.exists()
        conn = abrir_conexion(ruta_temporal)
        try:
            assert ruta_temporal.exists()
            assert ruta_temporal.parent.exists()
        finally:
            conn.close()

    def test_directorio_contiene_unico_fichero_db(self, ruta_temporal):
        """El directorio contiene un único fichero .db tras la inicialización."""
        conn = abrir_conexion(ruta_temporal)
        try:
            assert _contar_ficheros_db(ruta_temporal.parent) == 1
        finally:
            conn.close()

    def test_journal_mode_wal(self, conexion):
        """PRAGMA journal_mode devuelve 'wal' tras la inicialización."""
        conn, _ = conexion
        resultado = conn.execute("PRAGMA journal_mode;").fetchone()
        assert resultado[0] == "wal"

    def test_busy_timeout_mayor_que_cero(self, conexion):
        """PRAGMA busy_timeout devuelve un valor mayor que cero."""
        conn, _ = conexion
        resultado = conn.execute("PRAGMA busy_timeout;").fetchone()
        assert int(resultado[0]) > 0
        assert int(resultado[0]) == BUSY_TIMEOUT_MS


class TestTransaccion:
    """Pruebas del contexto de transacción."""

    def _crear_tabla(self, conn):
        conn.execute(
            "CREATE TABLE prueba (id INTEGER PRIMARY KEY, valor TEXT);"
        )

    def test_transaccion_confirmada_persiste(self, conexion):
        """Una transacción confirmada deja los cambios persistidos."""
        conn, _ = conexion
        self._crear_tabla(conn)
        with transaccion(conn):
            conn.execute("INSERT INTO prueba (id, valor) VALUES (1, 'hola');")
        resultado = conn.execute("SELECT valor FROM prueba WHERE id = 1;").fetchone()
        assert resultado[0] == "hola"

    def test_transaccion_deshecha_no_persiste(self, conexion):
        """Una transacción deshecha no deja los cambios persistidos."""
        conn, _ = conexion
        self._crear_tabla(conn)
        with pytest.raises(ValueError):
            with transaccion(conn):
                conn.execute("INSERT INTO prueba (id, valor) VALUES (1, 'adios');")
                raise ValueError("error simulado")
        resultado = conn.execute("SELECT COUNT(*) FROM prueba;").fetchone()
        assert resultado[0] == 0

    def test_transaccion_confirmada_sin_cambios(self, conexion):
        """Una transacción sin cambios se confirma sin error."""
        conn, _ = conexion
        with transaccion(conn):
            pass
        # No lanza excepción.

    def test_transaccion_deshecha_con_error_no_controlado(self, conexion):
        """Una excepción no controlada deshace la transacción y se propaga."""
        conn, _ = conexion
        self._crear_tabla(conn)
        with pytest.raises(RuntimeError):
            with transaccion(conn):
                conn.execute("INSERT INTO prueba (id, valor) VALUES (2, 'x');")
                raise RuntimeError("fallo")
        resultado = conn.execute("SELECT COUNT(*) FROM prueba;").fetchone()
        assert resultado[0] == 0


class TestConcurrencia:
    """Pruebas de concurrencia con WAL y busy_timeout."""

    def test_dos_escrituras_concurrentes(self, ruta_temporal):
        """Dos escrituras concurrentes terminan sin SQLITE_BUSY no controlado."""
        conn = abrir_conexion(ruta_temporal)
        conn.execute("CREATE TABLE contador (id INTEGER PRIMARY KEY, n INTEGER);")
        conn.execute("INSERT INTO contador (id, n) VALUES (1, 0);")
        conn.close()

        errores = []

        def incrementar():
            try:
                c = abrir_conexion(ruta_temporal)
                try:
                    for _ in range(5):
                        with transaccion(c):
                            fila = c.execute(
                                "SELECT n FROM contador WHERE id = 1;"
                            ).fetchone()
                            c.execute(
                                "UPDATE contador SET n = ? WHERE id = 1;",
                                (fila[0] + 1,),
                            )
                finally:
                    c.close()
            except Exception as exc:
                errores.append(exc)

        hilo1 = threading.Thread(target=incrementar)
        hilo2 = threading.Thread(target=incrementar)
        hilo1.start()
        hilo2.start()
        hilo1.join(timeout=10)
        hilo2.join(timeout=10)

        assert not errores, f"Errores en escrituras concurrentes: {errores}"

        c = abrir_conexion(ruta_temporal)
        try:
            fila = c.execute("SELECT n FROM contador WHERE id = 1;").fetchone()
            # El resultado debe ser 10 (5 + 5) si todo se serializó correctamente.
            assert fila[0] == 10
        finally:
            c.close()


class TestSinRed:
    """Pruebas que verifican que no se abre conexión de red ni se requiere servidor."""

    def test_no_requiere_servidor(self, ruta_temporal):
        """La conexión no requiere ningún servidor de base de datos."""
        conn = abrir_conexion(ruta_temporal)
        try:
            # Una simple operación de lectura/escritura funciona sin red.
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY);")
            conn.execute("INSERT INTO t (id) VALUES (1);")
            resultado = conn.execute("SELECT id FROM t;").fetchone()
            assert resultado[0] == 1
        finally:
            conn.close()

    def test_conexion_es_sqlite3(self, ruta_temporal):
        """La conexión devuelta es una conexión sqlite3 nativa."""
        conn = abrir_conexion(ruta_temporal)
        try:
            assert isinstance(conn, sqlite3.Connection)
        finally:
            conn.close()


class TestLockModulo:
    """Pruebas del lock del módulo."""

    def test_lock_es_threading_lock(self):
        """El lock del módulo es un threading.Lock."""
        assert isinstance(lock_modulo(), type(threading.Lock()))
