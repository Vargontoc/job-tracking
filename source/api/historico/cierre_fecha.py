"""Evaluador del cierre por fecha de fin de difusión.

Recibe las ofertas vigentes con ``fecha_fin_difusion`` informada, descarta
las fechas corruptas o imposibles (ALT-005), compara cada fecha de fin con
la fecha actual en la zona horaria configurada (NFR-001) y cierra de forma
idempotente, a través de ``persistencia-adapter``, solo las que tienen
fecha de fin estrictamente anterior a la fecha actual (REQ-003). Las ofertas
con fecha de fin vacía se devuelven como candidatas al cierre por
desaparición (REQ-004).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from source.api.historico.persistencia_client import (
    ErrorPersistencia,
    Oferta,
)


# ---------------------------------------------------------------------------
# Protocolo del reloj inyectable
# ---------------------------------------------------------------------------

class RelojProtocol(Protocol):
    """Protocolo de reloj para inyectar la fecha actual en pruebas."""

    def hoy(self, zona: ZoneInfo) -> date:
        """Devuelve la fecha actual en la zona horaria indicada."""
        ...


class RelojReal:
    """Reloj que devuelve la fecha real del sistema."""

    def hoy(self, zona: ZoneInfo) -> date:
        return datetime.now(tz=zona).date()


class RelojFijo:
    """Reloj de prueba que siempre devuelve la misma fecha.

    Args:
        fecha: Fecha fija que se devolverá en todas las llamadas.
    """

    def __init__(self, fecha: date) -> None:
        self._fecha = fecha

    def hoy(self, zona: ZoneInfo) -> date:
        return self._fecha


# ---------------------------------------------------------------------------
# Dataclass de resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoCierre:
    """Resultado de evaluar el cierre por fecha de fin de difusión.

    Atributos:
        cerradas: Códigos de las ofertas que se cerraron correctamente.
        errores: Mensajes de error para las ofertas que no se pudieron
            cerrar o cuyas fechas eran inválidas.
        candidatas_desaparicion: Ofertas vigentes sin ``fecha_fin_difusion``
            (o con fecha vacía) que se derivan al evaluador de desaparición
            (REQ-004).
        fechas_invalidas: Códigos de ofertas cuyas fechas de fin no
            cumplen el formato ``dd/mm/aaaa`` o son imposibles (ALT-005).
    """

    cerradas: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    candidatas_desaparicion: list[Oferta] = field(default_factory=list)
    fechas_invalidas: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evaluador
# ---------------------------------------------------------------------------

# Expresión regular para validar el formato dd/mm/aaaa.
_FORMATO_FECHA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


class EvaluadorCierreFecha:
    """Evaluador del cierre por fecha de fin de difusión.

    Args:
        cliente_persistencia: Cliente de ``persistencia-api`` para cerrar
            ofertas (TASK-009).
        zona_horaria: Zona horaria IANA para comparar fechas (NFR-001).
        reloj: Reloj inyectable para obtener la fecha actual. Si es
            ``None``, se usa :class:`RelojReal`.
    """

    def __init__(
        self,
        cliente_persistencia: object,
        zona_horaria: str,
        reloj: RelojProtocol | None = None,
    ) -> None:
        self._cliente = cliente_persistencia
        self._zona = ZoneInfo(zona_horaria)
        self._reloj = reloj if reloj is not None else RelojReal()

    def evaluar(self, ofertas_vigentes: list[Oferta]) -> ResultadoCierre:
        """Evalúa el cierre por fecha de fin de difusión.

        Recorre las ofertas vigentes y, para cada una:

        - Si ``fecha_fin_difusion`` está vacía o es ``None``, la añade a
          ``candidatas_desaparicion`` (REQ-004).
        - Si la fecha es inválida (formato o valor imposible), la añade a
          ``fechas_invalidas`` y registra un error (ALT-005).
        - Si la fecha de fin es estrictamente anterior a hoy, cierra la
          oferta a través del cliente de persistencia (REQ-003).
        - Si la fecha de fin es hoy o futura, la oferta permanece vigente.

        Los errores al cerrar se capturan sin lanzar excepción.

        Args:
            ofertas_vigentes: Lista de ofertas vigentes a evaluar.

        Returns:
            Resultado con las cerradas, errores, candidatas a desaparición
            y fechas inválidas.
        """
        resultado = ResultadoCierre()
        fecha_hoy = self._reloj.hoy(self._zona)

        for oferta in ofertas_vigentes:
            # Las ofertas en estado sin_ficha nunca se cierran por fecha (REQ-009).
            if oferta.estado == "sin_ficha":
                continue

            fecha_fin = oferta.fecha_fin_difusion

            # Sin fecha de fin → candidata al cierre por desaparición (REQ-004).
            if not fecha_fin:
                resultado.candidatas_desaparicion.append(oferta)
                continue

            # Validar formato dd/mm/aaaa (ALT-005).
            fecha_parseada = _parsear_fecha(fecha_fin)
            if fecha_parseada is None:
                resultado.fechas_invalidas.append(oferta.codigo)
                resultado.errores.append(
                    f"Fecha de fin de difusión inválida para la oferta "
                    f"{oferta.codigo}: '{fecha_fin}'."
                )
                continue

            # Cerrar solo si la fecha de fin es estrictamente anterior a hoy.
            if fecha_parseada < fecha_hoy:
                fecha_cierre = fecha_hoy.isoformat()
                cierre = self._cliente.cerrar_oferta(
                    oferta.comunidad, oferta.codigo, fecha_cierre
                )
                if isinstance(cierre, ErrorPersistencia):
                    resultado.errores.append(
                        f"Error al cerrar la oferta {oferta.codigo}: "
                        f"{cierre.motivo}"
                    )
                elif cierre is True:
                    resultado.cerradas.append(oferta.codigo)
                elif cierre is False:
                    resultado.errores.append(
                        f"La oferta {oferta.codigo} no existe en "
                        f"persistencia y no se puede cerrar."
                    )
            # Si fecha_parseada >= fecha_hoy, la oferta permanece vigente.

        return resultado


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parsear_fecha(texto: str) -> date | None:
    """Parsea una fecha en formato ``dd/mm/aaaa``.

    Devuelve ``None`` si el formato no coincide o la fecha es imposible
    (por ejemplo, 31/02/2026).
    """
    coincidencia = _FORMATO_FECHA.match(texto)
    if coincidencia is None:
        return None
    dia = int(coincidencia.group(1))
    mes = int(coincidencia.group(2))
    anio = int(coincidencia.group(3))
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None
