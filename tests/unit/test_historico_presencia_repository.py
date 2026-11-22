"""Pruebas del repositorio de presencia en listado y serie de recuentos (TASK-005)."""

import pytest

from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar
from source.api.historico.presencia_repository import RepositorioPresencia


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_presencia.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión a una BD temporal, migra y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo(conexion):
    """Devuelve un RepositorioPresencia sobre la BD migrada."""
    return RepositorioPresencia(conexion)


# ---------------------------------------------------------------------------
# Pruebas: registrar_presencia y registrar_ausencia
# ---------------------------------------------------------------------------

class TestRegistrarPresenciaAusencia:
    """Registrar presencia y ausencia del mismo código en fechas distintas."""

    def test_registrar_presencia(self, repo):
        """Registrar presencia deja una marca presente=1."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        historial = repo.consultar_historial("000000000001", "cantabria")
        assert len(historial) == 1
        assert historial[0] == ("2026-11-01", True)

    def test_registrar_ausencia(self, repo):
        """Registrar ausencia deja una marca presente=0."""
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        historial = repo.consultar_historial("000000000001", "cantabria")
        assert len(historial) == 1
        assert historial[0] == ("2026-11-01", False)

    def test_presencia_y_ausencia_en_fechas_distintas(self, repo):
        """Presencia y ausencia en fechas distintas producen dos marcas (REQ-005)."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-02")
        historial = repo.consultar_historial("000000000001", "cantabria")
        assert len(historial) == 2
        # Orden descendente por fecha
        assert historial[0] == ("2026-11-02", False)
        assert historial[1] == ("2026-11-01", True)

    def test_doble_registro_misma_fecha_no_duplica(self, repo):
        """Registrar dos veces la misma fecha no duplica y prevalece la última."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        historial = repo.consultar_historial("000000000001", "cantabria")
        assert len(historial) == 1
        # La última marca (ausencia) prevalece
        assert historial[0] == ("2026-11-01", False)

    def test_doble_presencia_misma_fecha_prevalece_presencia(self, repo):
        """Registrar ausencia y luego presencia en la misma fecha → prevalece presencia."""
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        historial = repo.consultar_historial("000000000001", "cantabria")
        assert len(historial) == 1
        assert historial[0] == ("2026-11-01", True)


# ---------------------------------------------------------------------------
# Pruebas: consultar_historial
# ---------------------------------------------------------------------------

class TestConsultarHistorial:
    """Consultar historial de un código."""

    def test_historial_orden_descendente(self, repo):
        """Las fechas se devuelven de más reciente a más antigua."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-03")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-02")
        historial = repo.consultar_historial("000000000001", "cantabria")
        fechas = [h[0] for h in historial]
        assert fechas == ["2026-11-03", "2026-11-02", "2026-11-01"]

    def test_historial_con_limite(self, repo):
        """El parámetro ``limite`` recorta el número de resultados."""
        for dia in range(1, 6):
            repo.registrar_presencia(
                "cantabria", "000000000001", f"2026-11-{dia:02d}"
            )
        historial = repo.consultar_historial(
            "000000000001", "cantabria", limite=3
        )
        assert len(historial) == 3

    def test_historial_sin_comunidad_consulta_todas(self, repo):
        """Sin ``comunidad``, se consultan todas las comunidades del código."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_ausencia("madrid", "000000000001", "2026-11-02")
        historial = repo.consultar_historial("000000000001")
        assert len(historial) == 2

    def test_historial_vacio(self, repo):
        """Un código sin registros devuelve lista vacía."""
        historial = repo.consultar_historial("000000000099", "cantabria")
        assert historial == []


# ---------------------------------------------------------------------------
# Pruebas: ausencias_consecutivas
# ---------------------------------------------------------------------------

class TestAusenciasConsecutivas:
    """Verificación de ausencias consecutivas."""

    def test_n_ausencias_consecutivas_true(self, repo):
        """Con n ausencias consecutivas devuelve True."""
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-02")
        assert repo.ausencias_consecutivas("000000000001", "cantabria", 2) is True

    def test_menos_de_n_registros_false(self, repo):
        """Con menos de n registros devuelve False."""
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        assert repo.ausencias_consecutivas("000000000001", "cantabria", 2) is False

    def test_mezcla_presencia_ausencia_false(self, repo):
        """Con una presencia intercalada no son n ausencias consecutivas."""
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-02")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-03")
        # Las dos más recientes son: ausencia (03), presencia (02) → no son 2 ausencias
        assert repo.ausencias_consecutivas("000000000001", "cantabria", 2) is False

    def test_tres_ausencias_consecutivas(self, repo):
        """Con 3 ausencias consecutivas se requiere n=3 (NFR-003)."""
        for dia in range(1, 4):
            repo.registrar_ausencia(
                "cantabria", "000000000001", f"2026-11-{dia:02d}"
            )
        assert repo.ausencias_consecutivas("000000000001", "cantabria", 3) is True
        # Pero con n=4 no
        assert repo.ausencias_consecutivas("000000000001", "cantabria", 4) is False

    def test_sin_registros_false(self, repo):
        """Un código sin registros no tiene ausencias consecutivas."""
        assert repo.ausencias_consecutivas("000000000099", "cantabria", 1) is False


# ---------------------------------------------------------------------------
# Pruebas: serie de recuentos
# ---------------------------------------------------------------------------

class TestSerieRecuentos:
    """Registro y consulta de la serie de recuentos."""

    def test_registrar_y_obtener_ultimo(self, repo):
        """Registrar un recuento y obtenerlo como último."""
        repo.registrar_recuento(93, "2026-11-01T10:00:00+00:00")
        ultimo = repo.obtener_ultimo_recuento()
        assert ultimo == (93, "2026-11-01T10:00:00+00:00")

    def test_ultimo_tras_varios_registros(self, repo):
        """El último recuento es el más reciente tras registrar varios."""
        repo.registrar_recuento(93, "2026-11-01T10:00:00+00:00")
        repo.registrar_recuento(92, "2026-11-02T10:00:00+00:00")
        repo.registrar_recuento(91, "2026-11-03T10:00:00+00:00")
        ultimo = repo.obtener_ultimo_recuento()
        assert ultimo == (91, "2026-11-03T10:00:00+00:00")

    def test_serie_vacia_devuelve_none(self, repo):
        """Sobre serie vacía, obtener_ultimo_recuento devuelve None (ALT-010)."""
        assert repo.obtener_ultimo_recuento() is None

    def test_recuentos_anterior_y_actual(self, repo):
        """Se puede obtener el recuento anterior consultando antes de registrar."""
        repo.registrar_recuento(93, "2026-11-01T10:00:00+00:00")
        anterior = repo.obtener_ultimo_recuento()
        assert anterior == (93, "2026-11-01T10:00:00+00:00")
        repo.registrar_recuento(92, "2026-11-02T10:00:00+00:00")
        actual = repo.obtener_ultimo_recuento()
        assert actual == (92, "2026-11-02T10:00:00+00:00")
        # El anterior sigue siendo el primero
        assert anterior == (93, "2026-11-01T10:00:00+00:00")


# ---------------------------------------------------------------------------
# Pruebas: no escribe en la base de datos de ofertas (SUP-003)
# ---------------------------------------------------------------------------

class TestNoEscribeEnOfertas:
    """El repositorio no escribe en la base de datos de ofertas."""

    def test_no_existe_tabla_ofertas(self, conexion):
        """La BD del histórico no contiene la tabla 'ofertas'."""
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas

    def test_operaciones_no_crean_tabla_ofertas(self, repo, conexion):
        """Tras usar el repositorio, no aparece la tabla 'ofertas'."""
        repo.registrar_presencia("cantabria", "000000000001", "2026-11-01")
        repo.registrar_ausencia("cantabria", "000000000001", "2026-11-02")
        repo.registrar_recuento(93, "2026-11-01T10:00:00+00:00")
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas
