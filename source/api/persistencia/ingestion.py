"""Tarea periódica de ingesta de ofertas completas desde el buscador."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from source.api.buscador.scheduler import RelojReal

from source.api.persistencia.client import ClienteBuscador
from source.api.persistencia.connection import transaccion
from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocolo de reloj (compatible con source.api.buscador.scheduler)
# ---------------------------------------------------------------------------


class RelojProtocol(Protocol):
    """Protocolo para inyección de reloj en pruebas."""

    def now(self) -> datetime:
        """Devuelve el datetime actual."""
        ...

    def sleep(self, segundos: float) -> None:
        """Duerme durante el tiempo indicado."""
        ...


# ---------------------------------------------------------------------------
# Resultado de un ciclo de ingesta (para diagnóstico y pruebas)
# ---------------------------------------------------------------------------


@dataclass
class ResultadoCiclo:
    """Resultado de un ciclo de ingesta.

    Atributos:
        ejecutado: Si el ciclo llegó a procesar ofertas (timestamp nuevo).
        timestamp_procesado: Timestamp de la pasada procesada, o vacío.
        ofertas_procesadas: Número de ofertas persistidas en este ciclo.
        motivo_omision: Razón por la que no se procesó (vacío si se procesó).
    """

    ejecutado: bool = False
    timestamp_procesado: str = ""
    ofertas_procesadas: int = 0
    motivo_omision: str = ""


# ---------------------------------------------------------------------------
# Tarea de ingesta
# ---------------------------------------------------------------------------


@dataclass
class TareaIngesta:
    """Tarea periódica de ingesta de ofertas completas.

    En cada ciclo consulta ``GET /buscador/status`` mediante el cliente,
    compara el ``timestamp`` de ``ultima_pasada`` con el último importado
    almacenado en ``ingesta_log``, y solo cuando difiere envía cada oferta
    de ``ofertas_nuevas`` al repositorio para su persistencia antes de
    registrar ese ``timestamp`` como importado.

    Args:
        cliente_buscador: Cliente HTTP de ``GET /buscador/status``.
        repositorio: Repositorio de ofertas.
        conexion: Conexión SQLite compartida (``check_same_thread=False``).
        cadencia_segundos: Intervalo entre ciclos de ingesta.
        reloj: Reloj inyectable para pruebas (por defecto, reloj real).
    """

    cliente_buscador: ClienteBuscador
    repositorio: RepositorioOfertas
    conexion: sqlite3.Connection
    cadencia_segundos: int = 300
    reloj: RelojProtocol = field(default_factory=RelojReal)
    _evento_parada: threading.Event = field(
        default_factory=threading.Event, repr=False
    )
    _hilo: threading.Thread | None = field(default=None, repr=False)
    _en_ejecucion: bool = field(default=False, repr=False)
    _lock_ciclo: threading.Lock = field(default_factory=threading.Lock, repr=False)
    ultimo_resultado: ResultadoCiclo = field(
        default_factory=ResultadoCiclo, repr=False
    )

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def iniciar(self) -> None:
        """Arranca el hilo daemon que ejecuta ciclos de ingesta."""
        if self._hilo is not None and self._hilo.is_alive():
            logger.warning("La tarea de ingesta ya está en ejecución.")
            return
        self._evento_parada.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        logger.info(
            "Tarea de ingesta iniciada (cadencia=%ds).", self.cadencia_segundos
        )

    def detener(self) -> None:
        """Cancela el hilo usando un ``threading.Event``."""
        logger.info("Deteniendo tarea de ingesta...")
        self._evento_parada.set()
        if self._hilo is not None:
            self._hilo.join(timeout=10.0)
            if self._hilo.is_alive():
                logger.warning(
                    "La tarea de ingesta no se detuvo en el tiempo esperado."
                )
        logger.info("Tarea de ingesta detenida.")

    # ------------------------------------------------------------------
    # Bucle y ciclo
    # ------------------------------------------------------------------

    def _bucle(self) -> None:
        """Bucle principal: ejecuta ciclos con la cadencia configurada."""
        while not self._evento_parada.is_set():
            try:
                self._ejecutar_ciclo()
            except Exception as exc:
                logger.error("Error inesperado en la tarea de ingesta: %s", exc)
            # Esperar la cadencia o la señal de parada
            if self._evento_parada.wait(timeout=self.cadencia_segundos):
                break

    def _ejecutar_ciclo(self) -> ResultadoCiclo:
        """Ejecuta un ciclo de ingesta evitando solapamientos.

        Usa un lock para evitar que dos ciclos se solapen. Si ya hay un
        ciclo en ejecución, devuelve un resultado indicando la omisión.
        Las excepciones se capturan para no lanzar al hilo principal.
        """
        if not self._lock_ciclo.acquire(blocking=False):
            logger.warning("Ciclo de ingesta omitido: otro ciclo en ejecución.")
            return ResultadoCiclo(motivo_omision="ciclo_anterior_en_ejecucion")
        try:
            resultado = self._ciclo()
            self.ultimo_resultado = resultado
            return resultado
        except Exception as exc:
            logger.error("Error durante el ciclo de ingesta: %s", exc)
            return ResultadoCiclo(motivo_omision=f"error: {exc}")
        finally:
            self._lock_ciclo.release()

    def _ciclo(self) -> ResultadoCiclo:
        """Ciclo de ingesta: consulta, compara y persiste."""
        # 1. Consultar el estado del buscador
        resultado_consulta = self.cliente_buscador.consultar_estado()

        # 2. Si hay error o ultima_pasada es nula, registrar log y terminar
        if resultado_consulta.error:
            logger.info(
                "Ciclo de ingesta: buscador no accesible (%s).",
                resultado_consulta.error,
            )
            return ResultadoCiclo(motivo_omision=resultado_consulta.error)

        estado = resultado_consulta.estado
        if estado is None or estado.ultima_pasada is None:
            logger.info("Ciclo de ingesta: ultima_pasada nula.")
            return ResultadoCiclo(motivo_omision="ultima_pasada_nula")

        ultima = estado.ultima_pasada
        timestamp_nuevo = ultima.timestamp

        # 3. Leer ingesta_log para obtener el último timestamp importado
        ultimo_importado = self._leer_ultimo_timestamp()

        # 4. Si el timestamp es igual al último importado, terminar (idempotente)
        if timestamp_nuevo and timestamp_nuevo == ultimo_importado:
            logger.debug(
                "Ciclo de ingesta: timestamp %s ya importado, omitiendo.",
                timestamp_nuevo,
            )
            return ResultadoCiclo(motivo_omision="timestamp_ya_importado")

        # 5. Si error_global no está vacío, registrar log y terminar
        if ultima.error_global:
            logger.info(
                "Ciclo de ingesta: error_global en la pasada (%s).",
                ultima.error_global,
            )
            return ResultadoCiclo(
                motivo_omision=f"error_global: {ultima.error_global}"
            )

        # 6. Persistir cada oferta de ofertas_nuevas
        ofertas_procesadas = 0
        for datos_oferta in ultima.ofertas_nuevas:
            try:
                oferta = _oferta_desde_datos(datos_oferta)
                if self._persistir_oferta(oferta):
                    ofertas_procesadas += 1
            except Exception as exc:
                logger.warning(
                    "Error procesando oferta %s: %s",
                    datos_oferta.get("numero_oferta", "?"),
                    exc,
                )

        # 7. Actualizar ingesta_log con el nuevo timestamp y actualizado_en
        self._actualizar_timestamp(timestamp_nuevo)

        logger.info(
            "Ciclo de ingesta completado: timestamp=%s, ofertas_procesadas=%d.",
            timestamp_nuevo,
            ofertas_procesadas,
        )
        return ResultadoCiclo(
            ejecutado=True,
            timestamp_procesado=timestamp_nuevo,
            ofertas_procesadas=ofertas_procesadas,
        )

    # ------------------------------------------------------------------
    # Helpers de persistencia
    # ------------------------------------------------------------------

    def _leer_ultimo_timestamp(self) -> str:
        """Lee el último timestamp importado de ``ingesta_log`` (id=1)."""
        fila = self.conexion.execute(
            "SELECT ultimo_timestamp FROM ingesta_log WHERE id = 1"
        ).fetchone()
        if fila is None or fila[0] is None:
            return ""
        return fila[0]

    def _actualizar_timestamp(self, timestamp: str) -> None:
        """Actualiza ``ingesta_log`` con el nuevo timestamp y ``actualizado_en``."""
        ahora = self.reloj.now().isoformat()
        with transaccion(self.conexion):
            self.conexion.execute(
                """UPDATE ingesta_log
                   SET ultimo_timestamp = ?, actualizado_en = ?
                   WHERE id = 1""",
                (timestamp, ahora),
            )

    def _persistir_oferta(self, oferta: Oferta) -> bool:
        """Persiste una oferta según su estado actual en la base de datos.

        - Si ya existe con estado ``vigente``, la omite (no sobrescribe con vacíos).
        - Si existe con estado ``sin_ficha``, la actualiza con los datos de la ficha.
        - Si no existe, la crea con estado ``vigente``.

        Returns:
            ``True`` si se persistió (creada o actualizada), ``False`` si se omitió.
        """
        resultado = self.repositorio.consultar_por_clave(
            oferta.comunidad, oferta.codigo
        )

        if resultado.encontrada and resultado.oferta is not None:
            if resultado.oferta.estado == EstadoOferta.VIGENTE:
                # No sobrescribir oferta vigente con datos potencialmente vacíos
                return False
            # sin_ficha u otro estado: completar con los datos de la ficha
            self.repositorio.crear_o_actualizar(oferta)
            return True

        # No existe: crear con estado vigente
        self.repositorio.crear_o_actualizar(oferta)
        return True


# ---------------------------------------------------------------------------
# Helper de conversión
# ---------------------------------------------------------------------------


def _oferta_desde_datos(datos: dict) -> Oferta:
    """Convierte los datos de una oferta del buscador en una :class:`Oferta`.

    Los campos ``sector``, ``nivel`` y ``contrato`` se almacenan vacíos
    (DEC-009), independientemente de lo que traigan los datos.
    """
    return Oferta(
        comunidad=datos.get("comunidad", "Cantabria"),
        codigo=datos.get("numero_oferta", ""),
        estado=EstadoOferta.VIGENTE,
        provincia=datos.get("provincia", ""),
        ocupacion=datos.get("ocupacion", ""),
        municipio=datos.get("municipio", ""),
        fecha_inicio_difusion=datos.get("fecha_inicio_difusion"),
        fecha_fin_difusion=datos.get("fecha_fin_difusion"),
        texto_libre=datos.get("texto_libre", ""),
        contacto=datos.get("contacto", ""),
    )
