"""Guardián de recuento del listado.

Compara el recuento actual del listado con el recuento anterior de la serie
propia. Si la caída supera el umbral configurado o el actual es inferior al
recuento mínimo, devuelve «no permitido» y registra la abstención. Sin
recuento anterior, registra el actual y aplaza el cierre por desaparición
(ALT-010). No escribe en la base de datos de ofertas (SUP-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.presencia_repository import RepositorioPresencia


# ---------------------------------------------------------------------------
# Resultado de la validación
# ---------------------------------------------------------------------------


@dataclass
class ResultadoValidacion:
    """Resultado de la validación del guardián de recuento.

    Atributos:
        permitido: ``True`` si el cierre por desaparición puede proceder.
        motivo_abstencion: Motivo de la abstención cuando ``permitido`` es
            ``False``; ``None`` cuando se permite el cierre.
    """

    permitido: bool
    motivo_abstencion: Optional[str] = None


# ---------------------------------------------------------------------------
# Guardián
# ---------------------------------------------------------------------------


class GuardianRecuento:
    """Guardián que valida el recuento del listado antes de permitir cierres.

    Recibe los dos repositorios de estado propio (presencia/serie de
    recuentos y abstenciones) y los umbrales configurados. Cada llamada a
    :meth:`validar` compara el recuento actual con el último registrado,
    aplica las dos reglas de abstención (umbral de caída y recuento mínimo)
    y, en caso de abstención, persiste el registro correspondiente.
    """

    def __init__(
        self,
        repositorio_presencia: RepositorioPresencia,
        abstenciones: RepositorioAbstenciones,
        umbral_caida_pct: int,
        recuento_minimo: int,
    ) -> None:
        """Inicializa el guardián.

        Args:
            repositorio_presencia: Repositorio de presencia y serie de
                recuentos del histórico.
            abstenciones: Repositorio de abstenciones de cierre.
            umbral_caida_pct: Porcentaje de caída que provoca abstención
                (REQ-008).
            recuento_minimo: Recuento mínimo para permitir cierres
                (REQ-008).
        """
        self._repositorio_presencia = repositorio_presencia
        self._abstenciones = abstenciones
        self._umbral_caida_pct = umbral_caida_pct
        self._recuento_minimo = recuento_minimo

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def validar(
        self, recuento_actual: int, timestamp: str
    ) -> ResultadoValidacion:
        """Valida el recuento actual contra el histórico de la serie propia.

        Reglas (REQ-008, ALT-002, ALT-010):

        1. Sin recuento anterior: se registra el actual y se aplaza el
           cierre por desaparición.
        2. Si ``recuento_actual < recuento_minimo``: abstención.
        3. Si la caída porcentual ``(anterior - actual) / anterior * 100``
           supera ``umbral_caida_pct``: abstención.
        4. En cualquier otro caso: se permite el cierre.

        El recuento actual se registra siempre en la serie. Si se produce
        abstención, también se registra en el repositorio de abstenciones.

        Args:
            recuento_actual: Total de ofertas del listado en la pasada
                actual.
            timestamp: Marca de tiempo ISO 8601 de la pasada.

        Returns:
            :class:`ResultadoValidacion` con ``permitido=True`` si el cierre
            puede proceder.
        """
        ultimo = self._repositorio_presencia.obtener_ultimo_recuento()

        # Caso sin histórico: registrar y aplazar (ALT-010).
        if ultimo is None:
            self._repositorio_presencia.registrar_recuento(
                recuento_actual, timestamp
            )
            return ResultadoValidacion(
                permitido=False,
                motivo_abstencion=(
                    "Sin recuento anterior: se aplaza el cierre por "
                    "desaparición"
                ),
            )

        recuento_anterior = ultimo[0]

        # Registrar siempre el recuento actual en la serie.
        self._repositorio_presencia.registrar_recuento(
            recuento_actual, timestamp
        )

        # Regla 1: recuento mínimo (REQ-008).
        if recuento_actual < self._recuento_minimo:
            motivo = (
                f"Recuento actual {recuento_actual} inferior al mínimo "
                f"{self._recuento_minimo}"
            )
            self._registrar_abstencion(
                motivo, timestamp, recuento_anterior, recuento_actual
            )
            return ResultadoValidacion(
                permitido=False, motivo_abstencion=motivo
            )

        # Regla 2: caída porcentual (REQ-008, ALT-002).
        if recuento_anterior > 0:
            caida_pct = (
                (recuento_anterior - recuento_actual) / recuento_anterior * 100
            )
        else:
            caida_pct = 0.0

        if caida_pct > self._umbral_caida_pct:
            motivo = (
                f"Caída del {caida_pct:.1f}% supera el umbral del "
                f"{self._umbral_caida_pct}%"
            )
            self._registrar_abstencion(
                motivo, timestamp, recuento_anterior, recuento_actual
            )
            return ResultadoValidacion(
                permitido=False, motivo_abstencion=motivo
            )

        # Sin motivo de abstención: permitido.
        return ResultadoValidacion(permitido=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _registrar_abstencion(
        self,
        motivo: str,
        timestamp: str,
        recuento_anterior: int,
        recuento_actual: int,
    ) -> None:
        """Persiste la abstención en el repositorio de abstenciones."""
        umbral_aplicado = (
            f"caida>{self._umbral_caida_pct}% o "
            f"minimo<{self._recuento_minimo}"
        )
        self._abstenciones.registrar(
            motivo=motivo,
            timestamp=timestamp,
            recuento_anterior=recuento_anterior,
            recuento_actual=recuento_actual,
            umbral_aplicado=umbral_aplicado,
        )
