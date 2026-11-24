"""Índice en JSON de las ejecuciones de la integridad del último mes.

Cada pasada de la comprobación diaria se registra en `<base>/ejecuciones.json`
(con la ruta base por defecto, `data/pdfs/ejecuciones.json`): un fichero JSON
ligero con la forma `{"version": 1, "ejecuciones": [...]}` donde cada entrada
lleva la marca de tiempo, el resultado global, los errores por comunidad, el
veredicto agregado y la referencia por fecha y comunidad a los `.meta.json` del
día (REQ-008, DEC-001). No se añade ningún fichero SQLite.

- La escritura es atómica: fichero temporal en el mismo directorio y `replace`
  al nombre definitivo, sin temporales remanentes.
- La marca de tiempo se genera con la zona horaria configurada y no con la del
  sistema (NFR-004).
- `consultar_ultimo_mes(hoy)` filtra la ventana de 30 días por la fecha de la
  marca de tiempo y ordena de más reciente a más antigua (REQ-009).
- Un índice ausente se lee como un índice vacío válido. Un índice ilegible o
  corrupto se comunica con `LecturaIndice.estado == "ilegible"` en lugar de
  lanzar una excepción o devolver un índice válido, y no impide registrar una
  ejecución nueva: al registrar se reescribe con la entrada nueva, conservando
  las entradas recuperables (riesgo de metadatos corruptos de `design@3`).
"""

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Versión del formato del índice, para poder evolucionarlo.
VERSION_INDICE = 1

# Días de la ventana de la consulta de las ejecuciones del último mes.
DIAS_VENTANA_MES = 30

# Estados posibles del resultado de `leer`.
ESTADO_INDICE_OK = "ok"
ESTADO_INDICE_AUSENTE = "ausente"
ESTADO_INDICE_ILEGIBLE = "ilegible"

# Campos de cada ejecución, en el orden en que se escriben (REQ-008).
CAMPOS_EJECUCION = (
    "timestamp",
    "resultado_global",
    "errores_por_comunidad",
    "veredicto_agregado",
    "referencias",
)

_NOMBRE_INDICE = "ejecuciones.json"
_SUFIJO_TEMPORAL = ".tmp"


@dataclass(frozen=True)
class Ejecucion:
    """Una ejecución del proceso de integridad guardada en el índice.

    Atributos:
        resultado_global: Resultado de la pasada (`ok` cuando no hubo errores y,
            por ejemplo, `parcial` cuando alguna comunidad falló).
        veredicto_agregado: Veredicto global del día, el más grave entre las
            comunidades (`fallido` > `divergente` > `concordante`, ALT-008).
        errores_por_comunidad: Lista de `{comunidad, mensaje}` de las
            comunidades que fallaron (REQ-008).
        referencias: Lista de `{fecha, comunidad}` que apunta a los `.meta.json`
            del día (DEC-001).
        timestamp: Marca de tiempo ISO 8601; si está vacía, `registrar` la genera
            en la zona horaria configurada (NFR-004).
    """

    resultado_global: str
    veredicto_agregado: str = ""
    errores_por_comunidad: list[dict] = field(default_factory=list)
    referencias: list[dict] = field(default_factory=list)
    timestamp: str = ""

    def a_diccionario(self) -> dict:
        """Devuelve la entrada del índice como diccionario JSON."""
        return {
            "timestamp": self.timestamp,
            "resultado_global": self.resultado_global,
            "errores_por_comunidad": [
                dict(error) for error in self.errores_por_comunidad
            ],
            "veredicto_agregado": self.veredicto_agregado,
            "referencias": [
                dict(referencia) for referencia in self.referencias
            ],
        }

    @classmethod
    def desde_diccionario(cls, datos: object) -> "Ejecucion":
        """Reconstruye una ejecución desde una entrada del índice.

        Raises:
            ValueError: si la entrada no tiene la forma del modelo o su marca de
                tiempo no es una fecha ISO 8601, para que quien llama no la
                confunda con una ejecución válida.
        """
        if not isinstance(datos, dict):
            raise ValueError("la ejecución no es un objeto JSON")
        faltan = [campo for campo in CAMPOS_EJECUCION if campo not in datos]
        if faltan:
            raise ValueError(
                "faltan campos en la ejecución: " + ", ".join(faltan)
            )

        timestamp = _texto(datos["timestamp"], "timestamp")
        try:
            datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise ValueError(
                f"'timestamp' no es una fecha ISO 8601: {error}"
            ) from error

        return cls(
            resultado_global=_texto(
                datos["resultado_global"], "resultado_global"
            ),
            veredicto_agregado=_texto(
                datos["veredicto_agregado"], "veredicto_agregado"
            ),
            errores_por_comunidad=_errores(datos["errores_por_comunidad"]),
            referencias=_referencias(datos["referencias"]),
            timestamp=timestamp,
        )


@dataclass(frozen=True)
class LecturaIndice:
    """Resultado controlado de la lectura del índice de ejecuciones.

    `estado` es `ok` (índice legible), `ausente` (todavía no existe, se lee
    como índice vacío válido) o `ilegible` (no es JSON válido o no tiene la
    forma esperada). En el caso `ilegible`, `ejecuciones` contiene solo las
    entradas recuperables y `motivo` explica qué ocurre.
    """

    estado: str
    ejecuciones: list[Ejecucion] = field(default_factory=list)
    motivo: str = ""

    @property
    def es_valido(self) -> bool:
        """Indica si el índice es utilizable (legible o aún sin crear)."""
        return self.estado in (ESTADO_INDICE_OK, ESTADO_INDICE_AUSENTE)


class IndiceEjecuciones:
    """Registra y consulta las ejecuciones de la integridad del último mes.

    Args:
        base: Ruta base del árbol de PDFs, absoluta o relativa a la raíz del
            proyecto; el índice se guarda como `<base>/ejecuciones.json`.
        zona_horaria: Zona IANA (o `ZoneInfo`) con la que se genera la marca de
            tiempo de las ejecuciones (NFR-004).
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

    @property
    def ruta_indice(self) -> Path:
        """Devuelve `<base>/ejecuciones.json`."""
        return self.base / _NOMBRE_INDICE

    def registrar(self, ejecucion: Ejecucion) -> Ejecucion:
        """Añade la ejecución al índice y lo reescribe de forma atómica.

        Si la ejecución no trae marca de tiempo, se genera aquí con la zona
        horaria configurada (NFR-004). Un índice ilegible o corrupto no impide
        el registro: se reescribe con la entrada nueva, conservando las
        entradas recuperables que se hayan podido leer.

        Returns:
            La ejecución guardada, con su marca de tiempo ya completa.
        """
        lectura = self.leer()
        if lectura.estado == ESTADO_INDICE_ILEGIBLE:
            logger.warning(
                "Índice de ejecuciones ilegible en %s: %s; se reescribe "
                "conservando %d entradas recuperables",
                self.ruta_indice,
                lectura.motivo,
                len(lectura.ejecuciones),
            )

        completa = (
            ejecucion
            if ejecucion.timestamp
            else replace(ejecucion, timestamp=self._ahora())
        )
        self._escribir([*lectura.ejecuciones, completa])
        logger.info("Ejecución registrada en %s", self.ruta_indice)
        return completa

    def leer(self) -> LecturaIndice:
        """Lee el índice con un resultado controlado.

        Si el fichero no existe devuelve estado `ausente` (índice vacío
        válido); si no es JSON válido o no tiene la forma esperada, estado
        `ilegible` con el motivo, sin lanzar excepción y sin tocar el fichero.
        """
        ruta = self.ruta_indice
        if not ruta.is_file():
            return LecturaIndice(estado=ESTADO_INDICE_AUSENTE)

        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            logger.warning(
                "Índice de ejecuciones ilegible en %s: %s", ruta, error
            )
            return LecturaIndice(
                estado=ESTADO_INDICE_ILEGIBLE, motivo=str(error)
            )

        return _leer_datos(datos)

    def consultar_ultimo_mes(self, hoy: date | datetime) -> list[Ejecucion]:
        """Devuelve las ejecuciones del último mes, de reciente a vieja.

        La ventana es inclusiva: `hoy - 30 días <= fecha <= hoy`, con la
        fecha tomada de la marca de tiempo convertida a la zona configurada.
        Un índice ausente o ilegible devuelve lo que se haya podido recuperar
        (lista vacía si no hay nada) sin error (REQ-009).
        """
        dia = _solo_fecha(hoy)
        inicio = dia - timedelta(days=DIAS_VENTANA_MES)

        seleccionadas: list[tuple[datetime, Ejecucion]] = []
        for ejecucion in self.leer().ejecuciones:
            momento = _momento(ejecucion.timestamp, self.zona)
            if inicio <= momento.date() <= dia:
                seleccionadas.append((momento, ejecucion))
        seleccionadas.sort(key=lambda par: par[0], reverse=True)
        return [ejecucion for _, ejecucion in seleccionadas]

    def _escribir(self, ejecuciones: list[Ejecucion]) -> None:
        """Escribe el índice completo de forma atómica (DEC-001)."""
        self.base.mkdir(parents=True, exist_ok=True)
        ruta = self.ruta_indice
        texto = json.dumps(
            {
                "version": VERSION_INDICE,
                "ejecuciones": [
                    ejecucion.a_diccionario() for ejecucion in ejecuciones
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        _escribir_atomico(ruta, (texto + "\n").encode("utf-8"))

    def _ahora(self) -> str:
        """Marca de tiempo ISO 8601 en la zona horaria configurada (NFR-004)."""
        return datetime.now(self.zona).isoformat(timespec="seconds")


def _leer_datos(datos: object) -> LecturaIndice:
    """Interpreta el JSON del índice con un resultado controlado."""
    if not isinstance(datos, dict) or not isinstance(
        datos.get("ejecuciones"), list
    ):
        return LecturaIndice(
            estado=ESTADO_INDICE_ILEGIBLE,
            motivo="el índice no tiene la forma {version, ejecuciones: [...]}",
        )

    recuperables: list[Ejecucion] = []
    omitidas = 0
    for entrada in datos["ejecuciones"]:
        try:
            recuperables.append(Ejecucion.desde_diccionario(entrada))
        except (TypeError, ValueError):
            omitidas += 1

    if omitidas:
        logger.warning(
            "Índice de ejecuciones con %d entradas ilegibles de %d",
            omitidas,
            len(datos["ejecuciones"]),
        )
        return LecturaIndice(
            estado=ESTADO_INDICE_ILEGIBLE,
            ejecuciones=recuperables,
            motivo=f"{omitidas} entradas ilegibles en el índice",
        )

    return LecturaIndice(
        estado=ESTADO_INDICE_OK, ejecuciones=recuperables
    )


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


def _momento(texto: str, zona: ZoneInfo) -> datetime:
    """Instante ISO 8601 del texto, expresado en la zona configurada."""
    momento = datetime.fromisoformat(texto)
    if momento.tzinfo is None:
        return momento.replace(tzinfo=zona)
    return momento.astimezone(zona)


def _solo_fecha(valor: date) -> date:
    """Reduce un `datetime` a su fecha para comparar con la del timestamp."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor


def _texto(valor: object, campo: str) -> str:
    """Devuelve un texto de la ejecución o lanza ValueError."""
    if not isinstance(valor, str):
        raise ValueError(f"'{campo}' debe ser un texto en la ejecución")
    return valor


def _errores(valor: object) -> list[dict]:
    """Devuelve los errores por comunidad o lanza ValueError."""
    if not isinstance(valor, list):
        raise ValueError(
            "'errores_por_comunidad' debe ser una lista en la ejecución"
        )
    errores: list[dict] = []
    for error in valor:
        if not isinstance(error, dict):
            raise ValueError(
                "cada error por comunidad debe ser un objeto JSON"
            )
        errores.append(
            {
                "comunidad": _texto(error.get("comunidad"), "comunidad"),
                "mensaje": _texto(error.get("mensaje"), "mensaje"),
            }
        )
    return errores


def _referencias(valor: object) -> list[dict]:
    """Devuelve las referencias a los `.meta.json` o lanza ValueError."""
    if not isinstance(valor, list):
        raise ValueError("'referencias' debe ser una lista en la ejecución")
    referencias: list[dict] = []
    for referencia in valor:
        if not isinstance(referencia, dict):
            raise ValueError("cada referencia debe ser un objeto JSON")
        referencias.append(
            {
                "fecha": _texto(referencia.get("fecha"), "fecha"),
                "comunidad": _texto(
                    referencia.get("comunidad"), "comunidad"
                ),
            }
        )
    return referencias
