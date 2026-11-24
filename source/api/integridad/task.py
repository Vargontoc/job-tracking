"""Tarea programada diaria de comprobación de integridad.

`TareaIntegridad` orquesta, en su propio hilo daemon del proceso FastAPI, la
comprobación diaria del PDF oficial de difusión de cada comunidad configurada,
a la hora entera configurada y en la zona horaria configurada (NFR-001,
NFR-004). No toca el planificador de `api-buscador` ni las demás tareas
programadas: convive con ellas (DEC-006, SUP-004).

Cada disparo:

1. Calcula el día en curso con la zona configurada.
2. Para cada comunidad consulta el `.meta.json` del día: si ya es terminal
   (`concordante`/`ok` o `fallido`) no descarga ni parsea (ALT-001, ALT-002,
   NFR-003).
3. Si hay PDF sin `.meta.json` (o con metadatos ilegibles) reprocesa el PDF
   existente y regenera los metadatos (ALT-007).
4. Si no hay nada, descarga el PDF, lo guarda de forma atómica con su hash,
   lo parsea, consulta `GET /buscador/status`, compara los recuentos y
   completa el `.meta.json` con los umbrales y el veredicto. Una descarga
   fallida deja el día `fallido` sin PDF (ALT-003); un parseo fallido conserva
   el PDF y deja el día `fallido` (DEC-002).
5. Registra un aviso consultable cuando el veredicto no es `concordante`
   (REQ-007). Los avisos son registros internos: no se envía nada por
   Telegram ni por ningún otro canal externo (SUP-007).
6. Al terminar todas las comunidades registra la ejecución global con el
   veredicto más grave (`fallido` > `divergente` > `concordante`, ALT-008) en
   el índice de ejecuciones y lanza la purga por antigüedad (REQ-008).

Al arrancar, `iniciar()` decide con `_decidir_arranque` qué toca antes de
entrar en el ciclo (DEC-007): si el día ya está resuelto en el `.meta.json` de
todas las comunidades no adelanta nada; si la hora configurada aún no ha
llegado, espera la ejecución normal; si se arranca dentro de la ventana
`[hora, hora + margen]` sin metadatos, programa una única ejecución para
`hora + margen`; y si se arranca después del margen, comprueba el día en el
acto. La decisión se apoya solo en el reloj inyectable y en el `.meta.json` de
hoy, nunca en memoria, de modo que un reinicio no rompe la frecuencia máxima
diaria (ALT-009). Nunca se procesan días anteriores ni se rellenan días
perdidos.

Una excepción inesperada de una comunidad se anota en los errores por
comunidad y no interrumpe a las demás; `_ejecutar_dia()` nunca propaga. Un
lock impide que dos disparos se solapen y el evento de parada corta tanto la
espera como el trabajo en curso. Sin SQLite (DEC-001).

El reloj es inyectable (`RelojProtocol`) y local de este subpaquete: no se
importa de `api-historico` ni de `api-buscador`. La espera se apoya en el
evento de parada, de modo que `detener()` corta el sueño en el acto.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.buscador_client import ClienteEstadoBuscador
from source.api.integridad.comparador import (
    ComparadorRecuentos,
    ResultadoComparacion,
)
from source.api.integridad.config import ConfigIntegridad
from source.api.integridad.downloader_adapter import (
    AdaptadorDescarga,
    ErrorDescargaIntegridad,
)
from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones
from source.api.integridad.parser_adapter import (
    AdaptadorParseo,
    ErrorParseoIntegridad,
    RecuentoPDF,
)
from source.api.integridad.pdf_store import (
    ESTADO_META_ILEGIBLE,
    ESTADO_META_OK,
    VEREDICTO_CONCORDANTE,
    VEREDICTO_DIVERGENTE,
    VEREDICTO_FALLIDO,
    AlmacenPDFs,
    ErrorPDFAusente,
    MetaDia,
)
from source.api.models import ComunidadConfigurada

logger = logging.getLogger(__name__)

# Gravedad del veredicto para agregar el resultado global (ALT-008).
_GRAVEDAD = {
    VEREDICTO_CONCORDANTE: 0,
    VEREDICTO_DIVERGENTE: 1,
    VEREDICTO_FALLIDO: 2,
}

# Resultado global de la ejecución en el índice (REQ-008).
RESULTADO_OK = "ok"
RESULTADO_PARCIAL = "parcial"

# Segundos de espera antes de reintentar el ciclo tras un error inesperado.
_ESPERA_TRAS_ERROR = 60.0

# Segundos máximos que `detener()` espera a que el hilo termine.
_ESPERA_PARADA = 10.0


class AccionArranque(str, Enum):
    """Qué toca hacer al arrancar la tarea, según DEC-007 y ALT-009.

    Valores:
        NINGUNA: el día en curso ya está resuelto en el `.meta.json` de todas
            las comunidades; no se adelanta ninguna comprobación.
        ESPERAR_NORMAL: la hora configurada aún no ha llegado; solo se espera
            la ejecución programada normal.
        DIFERIDA: se arranca dentro de la ventana `[hora, hora + margen]` sin
            metadatos de hoy; se programa una única ejecución para
            `hora + margen`.
        INMEDIATA: se arranca después de la ventana de catch-up sin metadatos
            de hoy; la comprobación del día se hace en el acto.
    """

    NINGUNA = "ninguna"
    ESPERAR_NORMAL = "esperar_normal"
    DIFERIDA = "diferida"
    INMEDIATA = "inmediata"


class RelojProtocol(Protocol):
    """Protocolo del reloj inyectable de la tarea de integridad."""

    def ahora(self) -> datetime:
        """Devuelve el instante actual, preferiblemente con zona horaria."""
        ...


class RelojReal:
    """Reloj real del sistema, expresado en la zona horaria configurada."""

    def __init__(self, zona: str | ZoneInfo = "Europe/Madrid") -> None:
        self._zona = zona if isinstance(zona, ZoneInfo) else ZoneInfo(zona)

    def ahora(self) -> datetime:
        """Devuelve el instante actual como datetime aware en la zona."""
        return datetime.now(self._zona)


@dataclass
class ResultadoDia:
    """Resultado de una ejecución diaria de la comprobación de integridad.

    Atributos:
        fecha: Día comprobado, en la zona horaria configurada (NFR-004).
        veredicto_global: Veredicto más grave entre las comunidades (ALT-008).
        veredictos_por_comunidad: Veredicto final por identificador de
            comunidad.
        errores_por_comunidad: Lista de `{comunidad, mensaje}` de las
            comunidades que fallaron de forma inesperada (REQ-008).
        referencias: Lista de `{fecha, comunidad}` que apunta a los `.meta.json`
            del día (DEC-001).
    """

    fecha: date
    veredicto_global: str = VEREDICTO_CONCORDANTE
    veredictos_por_comunidad: dict[str, str] = field(default_factory=dict)
    errores_por_comunidad: list[dict] = field(default_factory=list)
    referencias: list[dict] = field(default_factory=list)


class TareaIntegridad:
    """Tarea diaria que orquesta la comprobación de integridad (REQ-001).

    Args:
        config: Configuración de la integridad (`config-integridad`), de la
            que salen la hora, la zona, la retención, los umbrales y las
            comunidades.
        almacen: Almacén de PDFs y metadatos del día (`pdf-store`).
        adaptador_descarga: Adaptador de descarga del PDF (`downloader-adapter`).
        adaptador_parseo: Adaptador de recuento del PDF (`parser-adapter`).
        cliente_buscador: Cliente de `GET /buscador/status`
            (`buscador-status-adapter`).
        comparador: Comparador de recuentos (`comparador-veredicto`).
        avisos: Almacén de avisos del día (`avisos-store`).
        ejecuciones: Índice de ejecuciones del último mes (`avisos-store`).
        purger: Función de purga por antigüedad (`pdf-purger`).
        reloj: Reloj inyectable para las pruebas. Si es `None`, se usa el reloj
            real en la zona configurada.
    """

    def __init__(
        self,
        config: ConfigIntegridad,
        almacen: AlmacenPDFs,
        adaptador_descarga: AdaptadorDescarga,
        adaptador_parseo: AdaptadorParseo,
        cliente_buscador: ClienteEstadoBuscador,
        comparador: ComparadorRecuentos,
        avisos: AlmacenAvisos,
        ejecuciones: IndiceEjecuciones,
        purger: Callable[[str | Path, int, date], list[Path]],
        reloj: RelojProtocol | None = None,
    ) -> None:
        self._config = config
        self._almacen = almacen
        self._adaptador_descarga = adaptador_descarga
        self._adaptador_parseo = adaptador_parseo
        self._cliente_buscador = cliente_buscador
        self._comparador = comparador
        self._avisos = avisos
        self._ejecuciones = ejecuciones
        self._purgar = purger
        self._zona = config.zona
        self._reloj = reloj if reloj is not None else RelojReal(self._zona)
        self._evento_parada = threading.Event()
        self._lock_ejecucion = threading.Lock()
        self._hilo: threading.Thread | None = None

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def iniciar(self) -> None:
        """Arranca el hilo daemon que programa la comprobación del día.

        Antes de esperar, decide con `_decidir_arranque` qué toca en este
        arranque (DEC-007): no adelantar nada, esperar la hora configurada,
        una única ejecución diferida a `hora + margen` o una comprobación
        inmediata del día en curso. La decisión solo mira el reloj inyectable y
        el `.meta.json` de hoy, nunca un estado en memoria (ALT-009), y la
        comprobación que se adelanta comparte el lock y la idempotencia de
        `_ejecutar_dia()`, de modo que no se duplica con la ejecución normal.
        """
        if self._hilo is not None and self._hilo.is_alive():
            logger.warning("La tarea de integridad ya está en ejecución")
            return
        self._evento_parada.clear()
        ahora = self._reloj.ahora()
        try:
            accion = self._decidir_arranque(ahora, self._hay_meta_hoy())
        except Exception:
            logger.exception(
                "No se pudo decidir el arranque de la tarea de integridad; se "
                "espera la ejecución programada normal"
            )
            accion = AccionArranque.ESPERAR_NORMAL
        self._hilo = threading.Thread(
            target=self._ciclo,
            args=(ahora, accion),
            name="integridad-task",
            daemon=True,
        )
        self._hilo.start()
        logger.info(
            "Tarea de integridad iniciada con arranque '%s', próxima ejecución "
            "normal a las %02d:00",
            accion.value,
            self._config.hora_ejecucion,
        )

    def detener(self) -> None:
        """Detiene el hilo de forma limpia, sin dejar ejecuciones en curso."""
        logger.info("Deteniendo tarea de integridad...")
        self._evento_parada.set()
        hilo = self._hilo
        if hilo is not None:
            hilo.join(timeout=_ESPERA_PARADA)
            if hilo.is_alive():
                logger.warning(
                    "La tarea de integridad no se detuvo en el tiempo esperado"
                )
        logger.info("Tarea de integridad detenida")

    def _ejecutar_dia(self) -> ResultadoDia | None:
        """Ejecuta la comprobación del día en curso, sin propagar errores.

        Es idempotente por comunidad gracias al `.meta.json` del día. Si ya
        hay una ejecución en curso (o la tarea está detenida), se omite y
        devuelve `None`; cualquier excepción inesperada se registra y también
        devuelve `None`.

        Returns:
            El resultado del día, o `None` si se omitió o falló por completo.
        """
        if not self._lock_ejecucion.acquire(blocking=False):
            logger.info(
                "Ya hay una comprobación de integridad en curso; se omite"
            )
            return None
        try:
            if self._evento_parada.is_set():
                logger.info(
                    "La tarea de integridad está detenida; no se ejecuta el día"
                )
                return None
            return self._ejecutar_dia_interno()
        except Exception:
            logger.exception(
                "Error inesperado en la comprobación diaria de integridad"
            )
            return None
        finally:
            self._lock_ejecucion.release()

    # ------------------------------------------------------------------
    # Programación
    # ------------------------------------------------------------------

    def _ciclo(self, ahora: datetime, accion: AccionArranque) -> None:
        """Atiende la acción de arranque y después espera la hora configurada.

        Args:
            ahora: Instante leído al arrancar. Se reutiliza para la primera
                espera, de modo que el ciclo no vuelve a leer el reloj antes de
                esperar y el arranque no adelanta ni retrasa la ejecución.
            accion: Acción decidida por `_decidir_arranque`.
        """
        try:
            if not self._ejecutar_accion_de_arranque(ahora, accion):
                return
        except Exception:
            logger.exception("Error en el arranque de la tarea de integridad")
            if self._evento_parada.wait(timeout=_ESPERA_TRAS_ERROR):
                return

        while not self._evento_parada.is_set():
            try:
                espera = self._segundos_hasta_proxima(self._reloj.ahora())
                logger.debug(
                    "Esperando %.1fs hasta la próxima comprobación de "
                    "integridad",
                    espera,
                )
                if self._evento_parada.wait(timeout=espera):
                    break
                self._ejecutar_dia()
            except Exception:
                logger.exception("Error en el ciclo de la tarea de integridad")
                if self._evento_parada.wait(timeout=_ESPERA_TRAS_ERROR):
                    break

    def _ejecutar_accion_de_arranque(
        self, ahora: datetime, accion: AccionArranque
    ) -> bool:
        """Aplica la acción de arranque; devuelve `False` si se pidió detener."""
        if accion is AccionArranque.INMEDIATA:
            logger.info(
                "Arranque posterior al margen de catch-up sin metadatos de "
                "hoy; se comprueba el día en curso"
            )
            self._ejecutar_dia()
            return True

        if accion is AccionArranque.DIFERIDA:
            espera = self._segundos_hasta_catchup(ahora)
            logger.info(
                "Arranque dentro del margen de catch-up; el día se comprobará "
                "en %.0fs",
                espera,
            )
            if self._evento_parada.wait(timeout=espera):
                return False
            if self._hay_meta_hoy():
                logger.info(
                    "El día quedó resuelto durante el margen; no se ejecuta"
                )
                return True
            self._ejecutar_dia()
            return True

        # NINGUNA y ESPERAR_NORMAL: solo la ejecución programada normal.
        espera = self._segundos_hasta_proxima(ahora)
        logger.debug(
            "Esperando %.1fs hasta la comprobación programada de integridad",
            espera,
        )
        if self._evento_parada.wait(timeout=espera):
            return False
        self._ejecutar_dia()
        return True

    def _decidir_arranque(
        self, ahora: datetime, hay_meta_hoy: bool
    ) -> AccionArranque:
        """Decide qué toca al arrancar, sin efectos (DEC-007, ALT-009).

        Es una función pura sobre el reloj y la existencia del `.meta.json` de
        hoy: no lee ficheros, no duerme y no consulta ningún estado en memoria.
        El metadato del día tiene prioridad, de modo que un día ya resuelto no
        se vuelve a comprobar aunque se reinicie la aplicación.

        Args:
            ahora: Instante del arranque, con o sin zona horaria (un instante
                sin zona se interpreta en la zona configurada).
            hay_meta_hoy: `True` si todas las comunidades configuradas ya
                tienen `.meta.json` de hoy con veredicto terminal; lo calcula
                `_hay_meta_hoy` leyendo el almacén.

        Returns:
            `NINGUNA` si el día ya está resuelto; `ESPERAR_NORMAL` antes de la
            hora configurada; `DIFERIDA` dentro de `[hora, hora + margen]`; e
            `INMEDIATA` después de `hora + margen`. Con `margen_catchup` a 0, el
            instante exacto de la hora es `DIFERIDA` con espera cero y, a partir
            de ahí, `INMEDIATA`.
        """
        if hay_meta_hoy:
            return AccionArranque.NINGUNA
        local = self._como_local(ahora)
        inicio = local.replace(
            hour=self._config.hora_ejecucion,
            minute=0,
            second=0,
            microsecond=0,
        )
        if local < inicio:
            return AccionArranque.ESPERAR_NORMAL
        limite = inicio + timedelta(minutes=self._config.margen_catchup)
        if local <= limite:
            return AccionArranque.DIFERIDA
        return AccionArranque.INMEDIATA

    def _segundos_hasta_catchup(self, ahora: datetime) -> float:
        """Segundos que faltan hasta el final de la ventana de catch-up.

        La ventana empieza a la hora configurada y dura `margen_catchup`
        minutos (DEC-007); nunca es negativo.
        """
        local = self._como_local(ahora)
        inicio = local.replace(
            hour=self._config.hora_ejecucion,
            minute=0,
            second=0,
            microsecond=0,
        )
        limite = inicio + timedelta(minutes=self._config.margen_catchup)
        return max(0.0, (limite - local).total_seconds())

    def _hay_meta_hoy(self) -> bool:
        """Indica si todas las comunidades ya tienen el día resuelto (DEC-007).

        Criterio: hay metadatos de hoy si **todas** las comunidades de la
        configuración tienen un `.meta.json` de hoy legible con veredicto
        terminal (`ok`/`concordante`, `divergente` o `fallido`). Basta que una
        comunidad no lo tenga —ausente, ilegible o sin veredicto— para que el
        día se considere pendiente. Sin comunidades configuradas no hay nada
        que comprobar y devuelve `True`. Se consulta siempre el disco con
        `almacen.leer_meta`, nunca un estado en memoria, de modo que la
        decisión sobrevive a un reinicio (ALT-009).
        """
        hoy = self._hoy()
        for comunidad in self._config.comunidades:
            lectura = self._almacen.leer_meta(comunidad.identificador, hoy)
            if not lectura.es_valido:
                return False
            if _normalizar_veredicto(lectura.meta.veredicto) is None:
                return False
        return True

    def _segundos_hasta_proxima(self, ahora: datetime) -> float:
        """Segundos que faltan hasta la próxima ejecución programada."""
        local = self._como_local(ahora)
        return max(
            0.0, (self._proxima_ejecucion(local) - local).total_seconds()
        )

    def _proxima_ejecucion(self, local: datetime) -> datetime:
        """Próximo instante a la hora configurada, en la zona configurada.

        Si la hora de hoy aún no ha llegado, devuelve la de hoy; si ya pasó
        (incluido el instante exacto), la de mañana. La ejecución diaria no se
        repite dentro del mismo disparo: el ciclo vuelve a calcular la
        siguiente.
        """
        proxima = local.replace(
            hour=self._config.hora_ejecucion,
            minute=0,
            second=0,
            microsecond=0,
        )
        if proxima <= local:
            proxima += timedelta(days=1)
        return proxima

    def _como_local(self, ahora: datetime) -> datetime:
        """Expresa un instante en la zona horaria configurada (NFR-004)."""
        if ahora.tzinfo is None:
            ahora = ahora.replace(tzinfo=self._zona)
        return ahora.astimezone(self._zona)

    def _hoy(self) -> date:
        """Día en curso según la zona horaria configurada (NFR-004)."""
        return self._como_local(self._reloj.ahora()).date()

    # ------------------------------------------------------------------
    # Ejecución del día
    # ------------------------------------------------------------------

    def _ejecutar_dia_interno(self) -> ResultadoDia:
        """Comprueba todas las comunidades configuradas y cierra el día."""
        hoy = self._hoy()
        resultado = ResultadoDia(fecha=hoy)
        logger.info("Comprobación de integridad del %s", hoy.isoformat())

        interrumpida = False
        for comunidad in self._config.comunidades:
            if self._evento_parada.is_set():
                logger.info(
                    "Detención solicitada; se interrumpe la comprobación del día"
                )
                interrumpida = True
                break
            self._procesar_comunidad_segura(comunidad, hoy, resultado)

        resultado.veredicto_global = _veredicto_mas_grave(
            resultado.veredictos_por_comunidad.values()
        )

        if interrumpida:
            logger.info(
                "Comprobación interrumpida por detención; no se registra la "
                "ejecución ni se purga"
            )
            return resultado

        self._registrar_ejecucion(resultado)
        self._purgar_por_antiguedad(hoy)
        logger.info(
            "Comprobación de integridad del %s terminada con veredicto %s",
            hoy.isoformat(),
            resultado.veredicto_global,
        )
        return resultado

    def _procesar_comunidad_segura(
        self,
        comunidad: ComunidadConfigurada,
        hoy: date,
        resultado: ResultadoDia,
    ) -> None:
        """Procesa una comunidad anotando su veredicto o su error inesperado."""
        identificador = comunidad.identificador
        resultado.referencias.append(
            {"fecha": hoy.isoformat(), "comunidad": identificador}
        )
        try:
            veredicto = self._procesar_comunidad(comunidad, hoy)
        except Exception as error:
            logger.exception(
                "Error inesperado en la comunidad %s de integridad",
                identificador,
            )
            resultado.errores_por_comunidad.append(
                {
                    "comunidad": identificador,
                    "mensaje": (
                        f"Error en la comprobación de {identificador}: {error}"
                    ),
                }
            )
            resultado.veredictos_por_comunidad[identificador] = (
                VEREDICTO_FALLIDO
            )
            return
        resultado.veredictos_por_comunidad[identificador] = veredicto

    def _procesar_comunidad(
        self,
        comunidad: ComunidadConfigurada,
        hoy: date,
    ) -> str:
        """Comprueba una comunidad y devuelve su veredicto del día."""
        identificador = comunidad.identificador
        lectura = self._almacen.leer_meta(identificador, hoy)
        if lectura.es_valido:
            veredicto = _normalizar_veredicto(lectura.meta.veredicto)
            if veredicto is not None:
                logger.info(
                    "La comunidad %s ya tiene el día %s resuelto (%s); se omite",
                    identificador,
                    hoy.isoformat(),
                    veredicto,
                )
                return veredicto

        if self._hay_pdf_reprocesable(identificador, hoy, lectura.estado):
            return self._reprocesar_pdf_existente(identificador, hoy)

        return self._descargar_y_comprobar(
            identificador, comunidad.url_pdf, hoy
        )

    def _hay_pdf_reprocesable(
        self,
        comunidad: str,
        hoy: date,
        estado_meta: str,
    ) -> bool:
        """Indica si el día debe reprocesarse a partir del PDF ya guardado.

        Es el PDF huérfano (hay PDF y no hay `.meta.json`, ALT-007) o el día
        con metadatos ilegibles y PDF presente: en ambos casos se regeneran los
        metadatos desde el PDF sin volver a descargarlo.
        """
        if self._almacen.detectar_huerfano(comunidad, hoy):
            return True
        return (
            estado_meta == ESTADO_META_ILEGIBLE
            and self._almacen.ruta_pdf(comunidad, hoy).is_file()
        )

    def _reprocesar_pdf_existente(self, comunidad: str, hoy: date) -> str:
        """Reprocesa el PDF del día ya guardado y regenera sus metadatos."""
        logger.info(
            "PDF de %s del %s sin metadatos utilizables; se reprocesa",
            comunidad,
            hoy.isoformat(),
        )
        try:
            contenido = self._almacen.ruta_pdf(comunidad, hoy).read_bytes()
        except OSError as error:
            motivo = (
                f"No se pudo leer el PDF de {comunidad} del "
                f"{hoy.isoformat()}: {error}"
            )
            self._almacen.escribir_fallido(comunidad, hoy, motivo)
            self._avisos.registrar_fallo(comunidad, hoy, motivo)
            return VEREDICTO_FALLIDO

        parseo = self._adaptador_parseo.parsear(contenido, comunidad)
        if isinstance(parseo, ErrorParseoIntegridad):
            return self._marcar_fallo_parseo(comunidad, hoy, parseo.motivo)

        return self._completar_dia(
            comunidad, hoy, MetaDia(), parseo, regenerar=True
        )

    def _descargar_y_comprobar(
        self,
        comunidad: str,
        url_pdf: str,
        hoy: date,
    ) -> str:
        """Descarga el PDF del día, lo guarda, lo parsea y emite el veredicto."""
        descarga = self._adaptador_descarga.descargar(url_pdf)
        if isinstance(descarga, ErrorDescargaIntegridad):
            motivo = (
                f"No se pudo descargar el PDF de {comunidad}: {descarga.motivo}"
            )
            self._almacen.escribir_fallido(comunidad, hoy, motivo)
            self._avisos.registrar_fallo(comunidad, hoy, motivo)
            logger.warning(motivo)
            return VEREDICTO_FALLIDO

        meta = self._almacen.guardar_pdf(comunidad, hoy, descarga)
        parseo = self._adaptador_parseo.parsear(descarga, comunidad)
        if isinstance(parseo, ErrorParseoIntegridad):
            return self._marcar_fallo_parseo(
                comunidad, hoy, parseo.motivo, meta=meta
            )

        return self._completar_dia(comunidad, hoy, meta, parseo)

    def _marcar_fallo_parseo(
        self,
        comunidad: str,
        hoy: date,
        motivo_parseo: str,
        meta: MetaDia | None = None,
    ) -> str:
        """Conserva el PDF y deja el día `fallido` con el error (DEC-002)."""
        motivo = f"No se pudo parsear el PDF de {comunidad}: {motivo_parseo}"
        base = meta if meta is not None else MetaDia()
        fallido = replace(
            base, veredicto=VEREDICTO_FALLIDO, errores=[*base.errores, motivo]
        )
        try:
            if meta is None:
                self._almacen.regenerar_meta(comunidad, hoy, fallido)
            else:
                self._almacen.escribir_meta(comunidad, hoy, fallido)
        except ErrorPDFAusente:
            logger.warning(
                "El PDF de %s del %s ya no está disponible; se deja el día "
                "fallido sin PDF",
                comunidad,
                hoy.isoformat(),
            )
            self._almacen.escribir_fallido(comunidad, hoy, motivo)
        self._avisos.registrar_fallo(comunidad, hoy, motivo)
        logger.warning(motivo)
        return VEREDICTO_FALLIDO

    def _completar_dia(
        self,
        comunidad: str,
        hoy: date,
        meta: MetaDia,
        parseo: RecuentoPDF,
        regenerar: bool = False,
    ) -> str:
        """Consulta el buscador, compara y guarda el veredicto del día."""
        estado = self._cliente_buscador.consultar_estado()
        resultado = self._comparador.comparar(parseo.recuento, estado)
        completo = _meta_del_resultado(meta, resultado)

        if regenerar:
            self._almacen.regenerar_meta(comunidad, hoy, completo)
        else:
            self._almacen.escribir_meta(comunidad, hoy, completo)

        if resultado.veredicto != VEREDICTO_CONCORDANTE:
            self._avisos.registrar_divergencia(comunidad, hoy, resultado)
            logger.warning(
                "Divergencia de integridad en %s del %s: %s",
                comunidad,
                hoy.isoformat(),
                resultado.motivo,
            )

        return resultado.veredicto

    # ------------------------------------------------------------------
    # Cierre del día
    # ------------------------------------------------------------------

    def _registrar_ejecucion(self, resultado: ResultadoDia) -> None:
        """Añade la ejecución del día al índice del último mes (REQ-008)."""
        ejecucion = Ejecucion(
            resultado_global=_resultado_global(resultado),
            veredicto_agregado=resultado.veredicto_global,
            errores_por_comunidad=[
                dict(error) for error in resultado.errores_por_comunidad
            ],
            referencias=[dict(ref) for ref in resultado.referencias],
        )
        try:
            self._ejecuciones.registrar(ejecucion)
        except Exception:
            logger.exception(
                "No se pudo registrar la ejecución de integridad del %s",
                resultado.fecha.isoformat(),
            )

    def _purgar_por_antiguedad(self, hoy: date) -> None:
        """Purga los PDFs fuera de la ventana de retención (REQ-002)."""
        try:
            eliminados = self._purgar(
                self._config.ruta_base_pdfs,
                self._config.dias_retencion,
                hoy,
            )
        except Exception:
            logger.exception("Error en la purga de PDFs de integridad")
            return
        if eliminados:
            logger.info(
                "Purga de integridad: %d ficheros eliminados", len(eliminados)
            )


def _normalizar_veredicto(veredicto: str) -> str | None:
    """Veredicto agregable del día, o `None` si el día no está resuelto.

    Acepta `ok` como alias de `concordante` (el estado del día se expresa con
    el veredicto `ok`/`concordante`, `divergente` o `fallido`). Un veredicto
    vacío o desconocido indica que el día no llegó a completarse.
    """
    if veredicto in (VEREDICTO_CONCORDANTE, ESTADO_META_OK):
        return VEREDICTO_CONCORDANTE
    if veredicto in (VEREDICTO_DIVERGENTE, VEREDICTO_FALLIDO):
        return veredicto
    return None


def _veredicto_mas_grave(veredictos: Iterable[str]) -> str:
    """Veredicto más grave de los recibidos (ALT-008)."""
    resultado = VEREDICTO_CONCORDANTE
    for veredicto in veredictos:
        if _GRAVEDAD.get(veredicto, 0) > _GRAVEDAD[resultado]:
            resultado = veredicto
    return resultado


def _resultado_global(resultado: ResultadoDia) -> str:
    """Resultado global de la ejecución: `ok` o `parcial` (REQ-008)."""
    if not resultado.errores_por_comunidad:
        return RESULTADO_OK
    return RESULTADO_PARCIAL


def _meta_del_resultado(
    base: MetaDia, resultado: ResultadoComparacion
) -> MetaDia:
    """Traslada el veredicto del comparador al `.meta.json` del día (REQ-005)."""
    return replace(
        base,
        recuento_pdf=resultado.recuento_pdf,
        recuento_buscador=resultado.recuento_buscador,
        diferencia=resultado.diferencia,
        tolerancia_absoluta=resultado.tolerancia_absoluta,
        tolerancia_relativa_pct=resultado.tolerancia_relativa_pct,
        umbral_cordura=resultado.umbral_cordura,
        veredicto=resultado.veredicto,
    )
