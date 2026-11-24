"""Endpoints de consulta de la integridad.

El router expone bajo el prefijo ``/integridad`` la consulta del estado de la
comprobación diaria del PDF de difusión:

- ``GET /integridad/ultimo`` lee los ``.meta.json`` que ha dejado la tarea
  diaria en el árbol de PDFs, elige el día más reciente y devuelve el veredicto
  global junto con el desglose por comunidad y un booleano
  ``cierre_recomendado`` (REQ-006, REQ-009).
- ``GET /integridad/ejecuciones`` lee el índice de ejecuciones
  (``ejecuciones.json``) y devuelve las de la ventana de 30 días, de la más
  reciente a la más antigua, con los avisos de los ``.meta.json`` que
  referencian (REQ-008, REQ-009).
- ``GET /integridad/pdfs`` lista los PDFs conservados en el árbol con su fecha,
  su comunidad, su ruta relativa a la ruta base y los datos de sus metadatos
  cuando existen (REQ-002, REQ-005, REQ-009).

- La lectura se hace a través del ``AlmacenPDFs`` y del ``IndiceEjecuciones``
  guardados en ``app_state["almacen_integridad"]`` y
  ``app_state["indice_ejecuciones"]``; la fecha de "hoy" se calcula con la
  zona configurada en ``app_state["config_integridad"]`` (NFR-004).
- A igualdad de fecha máxima, el orden del desglose de ``/ultimo`` lo marca la
  última ejecución del índice que referencia ese día; si no hay índice, se
  ordena por comunidad.
- Con varias comunidades, el veredicto global es el más grave
  (``fallido`` > ``divergente`` > ``concordante``, ALT-008).
- Es de solo lectura: no escribe ningún fichero ni toca ``data/job_emcan.db``
  (SUP-002), omite los ``.meta.json`` y las entradas ilegibles sin error y no
  exige autenticación, como el resto de la API. El veredicto es informativo: no
  bloquea ni modifica los cierres de ``api-historico`` (SUP-002). No hay
  ningún canal de notificación externo (SUP-007).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones
from source.api.integridad.pdf_store import (
    VEREDICTO_CONCORDANTE,
    VEREDICTO_DIVERGENTE,
    VEREDICTO_FALLIDO,
    AlmacenPDFs,
    MetaDia,
    PdfConservado,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integridad", tags=["integridad"])

_SUFIJO_META = ".meta.json"

# Gravedad del veredicto para agregar el resultado global (ALT-008).
_GRAVEDAD = {
    VEREDICTO_CONCORDANTE: 0,
    VEREDICTO_DIVERGENTE: 1,
    VEREDICTO_FALLIDO: 2,
}


# ---------------------------------------------------------------------------
# Modelos Pydantic de salida
# ---------------------------------------------------------------------------


class VeredictoComunidad(BaseModel):
    """Veredicto de una comunidad para el día más reciente almacenado.

    Atributos:
        fecha: Día del veredicto.
        comunidad: Identificador de la comunidad.
        recuento_pdf: Ofertas extraídas del PDF, o nulo si el día falló.
        recuento_buscador: ``total_listado`` del buscador, o nulo si no se
            conoció.
        diferencia: Diferencia absoluta entre los dos recuentos.
        tolerancia_absoluta: Tolerancia absoluta aplicada, en ofertas.
        tolerancia_relativa_pct: Tolerancia relativa aplicada, en porcentaje.
        umbral_cordura: Recuento mínimo aceptado del PDF.
        veredicto: ``concordante``, ``divergente`` o ``fallido``.
    """

    fecha: date
    comunidad: str
    recuento_pdf: int | None = None
    recuento_buscador: int | None = None
    diferencia: int | None = None
    tolerancia_absoluta: int | None = None
    tolerancia_relativa_pct: int | None = None
    umbral_cordura: int | None = None
    veredicto: str


class RespuestaUltimoVeredicto(BaseModel):
    """Último veredicto de integridad y recomendación de cierre.

    Atributos:
        fecha: Día del veredicto más reciente, o nulo si aún no hay ninguno.
        veredicto_global: El más grave entre las comunidades del día, o nulo
            si no hay ningún veredicto almacenado.
        cierre_recomendado: ``True`` solo si el veredicto global es
            ``concordante`` y es de hoy; en cualquier otro caso, ``False``
            (REQ-006).
        comunidades: Desglose por comunidad del día más reciente.
    """

    fecha: date | None = None
    veredicto_global: str | None = None
    cierre_recomendado: bool
    comunidades: list[VeredictoComunidad] = Field(default_factory=list)


class ErrorComunidad(BaseModel):
    """Error de una comunidad en una ejecución de la integridad (REQ-008).

    Atributos:
        comunidad: Identificador de la comunidad afectada.
        mensaje: Motivo del fallo de esa comunidad.
    """

    comunidad: str
    mensaje: str


class EjecucionIntegridadSalida(BaseModel):
    """Una ejecución del proceso de integridad del último mes (REQ-008).

    Atributos:
        timestamp: Marca de tiempo ISO 8601 en la zona configurada.
        resultado_global: Resultado de la pasada (``ok``, ``parcial``...).
        errores_por_comunidad: Comunidades que fallaron y su mensaje.
        veredicto_agregado: Veredicto global del día, el más grave entre las
            comunidades (ALT-008).
        avisos: Avisos registrados en los ``.meta.json`` referenciados por la
            ejecución (REQ-007); los ficheros ilegibles se omiten.
    """

    timestamp: str
    resultado_global: str
    errores_por_comunidad: list[ErrorComunidad] = Field(
        default_factory=list
    )
    veredicto_agregado: str = ""
    avisos: list[dict] = Field(default_factory=list)


class PdfConservadoSalida(BaseModel):
    """Un PDF conservado con la información disponible de sus metadatos.

    Atributos:
        fecha: Día extraído del nombre ``<aaaa-mm-dd>.pdf``.
        comunidad: Comunidad del directorio del PDF.
        ruta: Ruta del PDF relativa a la ruta base del árbol
            (``<comunidad>/<aaaa-mm-dd>.pdf``); nunca una ruta absoluta del
            sistema.
        hash: SHA-256 del contenido, si existe su ``.meta.json`` (REQ-005).
        recuento_pdf: Ofertas extraídas del PDF, si existe su ``.meta.json``.
        recuento_buscador: ``total_listado`` del buscador del día, si existe
            su ``.meta.json`` y se conoció.
        veredicto: ``concordante``, ``divergente`` o ``fallido``, si existe su
            ``.meta.json``.
    """

    fecha: date
    comunidad: str
    ruta: str
    hash: str | None = None
    recuento_pdf: int | None = None
    recuento_buscador: int | None = None
    veredicto: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/ultimo",
    response_model=RespuestaUltimoVeredicto,
    summary="Último veredicto de integridad",
)
def consultar_ultimo_veredicto() -> RespuestaUltimoVeredicto:
    """Devuelve el último veredicto almacenado y si es recomendable cerrar.

    Lee los ``.meta.json`` del árbol de PDFs, se queda con la fecha máxima y
    devuelve el veredicto global (el más grave entre comunidades, ALT-008) con
    su desglose. ``cierre_recomendado`` es ``True`` solo si el veredicto
    global es ``concordante`` y corresponde a hoy en la zona configurada; un
    veredicto ``divergente`` o ``fallido``, o la ausencia de veredicto de hoy,
    lo dejan en ``False`` (REQ-006).
    """
    almacen, indice, zona = _dependencias()

    metas = _listar_metas(almacen)
    if not metas:
        return RespuestaUltimoVeredicto(cierre_recomendado=False)

    fecha = max(fecha_meta for _, fecha_meta, _ in metas)
    del_dia = _ordenar_por_indice(
        [
            (comunidad, meta)
            for comunidad, fecha_meta, meta in metas
            if fecha_meta == fecha
        ],
        indice,
        fecha,
    )

    veredicto_global = _veredicto_mas_grave(
        meta.veredicto for _, meta in del_dia
    )
    hoy = datetime.now(zona).date()

    return RespuestaUltimoVeredicto(
        fecha=fecha,
        veredicto_global=veredicto_global,
        cierre_recomendado=(
            veredicto_global == VEREDICTO_CONCORDANTE and fecha == hoy
        ),
        comunidades=[
            _a_veredicto_comunidad(comunidad, fecha, meta)
            for comunidad, meta in del_dia
        ],
    )


@router.get(
    "/ejecuciones",
    response_model=list[EjecucionIntegridadSalida],
    summary="Ejecuciones de la integridad del último mes",
)
def consultar_ejecuciones() -> list[EjecucionIntegridadSalida]:
    """Devuelve las ejecuciones de la ventana de 30 días con sus avisos.

    Lee el índice de ``app_state["indice_ejecuciones"]`` y se queda con las
    ejecuciones de los últimos 30 días, en el orden del índice (de la más
    reciente a la más antigua, REQ-009). Cada una lleva su marca de tiempo, su
    resultado global, sus errores por comunidad (REQ-008) y los avisos de los
    ``.meta.json`` que referencia; los metadatos ilegibles se omiten sin error.
    Sin índice, o con un índice ilegible, la respuesta es una lista vacía sin
    error (riesgo de metadatos corruptos de ``design@3``). Es de solo lectura
    y no envía nada por ningún canal externo (SUP-002, SUP-007).
    """
    almacen, indice, zona = _dependencias()
    if indice is None:
        return []

    hoy = datetime.now(zona).date()
    return [
        _a_ejecucion_salida(almacen, ejecucion)
        for ejecucion in indice.consultar_ultimo_mes(hoy)
    ]


@router.get(
    "/pdfs",
    response_model=list[PdfConservadoSalida],
    summary="PDFs conservados de la integridad",
)
def consultar_pdfs_conservados() -> list[PdfConservadoSalida]:
    """Devuelve los PDFs conservados con su fecha, comunidad y metadatos.

    Lista con ``AlmacenPDFs.listar_conservados()`` el árbol de PDFs de
    ``app_state["almacen_integridad"]``: un elemento por PDF, con su fecha, su
    comunidad y su ruta relativa a la ruta base (REQ-009). Cuando existe el
    ``.meta.json`` del día se añaden el hash, los recuentos y el veredicto
    (REQ-005); un PDF sin metadatos o con metadatos ilegibles se lista igual,
    sin esos datos y sin error (ALT-007). Sin directorio de PDFs la respuesta
    es una lista vacía. Refleja lo que queda tras la purga (DEC-004). Es de
    solo lectura: no escribe ni borra ningún fichero y no toca
    ``data/job_emcan.db`` (SUP-003); no exige autenticación.
    """
    almacen = _dependencias()[0]
    return [
        _a_pdf_conservado_salida(almacen, conservado)
        for conservado in almacen.listar_conservados()
    ]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _dependencias() -> tuple[
    AlmacenPDFs, IndiceEjecuciones | None, ZoneInfo
]:
    """Recupera el almacén, el índice y la zona desde ``app_state``.

    Lanza ``HTTPException(503)`` si la integridad no se inicializó, del mismo
    modo que el resto de la API cuando una feature no está disponible. El
    índice y la configuración son opcionales: sin configuración se usa la zona
    del almacén y sin índice se ordena el desglose por comunidad.
    """
    from source.api.main import app_state

    almacen = app_state.get("almacen_integridad")
    if almacen is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "La integridad no está disponible. "
                "Comprueba la configuración."
            ),
        )

    config = app_state.get("config_integridad")
    zona = config.zona if config is not None else almacen.zona
    return almacen, app_state.get("indice_ejecuciones"), zona


def _listar_metas(almacen: AlmacenPDFs) -> list[tuple[str, date, MetaDia]]:
    """Lista los ``.meta.json`` legibles del árbol con su comunidad y fecha.

    Recorre ``<base>/<comunidad>/`` y lee cada ``<aaaa-mm-dd>.meta.json`` con
    el propio almacén. Los nombres fuera del patrón se ignoran y los ficheros
    ilegibles se omiten sin error (riesgo de metadatos corruptos de
    ``design@3``); un árbol inexistente devuelve una lista vacía.
    """
    base = Path(almacen.base)
    if not base.is_dir():
        return []

    metas: list[tuple[str, date, MetaDia]] = []
    for carpeta in sorted(base.iterdir(), key=lambda ruta: ruta.name):
        if not carpeta.is_dir():
            continue
        for ruta_meta in sorted(
            carpeta.glob("*" + _SUFIJO_META), key=lambda ruta: ruta.name
        ):
            fecha = _fecha_del_nombre_meta(ruta_meta.name)
            if fecha is None:
                continue
            lectura = almacen.leer_meta(carpeta.name, fecha)
            if lectura.es_valido:
                metas.append((carpeta.name, fecha, lectura.meta))
    return metas


def _fecha_del_nombre_meta(nombre: str) -> date | None:
    """Devuelve la fecha de un nombre ``<aaaa-mm-dd>.meta.json``, o ``None``.

    Exige la forma canónica ISO de la fecha, como el almacén: nombres como
    ``2026-1-1.meta.json`` u ``otro.meta.json`` no cuentan como un día.
    """
    if not nombre.endswith(_SUFIJO_META):
        return None
    raiz = nombre[: -len(_SUFIJO_META)]
    try:
        fecha = date.fromisoformat(raiz)
    except ValueError:
        return None
    return fecha if fecha.isoformat() == raiz else None


def _ordenar_por_indice(
    metas: list[tuple[str, MetaDia]],
    indice: IndiceEjecuciones | None,
    fecha: date,
) -> list[tuple[str, MetaDia]]:
    """Ordena el desglose del día según la última ejecución del índice.

    A igualdad de fecha, la última ejecución del índice que referencia ese día
    fija el orden de sus comunidades; las que no aparezcan en ella quedan
    después por nombre. Sin índice, se ordena solo por comunidad.
    """
    orden = _orden_ultima_ejecucion(indice, fecha)
    return sorted(
        metas, key=lambda item: (orden.get(item[0], len(orden)), item[0])
    )


def _orden_ultima_ejecucion(
    indice: IndiceEjecuciones | None, fecha: date
) -> dict[str, int]:
    """Comunidades del día en el orden de la última ejecución del índice."""
    if indice is None:
        return {}

    iso = fecha.isoformat()
    for ejecucion in reversed(indice.leer().ejecuciones):
        comunidades = [
            referencia["comunidad"]
            for referencia in ejecucion.referencias
            if referencia.get("fecha") == iso
        ]
        if comunidades:
            return {
                comunidad: posicion
                for posicion, comunidad in enumerate(comunidades)
            }
    return {}


def _a_veredicto_comunidad(
    comunidad: str, fecha: date, meta: MetaDia
) -> VeredictoComunidad:
    """Traslada los metadatos del día a la fila de salida del desglose."""
    return VeredictoComunidad(
        fecha=fecha,
        comunidad=comunidad,
        recuento_pdf=meta.recuento_pdf,
        recuento_buscador=meta.recuento_buscador,
        diferencia=meta.diferencia,
        tolerancia_absoluta=meta.tolerancia_absoluta,
        tolerancia_relativa_pct=meta.tolerancia_relativa_pct,
        umbral_cordura=meta.umbral_cordura,
        veredicto=meta.veredicto,
    )


def _veredicto_mas_grave(veredictos) -> str | None:
    """Devuelve el veredicto más grave del día (ALT-008).

    El orden es ``fallido`` > ``divergente`` > ``concordante``. Los días sin
    veredicto terminado (texto vacío) no cuentan; un valor desconocido se
    trata como el más grave para no recomendar cierres con un estado que no
    se entiende.
    """
    presente = [veredicto for veredicto in veredictos if veredicto]
    if not presente:
        return None
    return max(
        presente,
        key=lambda veredicto: _GRAVEDAD.get(
            veredicto, _GRAVEDAD[VEREDICTO_FALLIDO]
        ),
    )


def _a_ejecucion_salida(
    almacen: AlmacenPDFs, ejecucion: Ejecucion
) -> EjecucionIntegridadSalida:
    """Traslada una ejecución del índice a la fila de salida (REQ-008)."""
    return EjecucionIntegridadSalida(
        timestamp=ejecucion.timestamp,
        resultado_global=ejecucion.resultado_global,
        errores_por_comunidad=[
            ErrorComunidad(
                comunidad=error["comunidad"], mensaje=error["mensaje"]
            )
            for error in ejecucion.errores_por_comunidad
        ],
        veredicto_agregado=ejecucion.veredicto_agregado,
        avisos=_avisos_de_la_ejecucion(almacen, ejecucion),
    )


def _avisos_de_la_ejecucion(
    almacen: AlmacenPDFs, ejecucion: Ejecucion
) -> list[dict]:
    """Avisos de los ``.meta.json`` que referencia la ejecución (REQ-007).

    Cada referencia ``{fecha, comunidad}`` se lee con el almacén; una fecha
    fuera del patrón ISO o unos metadatos ausentes o ilegibles se omiten sin
    error (riesgo de metadatos corruptos de ``design@3``).
    """
    avisos: list[dict] = []
    for referencia in ejecucion.referencias:
        fecha = _fecha_de_referencia(referencia)
        if fecha is None:
            continue
        lectura = almacen.leer_meta(referencia["comunidad"], fecha)
        if not lectura.es_valido:
            continue
        avisos.extend(
            _avisos_del_meta(lectura.meta, referencia["comunidad"], fecha)
        )
    return avisos


def _fecha_de_referencia(referencia: dict) -> date | None:
    """Fecha ISO 8601 de una referencia del índice, o ``None`` si no encaja."""
    texto = referencia.get("fecha")
    if not isinstance(texto, str):
        return None
    try:
        fecha = date.fromisoformat(texto)
    except ValueError:
        return None
    return fecha if fecha.isoformat() == texto else None


def _avisos_del_meta(
    meta: MetaDia, comunidad: str, fecha: date
) -> list[dict]:
    """Copia los avisos del día garantizando su fecha y su comunidad.

    Los elementos que no sean un objeto JSON se ignoran, de modo que un
    ``.meta.json`` manipulado a mano no rompe la respuesta.
    """
    avisos: list[dict] = []
    for aviso in meta.avisos:
        if not isinstance(aviso, dict):
            continue
        completo = dict(aviso)
        completo.setdefault("fecha", fecha.isoformat())
        completo.setdefault("comunidad", comunidad)
        avisos.append(completo)
    return avisos


def _a_pdf_conservado_salida(
    almacen: AlmacenPDFs, conservado: PdfConservado
) -> PdfConservadoSalida:
    """Traslada un PDF conservado a la fila de salida (REQ-009).

    La ruta se expone relativa a la ruta base del árbol, de modo que la
    respuesta no revela rutas absolutas del sistema. Los metadatos del día se
    añaden solo si existen y son legibles; si faltan, el PDF se lista igual
    con los campos de metadatos en nulo (ALT-007).
    """
    meta = conservado.meta
    return PdfConservadoSalida(
        fecha=conservado.fecha,
        comunidad=conservado.comunidad,
        ruta=_ruta_relativa_base(almacen, conservado.ruta),
        hash=meta.hash if meta is not None else None,
        recuento_pdf=meta.recuento_pdf if meta is not None else None,
        recuento_buscador=(
            meta.recuento_buscador if meta is not None else None
        ),
        veredicto=meta.veredicto if meta is not None else None,
    )


def _ruta_relativa_base(almacen: AlmacenPDFs, ruta: Path) -> str:
    """Devuelve la ruta del PDF relativa a la base, con separadores ``/``.

    Si la ruta no cuelga de la base (por ejemplo, porque se cambió la
    configuración entre la escritura y la consulta), se usa la forma
    ``<comunidad>/<nombre>`` deducida del propio fichero, que sigue siendo
    identificable y no expone rutas absolutas.
    """
    try:
        return ruta.relative_to(Path(almacen.base)).as_posix()
    except ValueError:
        return f"{ruta.parent.name}/{ruta.name}"
