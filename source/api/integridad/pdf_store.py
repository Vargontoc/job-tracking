"""Almacén en disco de los PDFs de difusión y de sus metadatos .meta.json.

El árbol es `<base>/<comunidad>/<aaaa-mm-dd>.pdf` con su fichero de metadatos
asociado `<base>/<comunidad>/<aaaa-mm-dd>.meta.json` (SUP-003). Todas las
escrituras son atómicas: fichero temporal en el mismo directorio y `replace`
al nombre definitivo, de modo que nunca se ve un nombre definitivo con el
contenido a medias (DEC-001). El `.meta.json` guarda los campos del modelo
lógico MetaDia (REQ-005) y la marca de tiempo se genera en la zona horaria
configurada (NFR-004).

Cuando existe el PDF del día pero falta su `.meta.json` (escritura
interrumpida) el día está incompleto: `detectar_huerfano` lo informa y
`regenerar_meta` recalcula el hash desde el PDF y escribe los metadatos sin
volver a escribir el PDF (ALT-007). `listar_conservados` devuelve un elemento
por cada PDF conservado con su fecha, su comunidad, su ruta y sus metadatos
cuando existen (REQ-009).

No se usa SQLite: la fuente de verdad del día son estos ficheros, no hay
ninguna base de datos propia ni conexión que abrir (DEC-001).
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Veredictos posibles del día (REQ-004).
VEREDICTO_CONCORDANTE = "concordante"
VEREDICTO_DIVERGENTE = "divergente"
VEREDICTO_FALLIDO = "fallido"

# Estados posibles del resultado de `leer_meta`.
ESTADO_META_OK = "ok"
ESTADO_META_AUSENTE = "ausente"
ESTADO_META_ILEGIBLE = "ilegible"

# Campos del modelo lógico MetaDia, en el orden en que se escriben (REQ-005).
CAMPOS_META = (
    "hash",
    "recuento_pdf",
    "recuento_buscador",
    "diferencia",
    "tolerancia_absoluta",
    "tolerancia_relativa_pct",
    "umbral_cordura",
    "veredicto",
    "errores",
    "avisos",
    "timestamp",
)

_SUFIJO_PDF = ".pdf"
_SUFIJO_META = ".meta.json"
_SUFIJO_TEMPORAL = ".tmp"


class ErrorPDFAusente(Exception):
    """Indica que el PDF del día no existe o no se puede leer.

    Es el error propio de `regenerar_meta`: sin el PDF no hay nada de donde
    recalcular el hash, de modo que quien llama recibe un error controlado y
    distinguible en lugar de una excepción del sistema de ficheros.
    """


@dataclass
class MetaDia:
    """Metadatos del día guardados en `<aaaa-mm-dd>.meta.json` (REQ-005).

    Atributos:
        hash: SHA-256 del contenido del PDF (DEC-003).
        recuento_pdf: Ofertas extraídas del PDF.
        recuento_buscador: `total_listado` publicado por el buscador.
        diferencia: Diferencia absoluta entre los dos recuentos.
        tolerancia_absoluta: Tolerancia absoluta aplicada, en ofertas.
        tolerancia_relativa_pct: Tolerancia relativa aplicada, en porcentaje.
        umbral_cordura: Recuento mínimo aceptado del PDF.
        veredicto: `concordante`, `divergente` o `fallido`; vacío mientras el
            día no se ha completado.
        errores: Mensajes de error del día (descarga, parseo...).
        avisos: Avisos registrados del día (divergencias y fallos).
        timestamp: Marca de tiempo ISO 8601 en la zona horaria configurada.
    """

    hash: str = ""
    recuento_pdf: int | None = None
    recuento_buscador: int | None = None
    diferencia: int | None = None
    tolerancia_absoluta: int | None = None
    tolerancia_relativa_pct: int | None = None
    umbral_cordura: int | None = None
    veredicto: str = ""
    errores: list[str] = field(default_factory=list)
    avisos: list[dict] = field(default_factory=list)
    timestamp: str = ""

    def a_diccionario(self) -> dict:
        """Devuelve el contenido del `.meta.json` como diccionario JSON."""
        return {
            "hash": self.hash,
            "recuento_pdf": self.recuento_pdf,
            "recuento_buscador": self.recuento_buscador,
            "diferencia": self.diferencia,
            "tolerancia_absoluta": self.tolerancia_absoluta,
            "tolerancia_relativa_pct": self.tolerancia_relativa_pct,
            "umbral_cordura": self.umbral_cordura,
            "veredicto": self.veredicto,
            "errores": list(self.errores),
            "avisos": list(self.avisos),
            "timestamp": self.timestamp,
        }

    @classmethod
    def desde_diccionario(cls, datos: object) -> "MetaDia":
        """Reconstruye un MetaDia desde el contenido JSON del `.meta.json`.

        Raises:
            ValueError: si el contenido no tiene la forma del modelo, para que
                quien llama no lo confunda con un día válido.
        """
        if not isinstance(datos, dict):
            raise ValueError("el .meta.json no contiene un objeto JSON")
        faltan = [campo for campo in CAMPOS_META if campo not in datos]
        if faltan:
            raise ValueError(
                "faltan campos en el .meta.json: " + ", ".join(faltan)
            )
        return cls(
            hash=_texto(datos["hash"], "hash"),
            recuento_pdf=_entero(datos["recuento_pdf"], "recuento_pdf"),
            recuento_buscador=_entero(
                datos["recuento_buscador"], "recuento_buscador"
            ),
            diferencia=_entero(datos["diferencia"], "diferencia"),
            tolerancia_absoluta=_entero(
                datos["tolerancia_absoluta"], "tolerancia_absoluta"
            ),
            tolerancia_relativa_pct=_entero(
                datos["tolerancia_relativa_pct"], "tolerancia_relativa_pct"
            ),
            umbral_cordura=_entero(datos["umbral_cordura"], "umbral_cordura"),
            veredicto=_texto(datos["veredicto"], "veredicto"),
            errores=_lista(datos["errores"], "errores"),
            avisos=_lista(datos["avisos"], "avisos"),
            timestamp=_texto(datos["timestamp"], "timestamp"),
        )


@dataclass
class LecturaMeta:
    """Resultado controlado de la lectura del `.meta.json` de un día.

    `estado` es `ok` (metadatos legibles en `meta`), `ausente` (no existe el
    fichero) o `ilegible` (no es JSON válido o no tiene la forma del modelo).
    Un `.meta.json` ilegible nunca se devuelve como día válido y se deja
    intacto en disco.
    """

    estado: str
    meta: MetaDia | None = None
    motivo: str = ""

    @property
    def es_valido(self) -> bool:
        """Indica si el día tiene metadatos legibles."""
        return self.estado == ESTADO_META_OK and self.meta is not None


@dataclass
class PdfConservado:
    """Un PDF conservado en el árbol, con sus metadatos si existen.

    Atributos:
        comunidad: Nombre del directorio de la comunidad.
        fecha: Día extraído del nombre `<aaaa-mm-dd>.pdf`.
        ruta: Ruta del PDF conservado.
        meta: Metadatos del día, o `None` si falta el `.meta.json` (día
            incompleto) o no es legible.
    """

    comunidad: str
    fecha: date
    ruta: Path
    meta: MetaDia | None = None


class AlmacenPDFs:
    """Gestiona el árbol de PDFs y de metadatos por comunidad y fecha.

    Args:
        base: Ruta base del árbol de PDFs, absoluta o relativa a la raíz del
            proyecto.
        zona_horaria: Zona IANA (o `ZoneInfo`) con la que se genera la marca
            de tiempo de los metadatos (NFR-004).
    """

    def __init__(
        self,
        base: str | Path,
        zona_horaria: str | ZoneInfo = "Europe/Madrid",
    ) -> None:
        self.base = Path(base)
        self.zona = (
            zona_horaria
            if isinstance(zona_horaria, ZoneInfo)
            else ZoneInfo(zona_horaria)
        )

    def ruta_pdf(self, comunidad: str, fecha: date) -> Path:
        """Devuelve `<base>/<comunidad>/<aaaa-mm-dd>.pdf`."""
        return self.base / comunidad / f"{_nombre_dia(fecha)}{_SUFIJO_PDF}"

    def ruta_meta(self, comunidad: str, fecha: date) -> Path:
        """Devuelve `<base>/<comunidad>/<aaaa-mm-dd>.meta.json`."""
        return self.base / comunidad / f"{_nombre_dia(fecha)}{_SUFIJO_META}"

    def guardar_pdf(
        self,
        comunidad: str,
        fecha: date,
        contenido: bytes,
        meta: MetaDia | None = None,
    ) -> MetaDia:
        """Guarda el PDF del día y su `.meta.json` de forma atómica.

        Crea el directorio de la comunidad si no existe y escribe el PDF con
        un temporal y `replace`. El hash SHA-256 y la marca de tiempo se
        calculan siempre aquí sobre el contenido y la zona configurada; el
        resto de campos se copian de `meta` (vacíos si no se indica), de modo
        que el día puede completarse después con `escribir_meta`.

        Returns:
            El `MetaDia` resultante, ya escrito junto al PDF.
        """
        ruta_pdf = self.ruta_pdf(comunidad, fecha)
        ruta_pdf.parent.mkdir(parents=True, exist_ok=True)
        _escribir_atomico(ruta_pdf, contenido)
        logger.info("PDF guardado en %s (%d bytes)", ruta_pdf, len(contenido))

        completo = replace(
            meta if meta is not None else MetaDia(),
            hash=_hash_sha256(contenido),
            timestamp=self._ahora(),
        )
        return self.escribir_meta(comunidad, fecha, completo)

    def escribir_meta(
        self, comunidad: str, fecha: date, meta: MetaDia
    ) -> MetaDia:
        """Escribe el `.meta.json` del día de forma atómica (DEC-001).

        Si el `meta` recibido no trae marca de tiempo, se genera aquí con la
        zona configurada (NFR-004); el resto de campos se escriben tal cual.
        """
        if not meta.timestamp:
            meta = replace(meta, timestamp=self._ahora())
        ruta_meta = self.ruta_meta(comunidad, fecha)
        ruta_meta.parent.mkdir(parents=True, exist_ok=True)
        texto = json.dumps(meta.a_diccionario(), ensure_ascii=False, indent=2)
        _escribir_atomico(ruta_meta, (texto + "\n").encode("utf-8"))
        return meta

    def leer_meta(self, comunidad: str, fecha: date) -> LecturaMeta:
        """Lee el `.meta.json` del día con un resultado controlado.

        Si no existe devuelve estado `ausente`; si existe pero no es JSON
        válido o no tiene la forma del modelo, estado `ilegible` con el motivo
        y el fichero intacto (riesgo de metadatos corruptos de `design@3`).
        """
        ruta_meta = self.ruta_meta(comunidad, fecha)
        if not ruta_meta.is_file():
            return LecturaMeta(estado=ESTADO_META_AUSENTE)

        try:
            datos = json.loads(ruta_meta.read_text(encoding="utf-8"))
            meta = MetaDia.desde_diccionario(datos)
        except (OSError, TypeError, ValueError) as error:
            logger.warning("Metadatos ilegibles en %s: %s", ruta_meta, error)
            return LecturaMeta(estado=ESTADO_META_ILEGIBLE, motivo=str(error))

        return LecturaMeta(estado=ESTADO_META_OK, meta=meta)

    def escribir_fallido(
        self, comunidad: str, fecha: date, motivo: str
    ) -> MetaDia:
        """Escribe el `.meta.json` del día en estado `fallido`, sin PDF.

        Se usa cuando la descarga falla (ALT-003): el día queda registrado con
        el motivo en `errores` y no se escribe ningún PDF.
        """
        meta = MetaDia(
            veredicto=VEREDICTO_FALLIDO,
            errores=[motivo],
            timestamp=self._ahora(),
        )
        return self.escribir_meta(comunidad, fecha, meta)

    def detectar_huerfano(self, comunidad: str, fecha: date) -> bool:
        """Indica si el día está incompleto: hay PDF y no hay `.meta.json`.

        Es el caso de una escritura interrumpida (ALT-007): el PDF existe y
        sus metadatos no, de modo que la tarea diaria puede reprocesarlo con
        `regenerar_meta`.
        """
        return (
            self.ruta_pdf(comunidad, fecha).is_file()
            and not self.ruta_meta(comunidad, fecha).is_file()
        )

    def regenerar_meta(
        self, comunidad: str, fecha: date, meta: MetaDia
    ) -> MetaDia:
        """Escribe el `.meta.json` del día recalculando el hash desde el PDF.

        No vuelve a escribir el PDF: solo lee su contenido para calcular el
        SHA-256 (DEC-003) y escribe los metadatos con los campos recibidos y
        la marca de tiempo de la zona configurada (NFR-004). Se usa cuando el
        PDF existe pero su `.meta.json` no (ALT-007).

        Raises:
            ErrorPDFAusente: si el PDF del día no existe o no se puede leer.
        """
        ruta_pdf = self.ruta_pdf(comunidad, fecha)
        try:
            contenido = ruta_pdf.read_bytes()
        except OSError as error:
            raise ErrorPDFAusente(
                "No se puede leer el PDF del día "
                f"{comunidad}/{ruta_pdf.name}: {error}"
            ) from error

        completo = replace(
            meta, hash=_hash_sha256(contenido), timestamp=self._ahora()
        )
        return self.escribir_meta(comunidad, fecha, completo)

    def listar_conservados(self) -> list[PdfConservado]:
        """Lista los PDFs conservados del árbol con sus metadatos disponibles.

        Devuelve un `PdfConservado` por cada PDF del árbol (REQ-009). Un
        `.meta.json` ilegible se omite en la parte de metadatos (`meta` queda
        en `None`) pero no excluye el PDF; un nombre que no sigue el patrón
        `<aaaa-mm-dd>` se ignora; y una ruta base, un directorio de comunidad
        vacío o inexistente no produce error.
        """
        if not self.base.is_dir():
            return []

        conservados: list[PdfConservado] = []
        for carpeta in self.base.iterdir():
            if not carpeta.is_dir():
                continue
            conservados.extend(self._listar_comunidad(carpeta))
        return sorted(
            conservados, key=lambda item: (item.comunidad, item.fecha)
        )

    def _listar_comunidad(self, carpeta: Path) -> list[PdfConservado]:
        """Lista los PDFs de un directorio de comunidad ya existente."""
        conservados: list[PdfConservado] = []
        for ruta_pdf in carpeta.glob("*" + _SUFIJO_PDF):
            fecha = _fecha_del_nombre_pdf(ruta_pdf.name)
            if fecha is None:
                continue
            lectura = self.leer_meta(carpeta.name, fecha)
            conservados.append(
                PdfConservado(
                    comunidad=carpeta.name,
                    fecha=fecha,
                    ruta=ruta_pdf,
                    meta=lectura.meta if lectura.es_valido else None,
                )
            )
        return conservados

    def _ahora(self) -> str:
        """Marca de tiempo ISO 8601 en la zona horaria configurada (NFR-004)."""
        return datetime.now(self.zona).isoformat(timespec="seconds")


def _nombre_dia(fecha: date) -> str:
    """Nombre `<aaaa-mm-dd>` del día; un `datetime` se reduce a su fecha."""
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    return fecha.isoformat()


def _hash_sha256(contenido: bytes) -> str:
    """SHA-256 hexadecimal del contenido del PDF (DEC-003)."""
    return hashlib.sha256(contenido).hexdigest()


def _fecha_del_nombre_pdf(nombre: str) -> date | None:
    """Devuelve la fecha de un nombre `<aaaa-mm-dd>.pdf`, o `None` si no encaja.

    Exige el patrón exacto: el nombre debe tener el sufijo `.pdf` y su raíz
    debe ser la forma canónica ISO de una fecha, de modo que nombres como
    `2026-1-1.pdf`, `otro.pdf` o `2026-11-23.pdf.bak` se ignoren.
    """
    if not nombre.endswith(_SUFIJO_PDF):
        return None
    raiz = nombre[: -len(_SUFIJO_PDF)]
    try:
        fecha = date.fromisoformat(raiz)
    except ValueError:
        return None
    return fecha if fecha.isoformat() == raiz else None


def _escribir_atomico(ruta: Path, contenido: bytes) -> None:
    """Escribe `contenido` en `ruta` sin dejar el nombre definitivo a medias.

    Usa un fichero temporal en el mismo directorio y `replace`; ante cualquier
    error elimina el temporal y propaga la excepción (DEC-001).
    """
    temporal = ruta.with_name(ruta.name + _SUFIJO_TEMPORAL)
    try:
        temporal.write_bytes(contenido)
        temporal.replace(ruta)
    except BaseException:
        temporal.unlink(missing_ok=True)
        raise


def _texto(valor: object, campo: str) -> str:
    """Devuelve un texto del `.meta.json` o lanza ValueError."""
    if not isinstance(valor, str):
        raise ValueError(f"'{campo}' debe ser un texto en el .meta.json")
    return valor


def _entero(valor: object, campo: str) -> int | None:
    """Devuelve un entero o nulo del `.meta.json`, o lanza ValueError."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(
            f"'{campo}' debe ser un entero o nulo en el .meta.json"
        )
    return valor


def _lista(valor: object, campo: str) -> list:
    """Devuelve una lista del `.meta.json` o lanza ValueError."""
    if not isinstance(valor, list):
        raise ValueError(f"'{campo}' debe ser una lista en el .meta.json")
    return list(valor)
