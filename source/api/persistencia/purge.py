"""Tarea periódica de purga por retención.

Consulta las ofertas en estado ``cerrada`` cuya ``fecha_cierre`` supere los
días de retención configurados y cuyo flag ``interesada`` sea ``false``,
y las reduce a registro mínimo mediante el repositorio.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from source.api.persistencia.repository import RepositorioOfertas

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reloj inyectable
# ---------------------------------------------------------------------------

class RelojProtocol(Protocol):
    """Protocolo para inyección de reloj en tests."""

    def now(self) -> datetime:
        """Devuelve el datetime actual."""
        ...

    def sleep(self, segundos: float) -> None:
        """Duerme durante el tiempo indicado."""
        ...


class RelojReal:
    """Reloj real del sistema (UTC)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, segundos: float) -> None:
        time.sleep(segundos)


# ---------------------------------------------------------------------------
# Tarea de purga
# ---------------------------------------------------------------------------

@dataclass
class TareaPurga:
    """Tarea periódica que purga ofertas cerradas tras el plazo de retención.

    Atributos:
        repositorio: Repositorio de ofertas sobre el que ejecutar la reducción.
        conexion: Conexión SQLite para consultar las candidatas a purga.
        dias_retencion: Días que se conservan texto y contacto tras el cierre.
        frecuencia_segundos: Intervalo entre ciclos de purga.
        reloj: Reloj inyectable para testing (por defecto, reloj real UTC).
    """

    repositorio: RepositorioOfertas
    conexion: sqlite3.Connection
    dias_retencion: int
    frecuencia_segundos: int
    reloj: RelojProtocol = field(default_factory=RelojReal)
    _evento_parada: threading.Event = field(default_factory=threading.Event)
    _hilo: threading.Thread | None = field(default=None, repr=False)
    _en_ejecucion: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def iniciar(self) -> None:
        """Arranca el hilo daemon de la tarea de purga."""
        if self._hilo is not None and self._hilo.is_alive():
            logger.warning("La tarea de purga ya está en ejecución")
            return

        self._evento_parada.clear()
        self._hilo = threading.Thread(target=self._ciclo, daemon=True)
        self._hilo.start()
        logger.info(
            "Tarea de purga iniciada (frecuencia=%ds, retención=%d días)",
            self.frecuencia_segundos,
            self.dias_retencion,
        )

    def detener(self) -> None:
        """Detiene la tarea de purga y espera a que termine el hilo."""
        logger.info("Deteniendo tarea de purga...")
        self._evento_parada.set()
        if self._hilo is not None:
            self._hilo.join(timeout=5.0)
            if self._hilo.is_alive():
                logger.warning(
                    "La tarea de purga no se detuvo en el tiempo esperado"
                )
        logger.info("Tarea de purga detenida")

    def _ciclo(self) -> None:
        """Ciclo principal: espera la frecuencia y ejecuta la purga."""
        while not self._evento_parada.is_set():
            # Esperar la frecuencia configurada (interrumpible por parada)
            if self._evento_parada.wait(timeout=self.frecuencia_segundos):
                break

            self._ejecutar_purga_si_posible()

    def _ejecutar_purga_si_posible(self) -> None:
        """Ejecuta la purga si no hay otra en curso (evita solapamiento)."""
        with self._lock:
            if self._en_ejecucion:
                logger.info("Purga en curso, omitiendo ejecución")
                return
            self._en_ejecucion = True

        try:
            self._purgar()
        except Exception:
            logger.exception("Error en la tarea de purga")
        finally:
            with self._lock:
                self._en_ejecucion = False

    def _purgar(self) -> None:
        """Calcula la fecha límite, consulta candidatas y reduce cada una."""
        fecha_limite = (
            self.reloj.now() - timedelta(days=self.dias_retencion)
        )
        fecha_limite_iso = fecha_limite.isoformat()

        filas = self.conexion.execute(
            """SELECT comunidad, codigo
               FROM ofertas
               WHERE estado = 'cerrada'
                 AND interesada = 0
                 AND fecha_cierre IS NOT NULL
                 AND fecha_cierre < ?""",
            (fecha_limite_iso,),
        ).fetchall()

        if not filas:
            logger.debug("No hay ofertas que purgar")
            return

        purgadas = 0
        for comunidad, codigo in filas:
            if self._evento_parada.is_set():
                logger.info(
                    "Parada solicitada durante la purga (%d/%d)",
                    purgadas,
                    len(filas),
                )
                break
            self.repositorio.reducir_a_registro_minimo(comunidad, codigo)
            purgadas += 1

        logger.info("Purga completada: %d ofertas reducidas a registro mínimo", purgadas)
