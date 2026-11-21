"""Importador idempotente de códigos vistos desde data/seen_codes.json."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoImportacion:
    """Resultado de la importación de códigos vistos.

    Attributes:
        importados: Número de códigos nuevos importados.
        existentes: Número de códigos que ya existían en la base de datos.
    """

    importados: int
    existentes: int


# ---------------------------------------------------------------------------
# Función pública
# ---------------------------------------------------------------------------

def importar_codigos_vistos(
    conexion,
    ruta_json: str | Path,
) -> ResultadoImportacion:
    """Importa códigos vistos desde un fichero JSON a la base de datos.

    Lee el fichero JSON como lista plana de códigos de texto y, por cada
    código que no exista en la base de datos, crea un registro con
    comunidad ``Cantabria``, estado ``sin_ficha`` y el resto de campos
    vacíos/nulos. No modifica nunca el fichero de origen.

    Si el fichero no existe, se registra y se continúa sin fallar.
    Si el fichero tiene JSON inválido o no es una lista, se registra como
    error y se continúa sin modificar la base de datos.

    Es idempotente: repetir la importación no crea duplicados.

    Args:
        conexion: Conexión SQLite abierta (del módulo connection).
        ruta_json: Ruta al fichero JSON de códigos vistos.

    Returns:
        ResultadoImportacion con el número de códigos importados y existentes.
    """
    ruta = Path(ruta_json)

    # Comprobar existencia del fichero (ALT-003)
    if not ruta.exists():
        logger.info(
            "Fichero de códigos vistos ausente: %s. Importación omitida.",
            ruta,
        )
        return ResultadoImportacion(importados=0, existentes=0)

    # Leer y parsear JSON
    try:
        contenido = ruta.read_text(encoding="utf-8")
        datos = json.loads(contenido)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.error(
            "Error al leer o parsear %s: %s. Importación omitida.",
            ruta,
            exc,
        )
        return ResultadoImportacion(importados=0, existentes=0)

    # Validar que es una lista
    if not isinstance(datos, list):
        logger.error(
            "El fichero %s no contiene una lista JSON. Importación omitida.",
            ruta,
        )
        return ResultadoImportacion(importados=0, existentes=0)

    repositorio = RepositorioOfertas(conexion)
    importados = 0
    existentes = 0

    for codigo in datos:
        # Validar que el código es una cadena
        if not isinstance(codigo, str):
            logger.warning("Código no es cadena, se omite: %r", codigo)
            continue

        resultado = repositorio.consultar_por_clave("Cantabria", codigo)
        if resultado.encontrada:
            existentes += 1
        else:
            oferta = Oferta(
                comunidad="Cantabria",
                codigo=codigo,
                estado=EstadoOferta.SIN_FICHA,
            )
            repositorio.crear_o_actualizar(oferta)
            importados += 1

    logger.info(
        "Importación de códigos vistos completada: %d importados, %d existentes.",
        importados,
        existentes,
    )
    return ResultadoImportacion(importados=importados, existentes=existentes)
