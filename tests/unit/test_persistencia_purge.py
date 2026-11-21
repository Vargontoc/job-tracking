"""Pruebas de la tarea periódica de purga por retención (TASK-011)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.purge import RelojReal, TareaPurga
from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal vacía."""
    return tmp_path / "test_purge.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión a una BD temporal, migra y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repositorio(conexion):
    """Devuelve un RepositorioOfertas sobre la BD temporal migrada."""
    return RepositorioOfertas(conexion)


class RelojFijo:
    """Reloj inyectable con hora fija y sleep no bloqueante."""

    def __init__(self, hora: datetime) -> None:
        self._hora = hora
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._hora

    def sleep(self, segundos: float) -> None:
        self.sleeps.append(segundos)


def _oferta_cerrada(
    codigo: str = "000000000001",
    fecha_cierre: str | None = None,
    interesada: bool = False,
    texto_libre: str = "Texto de la oferta",
    contacto: str = "contacto@empresa.com",
    embedding: np.ndarray | None = None,
    **kwargs,
) -> Oferta:
    """Crea una oferta cerrada con fecha de cierre y texto/contacto."""
    if fecha_cierre is None:
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    if embedding is None:
        embedding = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    valores = dict(
        comunidad="Cantabria",
        codigo=codigo,
        estado=EstadoOferta.CERRADA,
        provincia="Cantabria",
        ocupacion="Ingeniero",
        municipio="Santander",
        fecha_inicio_difusion="01/01/2026",
        fecha_fin_difusion="31/03/2026",
        texto_libre=texto_libre,
        contacto=contacto,
        embedding=embedding,
        embedding_model_name="nomic-embed-text",
        embedding_model_version="1.0",
        embedding_dim=4,
        interesada=interesada,
        fecha_cierre=fecha_cierre,
    )
    valores.update(kwargs)
    return Oferta(**valores)


# ---------------------------------------------------------------------------
# Prueba: oferta cerrada fuera de plazo se reduce a registro mínimo
# ---------------------------------------------------------------------------

class TestPurgaOfertaFueraDePlazo:
    """Una oferta cerrada cuya fecha_cierre es anterior al plazo se reduce."""

    def test_se_reduce_a_registro_minimo(self, repositorio, conexion):
        """Tras la purga, texto_libre y contacto quedan vacíos."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(fecha_cierre=fecha_cierre)
        repositorio.crear_o_actualizar(oferta)

        # Reloj: 30 días después del cierre, retención = 7 días
        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.texto_libre == ""
        assert resultado.oferta.contacto == ""


# ---------------------------------------------------------------------------
# Prueba: la oferta reducida conserva el embedding con nombre, versión y dim
# ---------------------------------------------------------------------------

class TestPurgaConservaEmbedding:
    """La oferta reducida conserva el embedding con sus metadatos."""

    def test_conserva_embedding(self, repositorio, conexion):
        """El BLOB, nombre, versión y dimensión se conservan tras la purga."""
        vector = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(
            fecha_cierre=fecha_cierre,
            embedding=vector,
        )
        # Sobrescribir los metadatos del embedding
        oferta.embedding_model_name = "nomic-embed-text"
        oferta.embedding_model_version = "1.5"
        oferta.embedding_dim = 5
        repositorio.crear_o_actualizar(oferta)

        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        o = resultado.oferta
        assert o.embedding is not None
        np.testing.assert_array_almost_equal(o.embedding, vector)
        assert o.embedding_model_name == "nomic-embed-text"
        assert o.embedding_model_version == "1.5"
        assert o.embedding_dim == 5


# ---------------------------------------------------------------------------
# Prueba: oferta cerrada dentro del plazo no se modifica
# ---------------------------------------------------------------------------

class TestPurgaDentroDePlazo:
    """Una oferta cerrada cuya fecha_cierre está dentro del plazo no se toca."""

    def test_no_se_modifica(self, repositorio, conexion):
        """Texto y contacto permanecen intactos si la oferta está dentro del plazo."""
        fecha_cierre = datetime(2026, 6, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(
            fecha_cierre=fecha_cierre,
            texto_libre="Texto importante",
            contacto="contacto@test.com",
        )
        repositorio.crear_o_actualizar(oferta)

        # Reloj: 3 días después del cierre, retención = 7 días
        reloj = RelojFijo(datetime(2026, 6, 4, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.texto_libre == "Texto importante"
        assert resultado.oferta.contacto == "contacto@test.com"


# ---------------------------------------------------------------------------
# Prueba: oferta cerrada con interesada=true se omite
# ---------------------------------------------------------------------------

class TestPurgaInteresadaSeOmite:
    """Una oferta cerrada con interesada=true se omite y conserva texto y contacto."""

    def test_interesada_no_se_purga(self, repositorio, conexion):
        """Una oferta marcada como interesada conserva texto_libre y contacto."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(
            fecha_cierre=fecha_cierre,
            interesada=True,
            texto_libre="No me borres",
            contacto="interesada@test.com",
        )
        repositorio.crear_o_actualizar(oferta)

        # Reloj: 30 días después del cierre, retención = 7 días
        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.texto_libre == "No me borres"
        assert resultado.oferta.contacto == "interesada@test.com"
        assert resultado.oferta.interesada is True


# ---------------------------------------------------------------------------
# Prueba: oferta vigente o sin_ficha nunca se purga
# ---------------------------------------------------------------------------

class TestPurgaNoTocaVigenteNiSinFicha:
    """Una oferta en estado vigente o sin_ficha nunca se purga."""

    def test_vigente_no_se_purga(self, repositorio, conexion):
        """Una oferta vigente con fecha_cierre antigua no se purga."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(
            codigo="000000000010",
            estado=EstadoOferta.VIGENTE,
            fecha_cierre=fecha_cierre,
            texto_libre="Soy vigente",
            contacto="vigente@test.com",
        )
        repositorio.crear_o_actualizar(oferta)

        reloj = RelojFijo(datetime(2026, 6, 1, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000010")
        assert resultado.encontrada is True
        assert resultado.oferta.texto_libre == "Soy vigente"
        assert resultado.oferta.contacto == "vigente@test.com"
        assert resultado.oferta.estado == EstadoOferta.VIGENTE

    def test_sin_ficha_no_se_purga(self, repositorio, conexion):
        """Una oferta sin_ficha con fecha_cierre no se purga."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = Oferta(
            comunidad="Cantabria",
            codigo="000000000020",
            estado=EstadoOferta.SIN_FICHA,
            fecha_cierre=fecha_cierre,
            texto_libre="Soy sin ficha",
            contacto="sinficha@test.com",
        )
        repositorio.crear_o_actualizar(oferta)

        reloj = RelojFijo(datetime(2026, 6, 1, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000020")
        assert resultado.encontrada is True
        assert resultado.oferta.texto_libre == "Soy sin ficha"
        assert resultado.oferta.contacto == "sinficha@test.com"
        assert resultado.oferta.estado == EstadoOferta.SIN_FICHA


# ---------------------------------------------------------------------------
# Prueba: la tarea se programa con la frecuencia configurada y se cancela
# ---------------------------------------------------------------------------

class TestProgramacionYCancelacion:
    """La tarea se programa con la frecuencia y se cancela sin dejar ejecuciones."""

    def test_iniciar_y_detener(self, repositorio, conexion):
        """iniciar() arranca el hilo y detener() lo cancela limpiamente."""
        reloj = RelojFijo(datetime(2026, 6, 1, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=1,  # frecuencia muy corta para el test
            reloj=reloj,
        )

        tarea.iniciar()
        assert tarea._hilo is not None
        assert tarea._hilo.is_alive()
        assert tarea._hilo.daemon is True

        tarea.detener()
        # Tras detener, el hilo no debe estar vivo
        time.sleep(0.2)
        assert not tarea._hilo.is_alive()

    def test_detener_sin_iniciar_no_falla(self, repositorio, conexion):
        """Llamar a detener() sin haber llamado iniciar() no produce error."""
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
        )
        # No debe lanzar excepción
        tarea.detener()

    def test_iniciar_dos_veces_no_duplica_hilo(self, repositorio, conexion):
        """Llamar a iniciar() dos veces no crea un segundo hilo."""
        reloj = RelojFijo(datetime(2026, 6, 1, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=3600,
            reloj=reloj,
        )

        tarea.iniciar()
        hilo_1 = tarea._hilo
        tarea.iniciar()
        hilo_2 = tarea._hilo

        assert hilo_1 is hilo_2  # mismo hilo, no se duplica

        tarea.detener()


# ---------------------------------------------------------------------------
# Prueba: la purga no modifica ingesta_log ni el estado de las ofertas
# ---------------------------------------------------------------------------

class TestPurgaNoModificaLogNiEstado:
    """La purga no modifica la fila de ingesta_log ni el estado de las ofertas."""

    def test_no_modifica_ingesta_log(self, repositorio, conexion):
        """La fila de ingesta_log permanece intacta tras la purga."""
        # Comprobar el estado inicial de ingesta_log
        antes = conexion.execute(
            "SELECT id, ultimo_timestamp, actualizado_en FROM ingesta_log WHERE id = 1"
        ).fetchone()
        assert antes is not None

        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(fecha_cierre=fecha_cierre)
        repositorio.crear_o_actualizar(oferta)

        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        despues = conexion.execute(
            "SELECT id, ultimo_timestamp, actualizado_en FROM ingesta_log WHERE id = 1"
        ).fetchone()
        assert despues == antes

    def test_no_modifica_estado_ofertas(self, repositorio, conexion):
        """El estado de las ofertas permanece 'cerrada' tras la purga."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(fecha_cierre=fecha_cierre)
        repositorio.crear_o_actualizar(oferta)

        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        resultado = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert resultado.encontrada is True
        assert resultado.oferta.estado == EstadoOferta.CERRADA

    def test_no_modifica_fechas_ni_interesada(self, repositorio, conexion):
        """fecha_alta, fecha_cierre, interesada y fecha_ultima_actualizacion no cambian."""
        fecha_cierre = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
        oferta = _oferta_cerrada(fecha_cierre=fecha_cierre, interesada=False)
        repositorio.crear_o_actualizar(oferta)

        antes = repositorio.consultar_por_clave("Cantabria", "000000000001")
        fecha_alta_antes = antes.oferta.fecha_alta
        fecha_cierre_antes = antes.oferta.fecha_cierre
        fecha_update_antes = antes.oferta.fecha_ultima_actualizacion

        reloj = RelojFijo(datetime(2026, 1, 31, tzinfo=timezone.utc))
        tarea = TareaPurga(
            repositorio=repositorio,
            conexion=conexion,
            dias_retencion=7,
            frecuencia_segundos=86400,
            reloj=reloj,
        )

        tarea._purgar()

        despues = repositorio.consultar_por_clave("Cantabria", "000000000001")
        assert despues.oferta.fecha_alta == fecha_alta_antes
        assert despues.oferta.fecha_cierre == fecha_cierre_antes
        assert despues.oferta.interesada is False
        assert despues.oferta.fecha_ultima_actualizacion == fecha_update_antes
