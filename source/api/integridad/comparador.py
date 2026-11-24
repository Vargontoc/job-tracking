"""Comparador de recuentos del PDF y del buscador con veredicto informativo.

`ComparadorRecuentos` recibe el recuento de ofertas extraídas del PDF de
difusión, el estado publicado por el buscador (`EstadoBuscador` o su variante
no utilizable) y los umbrales configurados en `config/integridad.yaml`, y
emite un `ResultadoComparacion` con el veredicto `concordante` o `divergente`
(DEC-005):

- `concordante` si la diferencia entra en la tolerancia absoluta **o** en la
  tolerancia relativa, aplicando la más permisiva.
- `divergente` si la diferencia no cabe en ninguna de las dos (REQ-004).
- `divergente` siempre que el recuento del PDF quede por debajo del umbral de
  cordura, aunque los recuentos coincidan (ALT-004).
- `divergente` siempre que el estado del buscador no sea utilizable, con el
  motivo de la causa: error HTTP o de red, `ultima_pasada` nula o
  `error_global` no vacío (ALT-005, ALT-006).

La regla relativa se evalúa solo cuando `total_listado` es mayor que cero, de
modo que un listado vacío no provoca ninguna división por cero; en ese caso la
decisión queda en manos de la tolerancia absoluta y del umbral de cordura.

La comparación es una función pura: no lee ni escribe ficheros, no consulta el
reloj y no lanza excepciones. El resultado siempre incluye los dos recuentos
(cuando se conocen), la diferencia, las tolerancias y el umbral aplicados y el
motivo (REQ-005). El veredicto es informativo: no bloquea ni modifica los
cierres de `api-historico` (REQ-006); quien lo persiste es el `.meta.json` del
día.
"""

from dataclasses import dataclass

from source.api.integridad.buscador_client import (
    EstadoBuscador,
    EstadoBuscadorNoUtilizable,
)
from source.api.integridad.pdf_store import (
    VEREDICTO_CONCORDANTE,
    VEREDICTO_DIVERGENTE,
)


@dataclass(frozen=True)
class ResultadoComparacion:
    """Veredicto de la comparación y los valores que lo justifican.

    Atributos:
        veredicto: `concordante` o `divergente` (REQ-004).
        recuento_pdf: Ofertas extraídas del PDF de difusión.
        recuento_buscador: `total_listado` del buscador, o `None` si el estado
            no es utilizable y no hay recuento con el que comparar.
        diferencia: Diferencia absoluta entre los dos recuentos, o `None` si
            falta el recuento del buscador.
        tolerancia_absoluta: Tolerancia absoluta aplicada, en ofertas.
        tolerancia_relativa_pct: Tolerancia relativa aplicada, en porcentaje
            sobre el `total_listado`.
        umbral_cordura: Recuento mínimo aceptado del PDF.
        motivo: Descripción legible de la causa del veredicto; es la que se
            guarda en el `.meta.json` del día y en los avisos.
    """

    veredicto: str
    recuento_pdf: int
    recuento_buscador: int | None
    diferencia: int | None
    tolerancia_absoluta: int
    tolerancia_relativa_pct: int
    umbral_cordura: int
    motivo: str


class ComparadorRecuentos:
    """Compara los recuentos del PDF y del buscador con los umbrales dados.

    Args:
        tolerancia_absoluta: Diferencia absoluta máxima aceptada, en ofertas.
        tolerancia_relativa_pct: Diferencia relativa máxima aceptada, en
            porcentaje sobre el `total_listado`.
        umbral_cordura: Recuento mínimo aceptado del PDF; por debajo de él el
            veredicto es siempre `divergente`.
    """

    def __init__(
        self,
        tolerancia_absoluta: int,
        tolerancia_relativa_pct: int,
        umbral_cordura: int,
    ) -> None:
        self._tolerancia_absoluta = tolerancia_absoluta
        self._tolerancia_relativa_pct = tolerancia_relativa_pct
        self._umbral_cordura = umbral_cordura

    def comparar(
        self,
        recuento_pdf: int,
        estado_buscador: EstadoBuscador | EstadoBuscadorNoUtilizable,
    ) -> ResultadoComparacion:
        """Emite el veredicto de integridad sin lanzar excepciones.

        Args:
            recuento_pdf: Ofertas extraídas del PDF de difusión.
            estado_buscador: Estado publicado por el buscador, utilizable o
                no.

        Returns:
            `ResultadoComparacion` con el veredicto, los recuentos
            conocidos, la diferencia, los umbrales aplicados y el motivo.
        """
        por_umbral = recuento_pdf < self._umbral_cordura
        motivo_umbral = (
            f"El recuento del PDF ({recuento_pdf}) no alcanza el umbral de "
            f"cordura ({self._umbral_cordura})"
        )

        if isinstance(estado_buscador, EstadoBuscadorNoUtilizable):
            motivo = (
                "Estado del buscador no utilizable: "
                f"{estado_buscador.motivo}"
            )
            if por_umbral:
                motivo = f"{motivo_umbral}. {motivo}"
            return self._resultado(
                veredicto=VEREDICTO_DIVERGENTE,
                recuento_pdf=recuento_pdf,
                recuento_buscador=None,
                diferencia=None,
                motivo=motivo,
            )

        total_listado = estado_buscador.total_listado
        diferencia = abs(recuento_pdf - total_listado)

        if por_umbral:
            return self._resultado(
                veredicto=VEREDICTO_DIVERGENTE,
                recuento_pdf=recuento_pdf,
                recuento_buscador=total_listado,
                diferencia=diferencia,
                motivo=(
                    f"{motivo_umbral}: el veredicto es divergente con "
                    f"independencia del total_listado ({total_listado})."
                ),
            )

        if self._dentro_de_tolerancia_absoluta(diferencia):
            return self._resultado(
                veredicto=VEREDICTO_CONCORDANTE,
                recuento_pdf=recuento_pdf,
                recuento_buscador=total_listado,
                diferencia=diferencia,
                motivo=(
                    f"Diferencia de {diferencia} ofertas dentro de la "
                    f"tolerancia absoluta ({self._tolerancia_absoluta})."
                ),
            )

        if self._dentro_de_tolerancia_relativa(diferencia, total_listado):
            return self._resultado(
                veredicto=VEREDICTO_CONCORDANTE,
                recuento_pdf=recuento_pdf,
                recuento_buscador=total_listado,
                diferencia=diferencia,
                motivo=(
                    f"Diferencia de {diferencia} ofertas dentro de la "
                    f"tolerancia relativa ({self._tolerancia_relativa_pct} % "
                    f"sobre un total_listado de {total_listado})."
                ),
            )

        return self._resultado(
            veredicto=VEREDICTO_DIVERGENTE,
            recuento_pdf=recuento_pdf,
            recuento_buscador=total_listado,
            diferencia=diferencia,
            motivo=(
                f"Diferencia de {diferencia} ofertas fuera de la tolerancia "
                f"absoluta ({self._tolerancia_absoluta}) y de la tolerancia "
                f"relativa ({self._tolerancia_relativa_pct} % sobre un "
                f"total_listado de {total_listado})."
            ),
        )

    def _dentro_de_tolerancia_absoluta(self, diferencia: int) -> bool:
        """Indica si la diferencia cabe en la tolerancia absoluta."""
        return diferencia <= self._tolerancia_absoluta

    def _dentro_de_tolerancia_relativa(
        self,
        diferencia: int,
        total_listado: int,
    ) -> bool:
        """Indica si la diferencia cabe en la tolerancia relativa.

        Se compara con enteros para no introducir redondeos: la regla solo
        aplica si el `total_listado` es mayor que cero, de modo que un listado
        vacío no divide por cero.
        """
        if total_listado <= 0:
            return False
        return diferencia * 100 <= self._tolerancia_relativa_pct * total_listado

    def _resultado(
        self,
        veredicto: str,
        recuento_pdf: int,
        recuento_buscador: int | None,
        diferencia: int | None,
        motivo: str,
    ) -> ResultadoComparacion:
        """Compone el resultado con los umbrales de este comparador."""
        return ResultadoComparacion(
            veredicto=veredicto,
            recuento_pdf=recuento_pdf,
            recuento_buscador=recuento_buscador,
            diferencia=diferencia,
            tolerancia_absoluta=self._tolerancia_absoluta,
            tolerancia_relativa_pct=self._tolerancia_relativa_pct,
            umbral_cordura=self._umbral_cordura,
            motivo=motivo,
        )
