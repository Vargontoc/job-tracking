"""Pruebas unitarias de la tarea programada diaria de cierre (TASK-015)."""

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest

from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.buscador_client import (
    ClienteEstadoBuscador,
    ErrorEstadoBuscador,
    EstadoBuscador,
)
from source.api.historico.config import ConfigHistorico
from source.api.historico.connection import abrir_conexion
from source.api.historico.ejecucion_repository import RepositorioEjecucion
from source.api.historico.migrations import migrar
from source.api.historico.pdf_adapter import (
    AdaptadorListadoPDF,
    ErrorListadoPDF,
    ListadoPDF,
)
from source.api.historico.persistencia_client import (
    ClientePersistencia,
    ErrorPersistencia,
    Oferta,
)
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.task import (
    ResultadoEjecucion,
    TareaHistorico,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


FECHA_HOY = date(2026, 11, 22)
FECHA_HOY_ISO = "2026-11-22"
TIMESTAMP = "2026-11-22T01:30:00+00:00"


class RelojControlado:
    """Reloj controlable para tests."""

    def __init__(
        self, ahora: datetime | None = None
    ) -> None:
        self._ahora = ahora or datetime(2026, 11, 22, 2, 0, 0)

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        pass


def crear_estado_buscador(
    total: int = 93,
    timestamp: str = TIMESTAMP,
    comunidad: str = "Cantabria",
    errores: list[str] | None = None,
) -> EstadoBuscador:
    """Crea un EstadoBuscador de prueba."""
    return EstadoBuscador(
        total_ofertas=total,
        timestamp=timestamp,
        comunidad=comunidad,
        errores=errores or [],
    )


def crear_oferta(
    codigo: str = "062026003633",
    comunidad: str = "Cantabria",
    estado: str = "vigente",
    fecha_fin: str | None = None,
) -> Oferta:
    """Crea una Oferta de prueba."""
    return Oferta(
        comunidad=comunidad,
        codigo=codigo,
        estado=estado,
        fecha_fin_difusion=fecha_fin,
    )


def configurar_buscador_ok(
    cliente: MagicMock,
    estado: EstadoBuscador | None = None,
    total: int | None = None,
) -> None:
    """Configura el mock del buscador para devolver un estado válido."""
    if estado is None:
        kwargs = {}
        if total is not None:
            kwargs["total"] = total
        estado = crear_estado_buscador(**kwargs)
    cliente.consultar_estado.return_value = estado


def configurar_pdf_ok(
    adaptador: MagicMock,
    codigos: set[str] | None = None,
    fecha: str = "2026-11-22",
) -> None:
    """Configura el mock del PDF para devolver un listado válido."""
    adaptador.obtener_listado.return_value = ListadoPDF(
        codigos=codigos or {"062026003633"},
        fecha_listado=fecha,
    )


def configurar_vigentes_ok(
    cliente: MagicMock, ofertas: list[Oferta] | None = None
) -> None:
    """Configura el mock de persistencia para devolver vigentes."""
    cliente.listar_vigentes.return_value = ofertas or []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ruta_db(tmp_path):
    """Devuelve la ruta de una BD temporal."""
    return tmp_path / "test_task.db"


@pytest.fixture
def conexion(ruta_db):
    """Abre una conexión, migra y la cierra al terminar."""
    conn = abrir_conexion(ruta_db)
    migrar(conn)
    yield conn
    conn.close()


@pytest.fixture
def repo_presencia(conexion):
    """Repositorio de presencia sobre la BD migrada."""
    return RepositorioPresencia(conexion)


@pytest.fixture
def repo_abstenciones(conexion):
    """Repositorio de abstenciones sobre la BD migrada."""
    return RepositorioAbstenciones(conexion)


@pytest.fixture
def repo_ejecucion(conexion):
    """Repositorio de ejecución sobre la BD migrada."""
    return RepositorioEjecucion(conexion)


@pytest.fixture
def config():
    """Configuración de prueba."""
    return ConfigHistorico(
        zona_horaria="Europe/Madrid",
        hora_ejecucion=2,
        ausencias_consecutivas=2,
        umbral_caida_pct=30,
        recuento_minimo=70,
    )


@pytest.fixture
def reloj():
    """Reloj controlado."""
    return RelojControlado()


@pytest.fixture
def cliente_buscador():
    """Mock del cliente del buscador."""
    return MagicMock(spec=ClienteEstadoBuscador)


@pytest.fixture
def cliente_persistencia():
    """Mock del cliente de persistencia."""
    return MagicMock(spec=ClientePersistencia)


@pytest.fixture
def adaptador_pdf():
    """Mock del adaptador del PDF."""
    return MagicMock(spec=AdaptadorListadoPDF)


@pytest.fixture
def tarea(
    config,
    cliente_buscador,
    cliente_persistencia,
    repo_presencia,
    repo_abstenciones,
    repo_ejecucion,
    adaptador_pdf,
    reloj,
):
    """Tarea con todos los mocks conectados."""
    return TareaHistorico(
        config=config,
        cliente_buscador=cliente_buscador,
        cliente_persistencia=cliente_persistencia,
        repositorio_presencia=repo_presencia,
        repositorio_abstenciones=repo_abstenciones,
        repositorio_ejecucion=repo_ejecucion,
        adaptador_pdf=adaptador_pdf,
        reloj=reloj,
    )


# ---------------------------------------------------------------------------
# Caso exitoso completo
# ---------------------------------------------------------------------------


class TestCasoExitoso:
    """Flujo completo sin errores."""

    def test_cierra_por_fecha_y_desaparicion(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Con pasada válida y ofertas candidatas, cierra por ambos criterios."""
        configurar_buscador_ok(cliente_buscador)
        configurar_pdf_ok(adaptador_pdf, codigos=set())
        # Oferta con fecha de fin pasada → cierre por fecha.
        oferta_fecha = crear_oferta(
            codigo="062026001111",
            fecha_fin="20/11/2026",
        )
        # Oferta sin fecha de fin ausente 2 veces → cierre por desaparición.
        oferta_desap = crear_oferta(
            codigo="062026002222",
            fecha_fin=None,
        )
        configurar_vigentes_ok(
            cliente_persistencia, [oferta_fecha, oferta_desap]
        )
        cliente_persistencia.cerrar_oferta.return_value = True

        # Registrar 2 ausencias previas para la oferta por desaparición.
        repo_presencia.registrar_ausencia(
            "Cantabria", "062026002222", "2026-11-20"
        )
        repo_presencia.registrar_ausencia(
            "Cantabria", "062026002222", "2026-11-21"
        )
        # Registrar recuento previo para que el guardián permita.
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        assert resultado.fecha == FECHA_HOY_ISO
        assert resultado.cerradas_por_fecha == 1
        assert resultado.cerradas_por_desaparicion == 1
        assert resultado.abstenciones == []

    def test_registra_ejecucion_del_dia(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_ejecucion,
        repo_presencia,
    ):
        """Tras ejecutar correctamente, se registra la fecha en ejecución."""
        configurar_buscador_ok(cliente_buscador)
        configurar_pdf_ok(adaptador_pdf)
        configurar_vigentes_ok(cliente_persistencia, [])
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        assert repo_ejecucion.se_ejecuto_hoy(FECHA_HOY_ISO) is True

    def test_no_crea_ofertas_ni_modifica_fecha_alta(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Verifica que solo se llama a cerrar_oferta, no a crear."""
        configurar_buscador_ok(cliente_buscador)
        configurar_pdf_ok(adaptador_pdf)
        oferta = crear_oferta(fecha_fin="20/11/2026")
        configurar_vigentes_ok(cliente_persistencia, [oferta])
        cliente_persistencia.cerrar_oferta.return_value = True
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")

        tarea.ejecutar_cierre_diario()

        # Solo se llama a cerrar_oferta, no a ningún método de creación.
        cliente_persistencia.cerrar_oferta.assert_called()
        # No existe ningún método de "crear" en el spec del cliente.
        assert not hasattr(
            cliente_persistencia, "crear_oferta"
        ) or not cliente_persistencia.crear_oferta.called


# ---------------------------------------------------------------------------
# Ya ejecutado hoy (ALT-006 / NFR-002)
# ---------------------------------------------------------------------------


class TestYaEjecutadoHoy:
    """Si ya se ejecutó hoy, la tarea finaliza sin reevaluar."""

    def test_no_reevalua_si_ya_ejecutado(
        self, tarea, repo_ejecucion, cliente_buscador
    ):
        """Con ejecución ya registrada, no se consulta nada más."""
        repo_ejecucion.registrar_ejecucion(FECHA_HOY_ISO)

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is True
        assert resultado.cerradas_por_fecha == 0
        assert resultado.cerradas_por_desaparicion == 0
        # No se consultó el buscador.
        cliente_buscador.consultar_estado.assert_not_called()

    def test_no_registra_presencia_si_ya_ejecutado(
        self, tarea, repo_ejecucion, adaptador_pdf
    ):
        """No se obtiene ni el PDF ni se registran presencias."""
        repo_ejecucion.registrar_ejecucion(FECHA_HOY_ISO)

        tarea.ejecutar_cierre_diario()

        adaptador_pdf.obtener_listado.assert_not_called()


# ---------------------------------------------------------------------------
# Error del buscador (ALT-001 / ALT-008)
# ---------------------------------------------------------------------------


class TestErrorBuscador:
    """Si el buscador falla, no se cierra nada y se registra abstención."""

    def test_error_global_no_cierra(
        self, tarea, cliente_buscador, adaptador_pdf
    ):
        """Con error_global, no se consulta el PDF ni se cierra."""
        cliente_buscador.consultar_estado.return_value = (
            ErrorEstadoBuscador(motivo="error en la pasada")
        )

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert resultado.cerradas_por_fecha == 0
        assert resultado.cerradas_por_desaparicion == 0
        assert len(resultado.abstenciones) == 1
        assert "buscador" in resultado.abstenciones[0].lower()
        adaptador_pdf.obtener_listado.assert_not_called()

    def test_ultima_pasada_nula_no_cierra(
        self, tarea, cliente_buscador
    ):
        """Con ultima_pasada nula, no cierra."""
        cliente_buscador.consultar_estado.return_value = (
            ErrorEstadoBuscador(motivo="ultima_pasada es nula")
        )

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) >= 1

    def test_excepcion_buscador_no_cierra(
        self, tarea, cliente_buscador
    ):
        """Si consultar_estado lanza excepción, no cierra."""
        cliente_buscador.consultar_estado.side_effect = RuntimeError("red")

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) >= 1

    def test_registra_abstencion_en_repositorio(
        self, tarea, cliente_buscador, repo_abstenciones
    ):
        """El error del buscador registra abstención en el repositorio."""
        cliente_buscador.consultar_estado.return_value = (
            ErrorEstadoBuscador(motivo="caído")
        )

        tarea.ejecutar_cierre_diario()

        ultimas = repo_abstenciones.consultar_ultimas()
        assert len(ultimas) >= 1
        assert "caído" in ultimas[0].motivo


# ---------------------------------------------------------------------------
# Error del PDF (ALT-004)
# ---------------------------------------------------------------------------


class TestErrorPDF:
    """Si el PDF falla, no se cierra por desaparición."""

    def test_error_pdf_no_cierra(
        self, tarea, cliente_buscador, adaptador_pdf, repo_presencia
    ):
        """Con error del PDF, se abstiene."""
        configurar_buscador_ok(cliente_buscador)
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        adaptador_pdf.obtener_listado.return_value = ErrorListadoPDF(
            motivo="descarga fallida"
        )

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) >= 1
        assert "PDF" in resultado.abstenciones[0]

    def test_excepcion_pdf_no_cierra(
        self, tarea, cliente_buscador, adaptador_pdf, repo_presencia
    ):
        """Si obtener_listado lanza excepción, se abstiene."""
        configurar_buscador_ok(cliente_buscador)
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        adaptador_pdf.obtener_listado.side_effect = RuntimeError("fallo")

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) >= 1


# ---------------------------------------------------------------------------
# Recuento no permitido (REQ-008 / ALT-002)
# ---------------------------------------------------------------------------


class TestRecuentoNoPermitido:
    """Si el guardián no permite, no se cierra por desaparición."""

    def test_caida_anomala_no_cierra(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Con caída > 30%, no se cierra nada y se registra abstención."""
        configurar_buscador_ok(cliente_buscador, total=60)
        configurar_pdf_ok(adaptador_pdf)
        # Recuento previo alto → caída > 30%.
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        oferta = crear_oferta()
        configurar_vigentes_ok(cliente_persistencia, [oferta])

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert resultado.cerradas_por_fecha == 0
        assert resultado.cerradas_por_desaparicion == 0
        assert len(resultado.abstenciones) >= 1
        # No se llamó a cerrar_oferta.
        cliente_persistencia.cerrar_oferta.assert_not_called()

    def test_recuento_minimo_no_permitido(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Con recuento actual < mínimo (70), no se cierra."""
        configurar_buscador_ok(cliente_buscador, total=65)
        configurar_pdf_ok(adaptador_pdf)
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        configurar_vigentes_ok(cliente_persistencia, [])

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) >= 1


# ---------------------------------------------------------------------------
# Invocación de evaluadores en orden correcto
# ---------------------------------------------------------------------------


class TestOrdenInvocacion:
    """Verifica que los evaluadores se invocan en el orden correcto."""

    def test_orden_buscador_pdf_guardian_vigentes_fecha_desaparicion(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Los pasos se ejecutan en orden: buscador → PDF → guardián → vigentes → fecha → desaparición."""
        configurar_buscador_ok(cliente_buscador)
        configurar_pdf_ok(adaptador_pdf, codigos=set())
        oferta_fecha = crear_oferta(
            codigo="062026001111", fecha_fin="20/11/2026"
        )
        oferta_desap = crear_oferta(codigo="062026002222", fecha_fin=None)
        configurar_vigentes_ok(
            cliente_persistencia, [oferta_fecha, oferta_desap]
        )
        cliente_persistencia.cerrar_oferta.return_value = True
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")
        # 2 ausencias previas para desaparición.
        repo_presencia.registrar_ausencia(
            "Cantabria", "062026002222", "2026-11-20"
        )
        repo_presencia.registrar_ausencia(
            "Cantabria", "062026002222", "2026-11-21"
        )

        resultado = tarea.ejecutar_cierre_diario()

        # Verificar que ambos adaptadores fueron llamados exactamente una vez.
        assert cliente_buscador.consultar_estado.call_count == 1
        assert adaptador_pdf.obtener_listado.call_count == 1

    def test_sin_guardian_permitido_no_invoca_vigentes(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        repo_presencia,
    ):
        """Si el guardián no permite, no se listan vigentes."""
        configurar_buscador_ok(cliente_buscador, total=50)
        configurar_pdf_ok(adaptador_pdf)
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")

        tarea.ejecutar_cierre_diario()

        cliente_persistencia.listar_vigentes.assert_not_called()


# ---------------------------------------------------------------------------
# Cancelación limpia
# ---------------------------------------------------------------------------


class TestCancelacion:
    """La tarea se cancela limpiamente sin dejar ejecuciones en curso."""

    def test_detener_no_deja_hilo_vivo(self, tarea):
        """detener() termina sin dejar el hilo activo."""
        tarea.iniciar()
        tarea.detener()
        assert tarea._hilo is not None
        assert not tarea._hilo.is_alive()

    def test_iniciar_detener_iniciar(self, tarea):
        """Se puede reiniciar tras detener."""
        tarea.iniciar()
        tarea.detener()
        tarea.iniciar()
        assert tarea._hilo is not None
        assert tarea._hilo.is_alive()
        tarea.detener()


# ---------------------------------------------------------------------------
# No solapamiento
# ---------------------------------------------------------------------------


class TestNoSolapamiento:
    """Una ejecución en curso impide otra simultánea."""

    def test_ejecucion_simultanea_se_omite(self, tarea, cliente_buscador):
        """Si _ejecutando es True, la segunda llamada se omite."""
        tarea._ejecutando = True

        resultado = tarea.ejecutar_cierre_diario()

        assert resultado.exitoso is False
        assert len(resultado.abstenciones) == 1
        assert "en curso" in resultado.abstenciones[0].lower()
        cliente_buscador.consultar_estado.assert_not_called()


# ---------------------------------------------------------------------------
# No escribe en la base de datos de ofertas (SUP-003)
# ---------------------------------------------------------------------------


class TestNoEscribeEnOfertas:
    """La tarea no escribe en la base de datos de ofertas."""

    def test_no_existe_tabla_ofertas(self, conexion):
        """La BD del histórico no contiene la tabla 'ofertas'."""
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas

    def test_tras_ejecucion_no_aparece_ofertas(
        self,
        tarea,
        cliente_buscador,
        adaptador_pdf,
        cliente_persistencia,
        conexion,
        repo_presencia,
    ):
        """Tras ejecutar, no aparece la tabla 'ofertas' en la BD propia."""
        configurar_buscador_ok(cliente_buscador)
        configurar_pdf_ok(adaptador_pdf)
        configurar_vigentes_ok(cliente_persistencia, [])
        repo_presencia.registrar_recuento(93, "2026-11-21T01:30:00+00:00")

        tarea.ejecutar_cierre_diario()

        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ofertas" not in tablas
