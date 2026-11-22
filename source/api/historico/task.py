"""Tarea programada diaria de cierre del histórico.

Orquesta los evaluadores de cierre (por fecha y por desaparición) a la hora
configurada, sin modificar el planificador de ``api-buscador``. Cada disparo:

1. Comprueba si ya se ejecutó hoy (ALT-006/NFR-002).
2. Consulta el estado del buscador (ALT-001/ALT-008).
3. Obtiene el listado oficial del PDF (ALT-004).
4. Valida el recuento con el guardián (REQ-008/ALT-002).
5. Obtiene las ofertas vigentes.
6. Ejecuta el cierre por fecha (REQ-003).
7. Ejecuta el cierre por desaparición (REQ-005).
8. Registra la ejecución del día.

Las escrituras van por ``persistencia-adapter``; no crea ofertas nuevas ni
altera ``fecha_alta`` (REQ-001). Un disparo no se solapa consigo mismo.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Protocol
from zoneinfo import ZoneInfo

from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.buscador_client import (
    ClienteEstadoBuscador,
    ErrorEstadoBuscador,
    EstadoBuscador,
)
from source.api.historico.cierre_fecha import EvaluadorCierreFecha
from source.api.historico.config import ConfigHistorico
from source.api.historico.desaparicion import EvaluadorDesaparicion
from source.api.historico.ejecucion_repository import RepositorioEjecucion
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
from source.api.historico.recuento_guardian import GuardianRecuento

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocolo del reloj inyectable (local, sin importar de otras features)
# ---------------------------------------------------------------------------


class RelojProtocol(Protocol):
    """Protocolo de reloj para inyectar la fecha y hora actuales en pruebas."""

    def now(self) -> datetime:
        """Devuelve el datetime actual."""
        ...

    def sleep(self, segundos: float) -> None:
        """Duerme durante el tiempo indicado."""
        ...


class RelojReal:
    """Reloj que usa la hora real del sistema."""

    def now(self) -> datetime:
        return datetime.now()

    def sleep(self, segundos: float) -> None:
        time.sleep(segundos)


# ---------------------------------------------------------------------------
# Adaptador interno para el protocolo de fecha de EvaluadorCierreFecha
# ---------------------------------------------------------------------------


class _RelojFechaAdaptador:
    """Adapta un RelojProtocol (now/sleep) al protocolo de ``hoy(zona)``."""

    def __init__(self, reloj: RelojProtocol) -> None:
        self._reloj = reloj

    def hoy(self, zona: ZoneInfo) -> date:
        return self._reloj.now().astimezone(zona).date()


# ---------------------------------------------------------------------------
# Resultado de la ejecución diaria
# ---------------------------------------------------------------------------


@dataclass
class ResultadoEjecucion:
    """Resultado de la ejecución diaria del cierre.

    Atributos:
        fecha: Fecha de ejecución (YYYY-MM-DD) en la zona horaria configurada.
        exitoso: ``True`` si se completaron los cierres sin errores graves.
        cerradas_por_fecha: Número de ofertas cerradas por fecha de fin.
        cerradas_por_desaparicion: Número de ofertas cerradas por desaparición.
        errores: Lista de mensajes de error producidos durante la ejecución.
        abstenciones: Lista de motivos de abstención registrados.
    """

    fecha: str = ""
    exitoso: bool = False
    cerradas_por_fecha: int = 0
    cerradas_por_desaparicion: int = 0
    errores: list[str] = field(default_factory=list)
    abstenciones: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tarea programada
# ---------------------------------------------------------------------------


class TareaHistorico:
    """Tarea programada diaria de cierre del histórico.

    Orquesta los evaluadores de cierre a la hora configurada (por defecto
    02:00, posterior a la pasada del buscador). Cada disparo consulta el
    estado del buscador, valida el recuento con el guardián y ejecuta los
    cierres correspondientes. Un disparo no se solapa consigo mismo.

    Args:
        config: Configuración del histórico (TASK-002).
        cliente_buscador: Cliente del estado del buscador (TASK-008).
        cliente_persistencia: Cliente de persistencia-api (TASK-009).
        repositorio_presencia: Repositorio de presencia (TASK-005).
        repositorio_abstenciones: Repositorio de abstenciones (TASK-006).
        repositorio_ejecucion: Repositorio de ejecución diaria (TASK-007).
        adaptador_pdf: Adaptador del listado PDF (TASK-011).
        reloj: Reloj inyectable para pruebas. Si es ``None``, se usa el
            reloj real del sistema.
    """

    def __init__(
        self,
        config: ConfigHistorico,
        cliente_buscador: ClienteEstadoBuscador,
        cliente_persistencia: ClientePersistencia,
        repositorio_presencia: RepositorioPresencia,
        repositorio_abstenciones: RepositorioAbstenciones,
        repositorio_ejecucion: RepositorioEjecucion,
        adaptador_pdf: AdaptadorListadoPDF,
        reloj: RelojProtocol | None = None,
    ) -> None:
        self._config = config
        self._cliente_buscador = cliente_buscador
        self._cliente_persistencia = cliente_persistencia
        self._repositorio_presencia = repositorio_presencia
        self._repositorio_abstenciones = repositorio_abstenciones
        self._repositorio_ejecucion = repositorio_ejecucion
        self._adaptador_pdf = adaptador_pdf
        self._reloj = reloj if reloj is not None else RelojReal()
        self._zona = ZoneInfo(config.zona_horaria)
        self._evento_parada = threading.Event()
        self._hilo: threading.Thread | None = None
        self._ejecutando = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def iniciar(self) -> None:
        """Arranca el hilo del planificador en segundo plano (daemon)."""
        if self._hilo is not None and self._hilo.is_alive():
            logger.warning("La tarea del histórico ya está en ejecución")
            return
        self._evento_parada.clear()
        self._hilo = threading.Thread(target=self._ciclo, daemon=True)
        self._hilo.start()
        logger.info(
            "Tarea del histórico iniciada, próxima ejecución a las "
            "%02d:00",
            self._config.hora_ejecucion,
        )

    def detener(self) -> None:
        """Detiene el planificador de forma limpia, sin dejar ejecuciones."""
        logger.info("Deteniendo tarea del histórico...")
        self._evento_parada.set()
        if self._hilo is not None:
            self._hilo.join(timeout=10.0)
            if self._hilo.is_alive():
                logger.warning(
                    "La tarea del histórico no se detuvo en el tiempo esperado"
                )
        logger.info("Tarea del histórico detenida")

    def ejecutar_cierre_diario(self) -> ResultadoEjecucion:
        """Ejecuta el cierre diario de ofertas.

        Orquesta los evaluadores según el flujo documentado. No lanza
        excepciones; los errores se capturan y se incluyen en el resultado.
        Si ya hay una ejecución en curso, se omite (no se solapa).

        Returns:
            Resultado con la fecha, el éxito y los contadores de cierres.
        """
        with self._lock:
            if self._ejecutando:
                logger.info("Ya hay una ejecución en curso, se omite")
                return ResultadoEjecucion(
                    fecha=self._fecha_hoy_iso(),
                    exitoso=False,
                    abstenciones=["Ejecución en curso, se omite"],
                )
            self._ejecutando = True

        try:
            return self._ejecutar_cierre_diario_interno()
        finally:
            self._ejecutando = False

    # ------------------------------------------------------------------
    # Ciclo interno del scheduler
    # ------------------------------------------------------------------

    def _ciclo(self) -> None:
        """Ciclo principal del planificador."""
        while not self._evento_parada.is_set():
            try:
                self._esperar_hora_configurada()
                if self._evento_parada.is_set():
                    break
                self.ejecutar_cierre_diario()
            except Exception as exc:
                logger.error(
                    "Error en el ciclo de la tarea del histórico: %s", exc
                )
                if not self._evento_parada.wait(timeout=60.0):
                    continue

    def _esperar_hora_configurada(self) -> None:
        """Calcula y espera hasta la próxima hora configurada."""
        ahora = self._reloj.now()
        siguiente = self._calcular_siguiente_ejecucion(ahora)
        segundos_espera = (siguiente - ahora).total_seconds()
        if segundos_espera > 0:
            logger.debug(
                "Esperando %.1fs hasta la próxima ejecución", segundos_espera
            )
            self._evento_parada.wait(timeout=segundos_espera)

    def _calcular_siguiente_ejecucion(self, ahora: datetime) -> datetime:
        """Calcula la próxima ejecución según la hora configurada."""
        hora = self._config.hora_ejecucion
        siguiente = ahora.replace(
            hour=hora, minute=0, second=0, microsecond=0
        )
        if ahora >= siguiente:
            siguiente += timedelta(days=1)
        return siguiente

    # ------------------------------------------------------------------
    # Lógica de cierre diario
    # ------------------------------------------------------------------

    def _ejecutar_cierre_diario_interno(self) -> ResultadoEjecucion:
        """Implementación interna del cierre diario."""
        fecha_hoy = self._fecha_hoy_iso()
        resultado = ResultadoEjecucion(fecha=fecha_hoy)

        # Paso 1: comprobar si ya se ejecutó hoy (ALT-006/NFR-002).
        try:
            ya_ejecutado = self._repositorio_ejecucion.se_ejecuto_hoy(fecha_hoy)
        except Exception as exc:
            resultado.errores.append(
                f"Error al consultar ejecución de hoy: {exc}"
            )
            return resultado

        if ya_ejecutado:
            logger.info(
                "La tarea ya se ejecutó hoy (%s), se omite", fecha_hoy
            )
            resultado.exitoso = True
            return resultado

        # Paso 2: consultar estado del buscador (ALT-001/ALT-008).
        estado_buscador = self._consultar_buscador(resultado)
        if estado_buscador is None:
            return resultado

        # Paso 3: obtener listado oficial del PDF (ALT-004).
        listado_pdf = self._obtener_listado_pdf(resultado)
        if listado_pdf is None:
            return resultado

        # Paso 4: validar recuento con guardián (REQ-008/ALT-002).
        try:
            guardian = self._crear_guardian()
            validacion = guardian.validar(
                estado_buscador.total_ofertas, estado_buscador.timestamp
            )
        except Exception as exc:
            motivo = f"Error al validar recuento: {exc}"
            resultado.abstenciones.append(motivo)
            self._registrar_abstencion(motivo)
            logger.error(motivo)
            return resultado

        if not validacion.permitido:
            motivo = validacion.motivo_abstencion or "Recuento no permitido"
            resultado.abstenciones.append(motivo)
            logger.info("Guardián no permite cierres: %s", motivo)
            return resultado

        # Paso 5: obtener ofertas vigentes.
        vigentes = self._obtener_vigentes(resultado)
        if vigentes is None:
            return resultado

        # Paso 6: ejecutar cierre por fecha (REQ-003).
        try:
            evaluador_fecha = self._crear_evaluador_fecha()
            resultado_fecha = evaluador_fecha.evaluar(vigentes)
            resultado.cerradas_por_fecha = len(resultado_fecha.cerradas)
            resultado.errores.extend(resultado_fecha.errores)
        except Exception as exc:
            resultado.errores.append(
                f"Error en evaluador de cierre por fecha: {exc}"
            )
            logger.error("Error en evaluador de cierre por fecha: %s", exc)
            return resultado

        # Paso 7: ejecutar cierre por desaparición (REQ-005).
        try:
            evaluador_desaparicion = self._crear_evaluador_desaparicion()
            errores_por_oferta = set(estado_buscador.errores)
            resultado_desaparicion = evaluador_desaparicion.evaluar(
                ofertas_vigentes=resultado_fecha.candidatas_desaparicion,
                listado_oficial=listado_pdf.codigos,
                errores_por_oferta=errores_por_oferta,
                fecha_listado=listado_pdf.fecha_listado,
            )
            resultado.cerradas_por_desaparicion = len(
                resultado_desaparicion.cerradas
            )
            resultado.errores.extend(resultado_desaparicion.errores)
        except Exception as exc:
            resultado.errores.append(
                f"Error en evaluador de desaparición: {exc}"
            )
            logger.error("Error en evaluador de desaparición: %s", exc)
            return resultado

        # Paso 8: registrar ejecución del día.
        try:
            self._repositorio_ejecucion.registrar_ejecucion(fecha_hoy)
        except Exception as exc:
            resultado.errores.append(f"Error al registrar ejecución: {exc}")
            return resultado

        resultado.exitoso = True
        logger.info(
            "Cierre diario completado: %d por fecha, %d por desaparición",
            resultado.cerradas_por_fecha,
            resultado.cerradas_por_desaparicion,
        )
        return resultado

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fecha_hoy_iso(self) -> str:
        """Devuelve la fecha de hoy en formato YYYY-MM-DD en la zona."""
        ahora = self._reloj.now()
        fecha_hoy = ahora.astimezone(self._zona).date()
        return fecha_hoy.isoformat()

    def _consultar_buscador(
        self, resultado: ResultadoEjecucion
    ) -> EstadoBuscador | None:
        """Consulta el estado del buscador. Devuelve None si falla."""
        try:
            estado = self._cliente_buscador.consultar_estado()
        except Exception as exc:
            motivo = f"Error al consultar el buscador: {exc}"
            resultado.abstenciones.append(motivo)
            self._registrar_abstencion(motivo)
            logger.warning(motivo)
            return None

        if isinstance(estado, ErrorEstadoBuscador):
            motivo = f"Buscador no disponible: {estado.motivo}"
            resultado.abstenciones.append(motivo)
            self._registrar_abstencion(motivo)
            logger.warning(motivo)
            return None

        return estado

    def _obtener_listado_pdf(
        self, resultado: ResultadoEjecucion
    ) -> ListadoPDF | None:
        """Obtiene el listado oficial del PDF. Devuelve None si falla."""
        try:
            listado = self._adaptador_pdf.obtener_listado()
        except Exception as exc:
            motivo = f"Error al obtener el listado PDF: {exc}"
            resultado.abstenciones.append(motivo)
            self._registrar_abstencion(motivo)
            logger.warning(motivo)
            return None

        if isinstance(listado, ErrorListadoPDF):
            motivo = f"Listado PDF no disponible: {listado.motivo}"
            resultado.abstenciones.append(motivo)
            self._registrar_abstencion(motivo)
            logger.warning(motivo)
            return None

        return listado

    def _obtener_vigentes(
        self, resultado: ResultadoEjecucion
    ) -> list[Oferta] | None:
        """Obtiene las ofertas vigentes. Devuelve None si falla."""
        try:
            vigentes = self._cliente_persistencia.listar_vigentes()
        except Exception as exc:
            resultado.errores.append(f"Error al obtener vigentes: {exc}")
            logger.error("Error al obtener vigentes: %s", exc)
            return None

        if isinstance(vigentes, ErrorPersistencia):
            resultado.errores.append(
                f"Error al obtener vigentes: {vigentes.motivo}"
            )
            logger.error("Error al obtener vigentes: %s", vigentes.motivo)
            return None

        return vigentes

    def _crear_guardian(self) -> GuardianRecuento:
        """Crea el guardián de recuento con los umbrales configurados."""
        return GuardianRecuento(
            repositorio_presencia=self._repositorio_presencia,
            abstenciones=self._repositorio_abstenciones,
            umbral_caida_pct=self._config.umbral_caida_pct,
            recuento_minimo=self._config.recuento_minimo,
        )

    def _crear_evaluador_fecha(self) -> EvaluadorCierreFecha:
        """Crea el evaluador de cierre por fecha con reloj compartido."""
        return EvaluadorCierreFecha(
            cliente_persistencia=self._cliente_persistencia,
            zona_horaria=self._config.zona_horaria,
            reloj=_RelojFechaAdaptador(self._reloj),
        )

    def _crear_evaluador_desaparicion(self) -> EvaluadorDesaparicion:
        """Crea el evaluador de desaparición."""
        return EvaluadorDesaparicion(
            repositorio_presencia=self._repositorio_presencia,
            cliente_persistencia=self._cliente_persistencia,
            abstenciones=self._repositorio_abstenciones,
            n_ausencias=self._config.ausencias_consecutivas,
        )

    def _registrar_abstencion(self, motivo: str) -> None:
        """Registra una abstención en el repositorio."""
        try:
            timestamp = self._reloj.now().astimezone(self._zona).isoformat()
            self._repositorio_abstenciones.registrar(
                motivo=motivo,
                timestamp=timestamp,
            )
        except Exception as exc:
            logger.error("Error al registrar abstención: %s", exc)
