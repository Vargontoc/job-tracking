"""Ensamblado de la respuesta agregada por comunidad."""

from dataclasses import asdict, replace
from datetime import UTC, datetime

from source.api.models import ResultadoPorComunidad


def ensamblar_respuesta(
    resultados: list[ResultadoPorComunidad],
) -> dict[str, object]:
    """Convierte los resultados por comunidad en el cuerpo de respuesta."""
    comunidades = [_serializar_resultado(resultado) for resultado in resultados]
    total_ofertas = sum(
        len(resultado.ofertas)
        for resultado in resultados
        if resultado.estado == "ok"
    )

    return {
        "metadatos": {
            "comunidades_procesadas": len(resultados),
            "total_ofertas": total_ofertas,
            "timestamp": datetime.now(UTC).isoformat(),
        },
        "resultados": comunidades,
    }


def _serializar_resultado(
    resultado: ResultadoPorComunidad,
) -> dict[str, object]:
    comunidad = {
        "comunidad": resultado.comunidad,
        "estado": resultado.estado,
    }
    if resultado.estado == "error":
        comunidad["error"] = resultado.mensaje_error
        return comunidad

    comunidad["ofertas"] = [
        asdict(replace(oferta, comunidad=resultado.comunidad))
        for oferta in resultado.ofertas
    ]
    return comunidad
