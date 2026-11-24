"""Almacén de avisos de fallo y divergencia en el .meta.json del día.

Cada aviso es un registro consultable que se **anexa** a la lista `avisos` del
`.meta.json` del día de esa comunidad, reescribiéndolo con la escritura
atómica de `pdf-store` (DEC-001). Así cada aviso queda asociado a su día y se
consulta por rango de fechas leyendo los metadatos de esos días (REQ-007,
REQ-009).

- Aviso de divergencia: fecha, comunidad, recuento del PDF, `total_listado`,
  diferencia, tolerancia absoluta, tolerancia relativa, umbral de cordura y
  motivo (REQ-007).
- Aviso de fallo: fecha, comunidad y motivo (ALT-003); cubre también el fallo
  de parseo del PDF, que se conserva con el día en `fallido` (DEC-002).

Los avisos son registros internos: no se envía nada por Telegram ni por ningún
otro canal externo (SUP-007) y no se usa SQLite (DEC-001). Si el día no tiene
un `.meta.json` legible, registrar un aviso lanza `ErrorAvisoIntegridad`: no se
inventa un día válido ni se crea un fichero de metadatos a medias.
"""

import logging
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from source.api.integridad.comparador import ResultadoComparacion
from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia

logger = logging.getLogger(__name__)

# Tipos de aviso que se guardan en la lista `avisos` del `.meta.json`.
TIPO_DIVERGENCIA = "divergencia"
TIPO_FALLO = "fallo"

_SUFIJO_META = ".meta.json"


class ErrorAvisoIntegridad(Exception):
    """Indica que el día no tiene metadatos legibles donde anexar el aviso.

    Es el error propio del almacén: sin un `.meta.json` legible no hay dónde
    registrar el aviso y no se crea un día válido inventado. Quien llama
    recibe un resultado controlado y distinguible en lugar de una excepción
    del sistema de ficheros.
    """


class AlmacenAvisos:
    """Registra y consulta los avisos de integridad del árbol de PDFs.

    Args:
        almacen_pdf: almacén de PDFs y metadatos del día (`pdf-store`), que
            aporta las rutas, la escritura atómica y la lectura controlada de
            los `.meta.json`.
    """

    def __init__(self, almacen_pdf: AlmacenPDFs) -> None:
        self._almacen = almacen_pdf

    def registrar_divergencia(
        self,
        comunidad: str,
        fecha: date,
        resultado: ResultadoComparacion,
    ) -> dict:
        """Anexa al día un aviso de divergencia y devuelve el aviso escrito.

        El aviso lleva fecha, comunidad, recuento del PDF, `total_listado`,
        diferencia, tolerancias y umbral aplicados y motivo (REQ-007).

        Raises:
            ErrorAvisoIntegridad: si el día no tiene un `.meta.json` legible.
        """
        aviso = {
            "tipo": TIPO_DIVERGENCIA,
            "fecha": _nombre_dia(fecha),
            "comunidad": comunidad,
            "recuento_pdf": resultado.recuento_pdf,
            "total_listado": resultado.recuento_buscador,
            "diferencia": resultado.diferencia,
            "tolerancia_absoluta": resultado.tolerancia_absoluta,
            "tolerancia_relativa_pct": resultado.tolerancia_relativa_pct,
            "umbral_cordura": resultado.umbral_cordura,
            "motivo": resultado.motivo,
        }
        return self._anexar(comunidad, fecha, aviso)

    def registrar_fallo(
        self,
        comunidad: str,
        fecha: date,
        motivo: str,
    ) -> dict:
        """Anexa al día un aviso de fallo y devuelve el aviso escrito.

        Se usa tanto para un fallo de descarga (ALT-003) como para un fallo de
        parseo (DEC-002): el aviso lleva fecha, comunidad afectada y motivo.

        Raises:
            ErrorAvisoIntegridad: si el día no tiene un `.meta.json` legible.
        """
        aviso = {
            "tipo": TIPO_FALLO,
            "fecha": _nombre_dia(fecha),
            "comunidad": comunidad,
            "motivo": motivo,
        }
        return self._anexar(comunidad, fecha, aviso)

    def consultar(self, desde: date, hasta: date) -> list[dict]:
        """Devuelve los avisos de los días del rango, extremos incluidos.

        Recorre `<base>/<comunidad>/` y lee los `.meta.json` cuya fecha, tomada
        del nombre `<aaaa-mm-dd>.meta.json`, cae en `[desde, hasta]`. Un
        `.meta.json` ausente o ilegible se omite sin error. Cada aviso
        devuelto incluye siempre su fecha y su comunidad; la lista se ordena
        por fecha y comunidad (REQ-009).
        """
        inicio = _solo_fecha(desde)
        fin = _solo_fecha(hasta)
        if fin < inicio or not self._almacen.base.is_dir():
            return []

        avisos: list[dict] = []
        for carpeta in sorted(self._almacen.base.iterdir()):
            if not carpeta.is_dir():
                continue
            avisos.extend(self._consultar_comunidad(carpeta, inicio, fin))
        return sorted(
            avisos, key=lambda aviso: (aviso["fecha"], aviso["comunidad"])
        )

    def _consultar_comunidad(
        self, carpeta: Path, inicio: date, fin: date
    ) -> list[dict]:
        """Avisos de los días del rango en un directorio de comunidad."""
        avisos: list[dict] = []
        for ruta_meta in sorted(carpeta.glob("*" + _SUFIJO_META)):
            fecha = _fecha_del_nombre_meta(ruta_meta.name)
            if fecha is None or not inicio <= fecha <= fin:
                continue
            lectura = self._almacen.leer_meta(carpeta.name, fecha)
            if not lectura.es_valido:
                continue
            avisos.extend(
                _avisos_del_dia(lectura.meta, carpeta.name, fecha)
            )
        return avisos

    def _anexar(self, comunidad: str, fecha: date, aviso: dict) -> dict:
        """Anexa `aviso` al `.meta.json` del día y lo reescribe de forma atómica."""
        lectura = self._almacen.leer_meta(comunidad, fecha)
        if not lectura.es_valido:
            motivo = f": {lectura.motivo}" if lectura.motivo else ""
            raise ErrorAvisoIntegridad(
                "No hay metadatos legibles para registrar el aviso de "
                f"{comunidad}/{_nombre_dia(fecha)} "
                f"(estado {lectura.estado}){motivo}"
            )

        meta = replace(
            lectura.meta, avisos=[*lectura.meta.avisos, aviso]
        )
        self._almacen.escribir_meta(comunidad, fecha, meta)
        logger.info(
            "Aviso %s registrado en %s/%s",
            aviso["tipo"],
            comunidad,
            _nombre_dia(fecha),
        )
        return aviso


def _avisos_del_dia(
    meta: MetaDia, comunidad: str, fecha: date
) -> list[dict]:
    """Copia los avisos del día garantizando su fecha y su comunidad."""
    avisos: list[dict] = []
    for aviso in meta.avisos:
        if not isinstance(aviso, dict):
            continue
        completo = dict(aviso)
        completo.setdefault("fecha", _nombre_dia(fecha))
        completo.setdefault("comunidad", comunidad)
        avisos.append(completo)
    return avisos


def _solo_fecha(valor: date) -> date:
    """Reduce un `datetime` a su fecha para comparar con la del nombre."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor


def _nombre_dia(fecha: date) -> str:
    """Nombre `<aaaa-mm-dd>` del día; un `datetime` se reduce a su fecha."""
    return _solo_fecha(fecha).isoformat()


def _fecha_del_nombre_meta(nombre: str) -> date | None:
    """Devuelve la fecha de un nombre `<aaaa-mm-dd>.meta.json`, o `None`.

    Exige el patrón exacto (forma canónica ISO), de modo que nombres como
    `2026-1-1.meta.json` u otros sufijos se ignoren.
    """
    if not nombre.endswith(_SUFIJO_META):
        return None
    raiz = nombre[: -len(_SUFIJO_META)]
    try:
        fecha = date.fromisoformat(raiz)
    except ValueError:
        return None
    return fecha if fecha.isoformat() == raiz else None
