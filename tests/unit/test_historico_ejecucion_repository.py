"""Pruebas del repositorio de ejecución diaria (TASK-007)."""

import pytest

from source.api.historico.connection import abrir_conexion
from source.api.historico.ejecucion_repository import RepositorioEjecucion
from source.api.historico.migrations import migrar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_ejecucion.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión a una BD temporal migrada y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repositorio(conexion):
    """Devuelve un RepositorioEjecucion sobre la BD temporal."""
    return RepositorioEjecucion(conexion)


# ---------------------------------------------------------------------------
# Pruebas: estado inicial
# ---------------------------------------------------------------------------

class TestEstadoInicial:
    """Sin ejecuciones registradas, las consultas devuelven valores vacíos."""

    def test_se_ejecuto_hoy_devuelve_false(self, repositorio):
        assert repositorio.se_ejecuto_hoy("2026-11-22") is False

    def test_obtener_ultima_ejecucion_devuelve_none(self, repositorio):
        assert repositorio.obtener_ultima_ejecucion() is None


# ---------------------------------------------------------------------------
# Pruebas: registrar y consultar (caso feliz)
# ---------------------------------------------------------------------------

class TestRegistrarYConsultar:
    """Tras registrar una ejecución, se_ejecuto_hoy devuelve True."""

    def test_registrar_ejecucion_hace_visible_la_fecha(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        assert repositorio.se_ejecuto_hoy("2026-11-22") is True

    def test_obtener_ultima_ejecucion_devuelve_la_fecha(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        assert repositorio.obtener_ultima_ejecucion() == "2026-11-22"

    def test_fecha_distinta_devuelve_false(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        assert repositorio.se_ejecuto_hoy("2026-11-23") is False

    def test_fecha_anterior_devuelve_false(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        assert repositorio.se_ejecuto_hoy("2026-11-21") is False


# ---------------------------------------------------------------------------
# Pruebas: idempotencia / prevención de duplicados (ALT-006)
# ---------------------------------------------------------------------------

class TestIdempotencia:
    """Registrar dos veces el mismo día no genera dos registros."""

    def test_registrar_dos_veces_misma_fecha_no_duplica(self, conexion, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        repositorio.registrar_ejecucion("2026-11-22")

        filas = conexion.execute(
            "SELECT COUNT(*) FROM ejecucion_diaria WHERE fecha = ?",
            ("2026-11-22",),
        ).fetchone()
        assert filas[0] == 1

    def test_registrar_dos_veces_no_lanza_excepcion(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        # La segunda llamada no debe lanzar excepción.
        repositorio.registrar_ejecucion("2026-11-22")
        assert repositorio.se_ejecuto_hoy("2026-11-22") is True


# ---------------------------------------------------------------------------
# Pruebas: última ejecución con varios registros
# ---------------------------------------------------------------------------

class TestUltimaEjecucion:
    """obtener_ultima_ejecucion devuelve la fecha más reciente."""

    def test_ultima_con_multiples_registros(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-20")
        repositorio.registrar_ejecucion("2026-11-22")
        repositorio.registrar_ejecucion("2026-11-21")
        # MAX(fecha) sobre texto YYYY-MM-DD ordena cronológicamente.
        assert repositorio.obtener_ultima_ejecucion() == "2026-11-22"

    def test_ultima_con_un_solo_registro(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-15")
        assert repositorio.obtener_ultima_ejecucion() == "2026-11-15"


# ---------------------------------------------------------------------------
# Pruebas: persistencia tras "reiniciar" (DEC-001)
# ---------------------------------------------------------------------------

class TestPersistencia:
    """Tras cerrar y reabrir la conexión, el registro persiste."""

    def test_registro_sobrevive_al_reinicio(self, ruta_db):
        # Primera conexión: registrar.
        conn1 = abrir_conexion(ruta_db)
        migrar(conn1)
        repo1 = RepositorioEjecucion(conn1)
        repo1.registrar_ejecucion("2026-11-22")
        conn1.close()

        # Segunda conexión: verificar que sigue ahí.
        conn2 = abrir_conexion(ruta_db)
        migrar(conn2)
        try:
            repo2 = RepositorioEjecucion(conn2)
            assert repo2.se_ejecuto_hoy("2026-11-22") is True
            assert repo2.obtener_ultima_ejecucion() == "2026-11-22"
        finally:
            conn2.close()


# ---------------------------------------------------------------------------
# Pruebas: zona horaria del llamador (NFR-001)
# ---------------------------------------------------------------------------

class TestZonaHorariaDelLlamador:
    """El repositorio almacena el texto tal cual; la zona la aplica el llamador."""

    def test_almacena_la_fecha_como_texto(self, repositorio):
        fecha = "2026-11-22"
        repositorio.registrar_ejecucion(fecha)
        assert repositorio.se_ejecuto_hoy(fecha) is True

    def test_dos_fechas_distintas_son_independientes(self, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        repositorio.registrar_ejecucion("2026-11-23")
        assert repositorio.se_ejecuto_hoy("2026-11-22") is True
        assert repositorio.se_ejecuto_hoy("2026-11-23") is True
        assert repositorio.obtener_ultima_ejecucion() == "2026-11-23"


# ---------------------------------------------------------------------------
# Pruebas: no escribe en la BD de ofertas (SUP-003)
# ---------------------------------------------------------------------------

class TestNoEscribeEnOfertas:
    """Las operaciones del repositorio no tocan la tabla de ofertas."""

    def test_no_existe_tabla_ofertas(self, conexion, repositorio):
        repositorio.registrar_ejecucion("2026-11-22")
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas
