"""Pruebas del repositorio de abstenciones de cierre (TASK-006)."""

import json

import pytest

from source.api.historico.abstenciones_repository import (
    Abstencion,
    RepositorioAbstenciones,
)
from source.api.historico.connection import abrir_conexion
from source.api.historico.migrations import migrar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_abstenciones.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión migrada a una BD temporal y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo(conexion):
    """Devuelve un RepositorioAbstenciones listo para usar."""
    return RepositorioAbstenciones(conexion)


# ---------------------------------------------------------------------------
# Pruebas: registrar con todos los datos (REQ-011, REQ-008, REQ-007)
# ---------------------------------------------------------------------------

class TestRegistrarCompleta:
    """Una abstención registrada conserva motivo, marca de tiempo, recuentos,
    umbral aplicado y códigos afectados."""

    def test_registrar_y_consultar_devuelve_datos_intactos(self, repo):
        """REQ-011: registrar con recuentos y códigos y consultarla devuelve
        los cinco datos intactos."""
        codigo = "062026099999"
        id_ = repo.registrar(
            motivo="caida_anomala",
            timestamp="2026-11-22T02:00:00+00:00",
            recuento_anterior=93,
            recuento_actual=50,
            umbral_aplicado="0.5",
            codigos_afectados=[codigo],
        )
        assert isinstance(id_, int)
        assert id_ > 0

        ultimas = repo.consultar_ultimas(n=1)
        assert len(ultimas) == 1
        abst = ultimas[0]
        assert abst.id == id_
        assert abst.motivo == "caida_anomala"
        assert abst.timestamp == "2026-11-22T02:00:00+00:00"
        assert abst.recuento_anterior == 93
        assert abst.recuento_actual == 50
        assert abst.umbral_aplicado == "0.5"
        assert abst.codigos_afectados == [codigo]

    def test_codigos_se_serializan_como_json_en_bd(self, conexion, repo):
        """codigos_afectados se guarda como JSON string en la columna."""
        repo.registrar(
            motivo="test",
            timestamp="2026-11-22T02:00:00+00:00",
            codigos_afectados=["ABC123", "DEF456"],
        )
        fila = conexion.execute(
            "SELECT codigos_afectados FROM abstenciones_cierre"
        ).fetchone()
        assert json.loads(fila["codigos_afectados"]) == ["ABC123", "DEF456"]

    def test_registrar_pasada_fallida_sin_recuentos(self, repo):
        """REQ-006: registrar una abstención por pasada fallida conserva motivo
        y timestamp; los recuentos quedan a None."""
        repo.registrar(
            motivo="pasada_fallida",
            timestamp="2026-11-22T03:00:00+00:00",
        )
        ultimas = repo.consultar_ultimas(n=1)
        assert len(ultimas) == 1
        abst = ultimas[0]
        assert abst.motivo == "pasada_fallida"
        assert abst.recuento_anterior is None
        assert abst.recuento_actual is None
        assert abst.umbral_aplicado is None
        assert abst.codigos_afectados is None

    def test_registrar_oferta_excluida(self, repo):
        """REQ-007 / REQ-011: registrar una abstención por oferta excluida
        devuelve el código de la oferta y el motivo."""
        codigo = "062026000001"
        repo.registrar(
            motivo="oferta_excluida",
            timestamp="2026-11-22T04:00:00+00:00",
            codigos_afectados=[codigo],
        )
        filtradas = repo.consultar_por_motivo("oferta_excluida")
        assert len(filtradas) == 1
        assert filtradas[0].codigos_afectados == [codigo]
        assert filtradas[0].motivo == "oferta_excluida"

    def test_registrar_sin_codigos_ni_recuentos_no_falla(self, repo):
        """Una abstención sin recuentos ni códigos afectados se registra con
        esos campos a None y no falla."""
        repo.registrar(
            motivo="sin_datos",
            timestamp="2026-11-22T05:00:00+00:00",
        )
        ultimas = repo.consultar_ultimas(n=1)
        assert len(ultimas) == 1
        assert ultimas[0].codigos_afectados is None
        assert ultimas[0].recuento_anterior is None
        assert ultimas[0].recuento_actual is None


# ---------------------------------------------------------------------------
# Pruebas: consultar_ultimas ordena por timestamp desc
# ---------------------------------------------------------------------------

class TestConsultarUltimas:
    """La consulta devuelve las abstenciones de más reciente a más antigua."""

    def test_orden_descendente(self, repo):
        ts_1 = "2026-11-22T01:00:00+00:00"
        ts_2 = "2026-11-22T02:00:00+00:00"
        ts_3 = "2026-11-22T03:00:00+00:00"
        repo.registrar(motivo="a", timestamp=ts_1)
        repo.registrar(motivo="b", timestamp=ts_2)
        repo.registrar(motivo="c", timestamp=ts_3)

        ultimas = repo.consultar_ultimas(n=10)
        assert [a.motivo for a in ultimas] == ["c", "b", "a"]

    def test_limite_n(self, repo):
        for i in range(5):
            repo.registrar(motivo=f"m{i}", timestamp=f"2026-11-{20+i:02d}T08:00:00")

        ultimas = repo.consultar_ultimas(n=3)
        assert len(ultimas) == 3
        # Las 3 más recientes: m4, m3, m2
        assert [a.motivo for a in ultimas] == ["m4", "m3", "m2"]

    def test_tabla_vacia(self, repo):
        assert repo.consultar_ultimas(n=10) == []


# ---------------------------------------------------------------------------
# Pruebas: consultar_por_motivo filtra correctamente
# ---------------------------------------------------------------------------

class TestConsultarPorMotivo:
    """La consulta filtrada por motivo devuelve solo las abstenciones de ese
    motivo."""

    def test_filtra_por_motivo(self, repo):
        repo.registrar(motivo="caida_anomala", timestamp="2026-11-22T01:00:00")
        repo.registrar(motivo="pasada_fallida", timestamp="2026-11-22T02:00:00")
        repo.registrar(motivo="caida_anomala", timestamp="2026-11-22T03:00:00")

        caidas = repo.consultar_por_motivo("caida_anomala")
        assert len(caidas) == 2
        assert all(a.motivo == "caida_anomala" for a in caidas)

    def test_motivo_inexistente_devuelve_vacio(self, repo):
        repo.registrar(motivo="caida_anomala", timestamp="2026-11-22T01:00:00")
        assert repo.consultar_por_motivo("inexistente") == []

    def test_limite_por_motivo(self, repo):
        for i in range(5):
            repo.registrar(
                motivo="caida_anomala",
                timestamp=f"2026-11-{20+i:02d}T08:00:00",
            )
        resultado = repo.consultar_por_motivo("caida_anomala", limite=2)
        assert len(resultado) == 2


# ---------------------------------------------------------------------------
# Pruebas: consultar_por_rango de fechas
# ---------------------------------------------------------------------------

class TestConsultarPorRango:
    """La consulta por rango de fechas devuelve solo las abstenciones dentro
    del rango [inicio, fin] inclusive."""

    def test_rango_inclusivo(self, repo):
        repo.registrar(motivo="a", timestamp="2026-11-21T00:00:00")
        repo.registrar(motivo="b", timestamp="2026-11-22T12:00:00")
        repo.registrar(motivo="c", timestamp="2026-11-23T00:00:00")
        repo.registrar(motivo="d", timestamp="2026-11-24T00:00:00")

        resultado = repo.consultar_por_rango(
            fecha_inicio="2026-11-22T00:00:00",
            fecha_fin="2026-11-23T23:59:59",
        )
        motivos = [a.motivo for a in resultado]
        assert "b" in motivos
        assert "c" in motivos
        assert "a" not in motivos
        assert "d" not in motivos

    def test_rango_vacio(self, repo):
        repo.registrar(motivo="a", timestamp="2026-11-22T01:00:00")
        resultado = repo.consultar_por_rango(
            fecha_inicio="2027-01-01T00:00:00",
            fecha_fin="2027-01-31T23:59:59",
        )
        assert resultado == []


# ---------------------------------------------------------------------------
# Pruebas: no escribe en BD de ofertas (SUP-003)
# ---------------------------------------------------------------------------

class TestSup003SinTablaOfertas:
    """El componente no escribe en ninguna base de datos de ofertas."""

    def test_no_crea_tabla_ofertas(self, conexion, repo):
        repo.registrar(
            motivo="test",
            timestamp="2026-11-22T01:00:00",
            codigos_afectados=["062026099999"],
        )
        tablas = {
            fila["name"]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas
