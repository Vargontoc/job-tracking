"""Planificador diario de la pasada automática del rastreador."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador

logger = logging.getLogger(__name__)


class RelojProtocol(Protocol):
    """Protocolo para inyección de reloj en tests."""

    def now(self) -> datetime:
        """Devuelve el datetime actual."""
        ...

    def sleep(self, segundos: float) -> None:
        """Duerme durante el tiempo indicado."""
        ...


class RelojReal:
    """Reloj real del sistema."""

    def now(self) -> datetime:
        return datetime.now()

    def sleep(self, segundos: float) -> None:
        time.sleep(segundos)


@dataclass
class Scheduler:
    """Planificador diario de la pasada automática.

    Ejecuta una pasada del rastreador diariamente a la hora configurada.
    Si al momento de ejecutar ya hay una pasada en curso, omite la ejecución.

    Atributos:
        coordinador: Coordinador de pasadas del rastreador.
        config: Configuración del buscador con hora de ejecución.
        reloj: Reloj inyectable para testing (por defecto, reloj real).
        _evento_parada: Evento para detener el scheduler gracefulmente.
        _hilo: Hilo de ejecución del scheduler.
    """

    coordinador: CoordinadorPasada
    config: ConfigBuscador
    reloj: RelojProtocol = RelojReal()
    _evento_parada: threading.Event = threading.Event()
    _hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        """Arranca el hilo del planificador en segundo plano."""
        if self._hilo is not None and self._hilo.is_alive():
            logger.warning("El scheduler ya está en ejecución")
            return

        self._evento_parada.clear()
        self._hilo = threading.Thread(target=self._ciclo, daemon=True)
        self._hilo.start()
        logger.info(f"Scheduler iniciado, próxima ejecución a las {self.config.hora_pasada:02d}:00")

    def detener(self) -> None:
        """Detiene el scheduler gracefulmente."""
        logger.info("Deteniendo scheduler...")
        self._evento_parada.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5.0)
            if self._hilo.is_alive():
                logger.warning("El scheduler no se detuvo en el tiempo esperado")
        logger.info("Scheduler detenido")

    def _ciclo(self) -> None:
        """Ciclo principal del scheduler."""
        while not self._evento_parada.is_set():
            try:
                self._esperar_hora_configurada()
                if self._evento_parada.is_set():
                    break

                self._ejecutar_pasada_si_posible()

            except Exception as e:
                logger.error(f"Error en el ciclo del scheduler: {e}")
                # Esperar un poco antes de reintentar
                if not self._evento_parada.wait(timeout=60.0):
                    continue

    def _esperar_hora_configurada(self) -> None:
        """Calcula y espera hasta la próxima hora configurada."""
        ahora = self.reloj.now()
        siguiente = self._calcular_siguiente_ejecucion(ahora)
        segundos_espera = (siguiente - ahora).total_seconds()

        if segundos_espera > 0:
            logger.debug(f"Esperando {segundos_espera:.1f}s hasta la próxima ejecución")
            self._evento_parada.wait(timeout=segundos_espera)

    def _calcular_siguiente_ejecucion(self, ahora: datetime) -> datetime:
        """Calcula la próxima ejecución basada en la hora configurada."""
        hora_config = self.config.hora_pasada
        siguiente = ahora.replace(hour=hora_config, minute=0, second=0, microsecond=0)

        # Si la hora de hoy ya pasó, programar para mañana
        if ahora >= siguiente:
            siguiente += timedelta(days=1)

        return siguiente

    def _ejecutar_pasada_si_posible(self) -> None:
        """Ejecuta una pasada si no hay otra en curso."""
        if self.coordinador.pasada_en_curso:
            logger.info("Pasada en curso, omitiendo ejecución del scheduler")
            return

        logger.info("Iniciando pasada automática")
        try:
            self.coordinador.ejecutar_pasada()
            logger.info("Pasada automática completada")
        except Exception as e:
            logger.error(f"Error ejecutando pasada automática: {e}")
