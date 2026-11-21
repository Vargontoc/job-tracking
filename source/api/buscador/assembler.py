"""Ensamblado del resultado estructurado de una pasada del rastreador."""

from datetime import datetime

from source.api.buscador.models import (
    ErrorOferta,
    OfertaBuscador,
    ResultadoPasada,
)


def ensamblar_resultado_pasada(
    timestamp_inicio: str,
    timestamp_fin: str,
    ofertas_nuevas: list[OfertaBuscador],
    errores_por_oferta: list[ErrorOferta],
    error_global: str,
    total_listado: int,
    comunidad: str = "Cantabria",
) -> ResultadoPasada:
    """Construye el resultado estructurado de una pasada del rastreador.

    Si existe un error global, la lista de ofertas nuevas se deja vacía.
    Si no hay error global, se incluyen las ofertas nuevas y los errores
    por oferta.

    Args:
        timestamp_inicio: Marca de tiempo ISO del inicio de la pasada.
        timestamp_fin: Marca de tiempo ISO del fin de la pasada.
        ofertas_nuevas: Lista de ofertas nuevas parseadas correctamente.
        errores_por_oferta: Lista de errores por oferta individual.
        error_global: Error que impidió completar la pasada (vacío si no hay).
        total_listado: Total de ofertas encontradas en el listado.
        comunidad: Comunidad rastreada (por defecto "Cantabria").

    Returns:
        ResultadoPasada con los datos de la pasada.
    """
    # Si hay error global, no incluir ofertas
    if error_global:
        ofertas_finales: list[OfertaBuscador] = []
    else:
        ofertas_finales = ofertas_nuevas

    return ResultadoPasada(
        timestamp=timestamp_inicio,
        comunidad=comunidad,
        total_listado=total_listado,
        error_global=error_global,
        errores_por_oferta=errores_por_oferta,
        ofertas_nuevas=ofertas_finales,
    )
