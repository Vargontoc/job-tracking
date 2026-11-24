"""Pruebas unitarias del catch-up de arranque de la integridad (TASK-013).

Cubren la decisión pura de `_decidir_arranque` para los cuatro casos de
DEC-007 (antes de la hora, dentro de la ventana, al final del margen y después
del margen), el criterio de `_hay_meta_hoy` (todas las comunidades con el día
resuelto, consultado en disco y nunca en memoria) y el comportamiento de
`iniciar()`: nada inmediato antes de la hora, una única ejecución diferida a
`hora + margen` que no se duplica con la normal, ejecución inmediata tras el
margen y ninguna repetición cuando el día ya se procesó antes de un reinicio.
La recuperación nunca toca días anteriores.

El reloj se inyecta y las esperas del hilo son cortas (menos de un segundo),
de modo que ninguna prueba duerme de verdad; los dobles viven en `tmp_path`.
"""

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.buscador_client import (
    EstadoBuscador,
    UltimaPasada,
)
from source.api.integridad.comparador import ComparadorRecuentos
from source.api.integridad.config import ConfigIntegridad
from source.api.integridad.ejecuciones import IndiceEjecuciones
from source.api.integridad.parser_adapter import RecuentoPDF
from source.api.integridad.pdf_store import (
    VEREDICTO_CONCORDANTE,
    AlmacenPDFs,
    MetaDia,
)
from source.api.integridad.task import AccionArranque, TareaIntegridad
from source.api.models import ComunidadConfigurada

ZONA = ZoneInfo("Europe/Madrid")
HOY = date(2026, 11, 23)
AHORA = datetime(2026, 11, 23, 2, 30, tzinfo=ZONA)
CONTENIDO_PDF = b"%PDF-1.4 contenido simulado del PDF de difusion"

CANTABRIA = ComunidadConfigurada(
    identificador="cantabria",
    url_pdf="https://ejemplo.test/cantabria.pdf",
)
MADRID = ComunidadConfigurada(
    identificador="madrid",
    url_pdf="https://ejemplo.test/madrid.pdf",
)


# ---------------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------------


class RelojFijo:
    """Reloj de prueba que devuelve siempre el mismo instante."""

    def __init__(self, momento: datetime) -> None:
        self._momento = momento

    def ahora(self) -> datetime:
        return self._momento


class RelojControlado:
    """Reloj con una secuencia de instantes; repite el último."""

    def __init__(self, momentos: list[datetime]) -> None:
        self._momentos = list(momentos)

    def ahora(self) -> datetime:
        if len(self._momentos) > 1:
            return self._momentos.pop(0)
        return self._momentos[0]


class DescargaDoble:
    """Descargador de prueba que devuelve un PDF y anota las llamadas."""

    def __init__(self) -> None:
        self.llamadas: list[str] = []

    def descargar(self, url: str) -> bytes:
        self.llamadas.append(url)
        return CONTENIDO_PDF


class ParseoDoble:
    """Parser de prueba con un recuento fijo de ofertas."""

    def __init__(self, recuento: int = 92) -> None:
        self.recuento = recuento

    def parsear(self, contenido: bytes, comunidad: str) -> RecuentoPDF:
        return RecuentoPDF(recuento=self.recuento, comunidad=comunidad)


class BuscadorDoble:
    """Cliente del estado del buscador con un `total_listado` fijo."""

    def __init__(self, total_listado: int = 93) -> None:
        self.total_listado = total_listado

    def consultar_estado(self) -> EstadoBuscador:
        return EstadoBuscador(
            in_progress=False,
            progreso=None,
            ultima_pasada=UltimaPasada(
                timestamp="2026-11-23T01:00:04",
                comunidad="Cantabria",
                total_listado=self.total_listado,
                error_global="",
            ),
        )


def _purgar(base: str, dias: int, hoy: date) -> list[Path]:
    """Purga de prueba: no toca el disco y no devuelve eliminados."""
    return []


@dataclass
class Piezas:
    """Colaboradores de una tarea de prueba."""

    tarea: TareaIntegridad
    config: ConfigIntegridad
    almacen: AlmacenPDFs
    ejecuciones: IndiceEjecuciones
    descarga: DescargaDoble


def _config(
    tmp_path: Path,
    comunidades: tuple[ComunidadConfigurada, ...] = (CANTABRIA,),
    *,
    hora: int = 2,
    margen: int = 60,
) -> ConfigIntegridad:
    """Configuración de prueba con la ruta base dentro de `tmp_path`."""
    return ConfigIntegridad(
        zona_horaria="Europe/Madrid",
        hora_ejecucion=hora,
        margen_catchup=margen,
        dias_retencion=30,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        ruta_base_pdfs=str(tmp_path / "pdfs"),
        url_base_buscador="http://localhost:8000",
        comunidades=list(comunidades),
    )


def _piezas(
    tmp_path: Path,
    *,
    config: ConfigIntegridad | None = None,
    reloj: RelojFijo | RelojControlado | None = None,
) -> Piezas:
    """Compone la tarea con dobles sobre el directorio temporal."""
    config = config or _config(tmp_path)
    almacen = AlmacenPDFs(config.ruta_base_pdfs, config.zona_horaria)
    ejecuciones = IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria)
    descarga = DescargaDoble()
    tarea = TareaIntegridad(
        config,
        almacen,
        descarga,
        ParseoDoble(),
        BuscadorDoble(),
        ComparadorRecuentos(
            config.tolerancia_absoluta,
            config.tolerancia_relativa_pct,
            config.umbral_cordura,
        ),
        AlmacenAvisos(almacen),
        ejecuciones,
        _purgar,
        reloj=reloj or RelojFijo(AHORA),
    )
    return Piezas(
        tarea=tarea,
        config=config,
        almacen=almacen,
        ejecuciones=ejecuciones,
        descarga=descarga,
    )


def _esperar(condicion, timeout: float = 5.0) -> bool:
    """Espera a que se cumpla una condición, sondeando en intervalos cortos."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


def _meta(veredicto: str) -> MetaDia:
    """Metadatos del día ya resueltos, como los dejaría una ejecución previa."""
    return MetaDia(
        recuento_pdf=92,
        recuento_buscador=93,
        diferencia=1,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        veredicto=veredicto,
    )


# ---------------------------------------------------------------------------
# Decisión de arranque: los cuatro casos (DEC-007)
# ---------------------------------------------------------------------------


def test_accion_arranque_expone_los_cuatro_casos() -> None:
    """La decisión se expresa con las cuatro acciones de DEC-007."""
    assert {accion.value for accion in AccionArranque} == {
        "ninguna",
        "esperar_normal",
        "diferida",
        "inmediata",
    }


@pytest.mark.parametrize(
    ("momento", "esperado"),
    [
        (
            datetime(2026, 11, 23, 1, 59, 59, tzinfo=ZONA),
            AccionArranque.ESPERAR_NORMAL,
        ),
        (
            datetime(2026, 11, 23, 2, 0, 0, tzinfo=ZONA),
            AccionArranque.DIFERIDA,
        ),
        (
            datetime(2026, 11, 23, 2, 30, tzinfo=ZONA),
            AccionArranque.DIFERIDA,
        ),
        (
            datetime(2026, 11, 23, 3, 0, 0, tzinfo=ZONA),
            AccionArranque.DIFERIDA,
        ),
        (
            datetime(2026, 11, 23, 3, 0, 1, tzinfo=ZONA),
            AccionArranque.INMEDIATA,
        ),
        (
            datetime(2026, 11, 23, 12, 0, tzinfo=ZONA),
            AccionArranque.INMEDIATA,
        ),
    ],
)
def test_decidir_arranque_sin_metadatos(
    tmp_path: Path, momento: datetime, esperado: AccionArranque
) -> None:
    """Antes de la hora espera; en la ventana difiere; después ejecuta."""
    piezas = _piezas(tmp_path)

    assert (
        piezas.tarea._decidir_arranque(momento, hay_meta_hoy=False) is esperado
    )


def test_decidir_arranque_respeta_otra_hora_configurada(tmp_path: Path) -> None:
    """Con la hora a las 05:00 la ventana es 05:00-06:00, no 02:00-03:00."""
    config = _config(tmp_path, hora=5, margen=60)
    piezas = _piezas(tmp_path, config=config)

    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 4, 30, tzinfo=ZONA), False
    ) is AccionArranque.ESPERAR_NORMAL
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 5, 30, tzinfo=ZONA), False
    ) is AccionArranque.DIFERIDA
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 6, 30, tzinfo=ZONA), False
    ) is AccionArranque.INMEDIATA


def test_decidir_arranque_interpreta_un_instante_sin_zona(
    tmp_path: Path,
) -> None:
    """Un instante sin zona se interpreta en la zona configurada."""
    piezas = _piezas(tmp_path)

    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 2, 30), hay_meta_hoy=False
    ) is AccionArranque.DIFERIDA
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 1, 30), hay_meta_hoy=False
    ) is AccionArranque.ESPERAR_NORMAL


def test_margen_cero_ejecuta_en_cuanto_pasa_la_hora(tmp_path: Path) -> None:
    """Con `margen_catchup=0`, tras la hora la comprobación es inmediata."""
    config = _config(tmp_path, margen=0)
    piezas = _piezas(tmp_path, config=config)

    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 1, 59, 59, tzinfo=ZONA), False
    ) is AccionArranque.ESPERAR_NORMAL
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 2, 0, 30, tzinfo=ZONA), False
    ) is AccionArranque.INMEDIATA
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 12, 0, tzinfo=ZONA), False
    ) is AccionArranque.INMEDIATA


def test_decidir_arranque_con_meta_de_hoy_no_hace_nada(
    tmp_path: Path,
) -> None:
    """Con el día ya resuelto ninguna hora dispara un adelanto."""
    piezas = _piezas(tmp_path)

    for momento in (
        datetime(2026, 11, 23, 1, 0, tzinfo=ZONA),
        datetime(2026, 11, 23, 2, 0, tzinfo=ZONA),
        datetime(2026, 11, 23, 2, 30, tzinfo=ZONA),
        datetime(2026, 11, 23, 12, 0, tzinfo=ZONA),
    ):
        assert piezas.tarea._decidir_arranque(
            momento, hay_meta_hoy=True
        ) is AccionArranque.NINGUNA


def test_segundos_hasta_catchup_apunta_al_final_del_margen(
    tmp_path: Path,
) -> None:
    """La espera diferida termina en `hora + margen` y nunca es negativa."""
    piezas = _piezas(tmp_path)

    assert piezas.tarea._segundos_hasta_catchup(
        datetime(2026, 11, 23, 2, 30, tzinfo=ZONA)
    ) == pytest.approx(1800.0)
    assert piezas.tarea._segundos_hasta_catchup(
        datetime(2026, 11, 23, 3, 0, tzinfo=ZONA)
    ) == 0.0
    assert piezas.tarea._segundos_hasta_catchup(
        datetime(2026, 11, 23, 12, 0, tzinfo=ZONA)
    ) == 0.0


# ---------------------------------------------------------------------------
# Criterio de "hay meta de hoy": todas las comunidades (DEC-007, ALT-009)
# ---------------------------------------------------------------------------


def test_hay_meta_hoy_exige_todas_las_comunidades(tmp_path: Path) -> None:
    """Basta una comunidad sin metadatos para que el día esté pendiente."""
    config = _config(tmp_path, (CANTABRIA, MADRID))
    piezas = _piezas(tmp_path, config=config)

    assert piezas.tarea._hay_meta_hoy() is False

    piezas.almacen.escribir_meta(CANTABRIA.identificador, HOY, _meta("ok"))
    assert piezas.tarea._hay_meta_hoy() is False

    piezas.almacen.escribir_fallido(
        MADRID.identificador, HOY, "error HTTP 503"
    )
    assert piezas.tarea._hay_meta_hoy() is True


def test_hay_meta_hoy_acepta_los_veredictos_terminales(tmp_path: Path) -> None:
    """`ok`, `concordante`, `divergente` y `fallido` cierran el día."""
    piezas = _piezas(tmp_path)

    for veredicto in ("ok", VEREDICTO_CONCORDANTE, "divergente", "fallido"):
        piezas.almacen.escribir_meta(
            CANTABRIA.identificador, HOY, _meta(veredicto)
        )
        assert piezas.tarea._hay_meta_hoy() is True, veredicto


def test_hay_meta_hoy_no_acepta_un_dia_sin_veredicto(tmp_path: Path) -> None:
    """Un `.meta.json` sin veredicto no se considera día resuelto."""
    piezas = _piezas(tmp_path)
    piezas.almacen.escribir_meta(CANTABRIA.identificador, HOY, MetaDia())

    assert piezas.tarea._hay_meta_hoy() is False


def test_hay_meta_hoy_no_acepta_metadatos_ilegibles(tmp_path: Path) -> None:
    """Un `.meta.json` corrupto no resuelve el día y fuerza la comprobación."""
    piezas = _piezas(tmp_path)
    ruta_meta = piezas.almacen.ruta_meta(CANTABRIA.identificador, HOY)
    ruta_meta.parent.mkdir(parents=True, exist_ok=True)
    ruta_meta.write_text("{no es JSON", encoding="utf-8")

    assert piezas.tarea._hay_meta_hoy() is False


def test_hay_meta_hoy_ignora_los_dias_pasados(tmp_path: Path) -> None:
    """Los metadatos de ayer no cuentan como metadatos de hoy."""
    piezas = _piezas(tmp_path)
    ayer = date(2026, 11, 22)
    piezas.almacen.escribir_meta(CANTABRIA.identificador, ayer, _meta("ok"))

    assert piezas.tarea._hay_meta_hoy() is False


def test_hay_meta_hoy_sin_comunidades_no_hay_nada_que_comprobar(
    tmp_path: Path,
) -> None:
    """Sin comunidades configuradas no queda trabajo pendiente."""
    config = _config(tmp_path, comunidades=())
    piezas = _piezas(tmp_path, config=config)

    assert piezas.tarea._hay_meta_hoy() is True


# ---------------------------------------------------------------------------
# `iniciar()`: antes de la hora, dentro del margen y después (ALT-009)
# ---------------------------------------------------------------------------


def test_iniciar_antes_de_la_hora_solo_espera_la_normal(tmp_path: Path) -> None:
    """Antes de la hora no se adelanta nada y a la hora se dispara la normal."""
    reloj = RelojControlado(
        [
            datetime(2026, 11, 23, 1, 59, 59, 900_000, tzinfo=ZONA),
            datetime(2026, 11, 23, 2, 0, 5, tzinfo=ZONA),
        ]
    )
    piezas = _piezas(tmp_path, reloj=reloj)
    disparos: list[int] = []
    primero = threading.Event()

    def doble() -> None:
        disparos.append(1)
        primero.set()

    piezas.tarea._ejecutar_dia = doble
    piezas.tarea.iniciar()
    try:
        assert primero.wait(timeout=5.0), "no se disparó la ejecución normal"
        assert _esperar(lambda: len(disparos) == 1)
        assert len(disparos) == 1
    finally:
        piezas.tarea.detener()

    assert piezas.descarga.llamadas == []


def test_la_diferida_ejecuta_una_sola_vez_al_llegar_al_margen(
    tmp_path: Path,
) -> None:
    """Dentro de la ventana se ejecuta una única vez, a `hora + margen`."""
    # 02:59:59.9 dentro de [02:00, 03:00]: la ejecución diferida queda a 0.1s.
    reloj = RelojFijo(
        datetime(2026, 11, 23, 2, 59, 59, 900_000, tzinfo=ZONA)
    )
    piezas = _piezas(tmp_path, reloj=reloj)
    disparos: list[int] = []
    ejecutado = threading.Event()

    def doble() -> None:
        disparos.append(1)
        ejecutado.set()

    piezas.tarea._ejecutar_dia = doble
    piezas.tarea.iniciar()
    try:
        assert ejecutado.wait(timeout=5.0), "no llegó la ejecución diferida"
        # Tras la ejecución, la siguiente normal es la de mañana (ALT-009):
        # la diferida no se duplica con la de la hora configurada.
        time.sleep(0.3)
        assert len(disparos) == 1
    finally:
        piezas.tarea.detener()

    assert piezas.descarga.llamadas == []


def test_al_llegar_al_margen_ejecuta_el_dia(tmp_path: Path) -> None:
    """Si al llegar a `hora + margen` sigue sin metadatos, se comprueba el día."""
    reloj = RelojFijo(datetime(2026, 11, 23, 3, 0, 0, tzinfo=ZONA))
    piezas = _piezas(tmp_path, reloj=reloj)

    piezas.tarea.iniciar()
    try:
        assert _esperar(
            lambda: piezas.almacen.ruta_meta(
                CANTABRIA.identificador, HOY
            ).is_file()
        ), "no se comprobó el día al llegar al margen"
    finally:
        piezas.tarea.detener()

    assert piezas.descarga.llamadas == [CANTABRIA.url_pdf]
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    assert lectura.meta.veredicto == VEREDICTO_CONCORDANTE


def test_iniciar_despues_del_margen_ejecuta_de_inmediato(tmp_path: Path) -> None:
    """Después de `hora + margen` sin metadatos la comprobación es inmediata."""
    piezas = _piezas(
        tmp_path, reloj=RelojFijo(datetime(2026, 11, 23, 10, 0, tzinfo=ZONA))
    )

    piezas.tarea.iniciar()
    try:
        assert _esperar(
            lambda: piezas.almacen.ruta_meta(
                CANTABRIA.identificador, HOY
            ).is_file()
        ), "no se ejecutó la comprobación inmediata"
    finally:
        piezas.tarea.detener()

    assert piezas.descarga.llamadas == [CANTABRIA.url_pdf]
    assert not piezas.almacen.ruta_meta(
        CANTABRIA.identificador, date(2026, 11, 22)
    ).exists()


def test_la_recuperacion_no_toca_los_dias_anteriores(tmp_path: Path) -> None:
    """Con días pasados en el árbol y sin metadatos de hoy, solo se hace hoy."""
    piezas = _piezas(
        tmp_path, reloj=RelojFijo(datetime(2026, 11, 23, 10, 0, tzinfo=ZONA))
    )
    ayer = date(2026, 11, 22)
    piezas.almacen.guardar_pdf(
        CANTABRIA.identificador, ayer, b"%PDF-1.4 de ayer", _meta("ok")
    )
    ruta_meta_ayer = piezas.almacen.ruta_meta(CANTABRIA.identificador, ayer)
    ruta_pdf_ayer = piezas.almacen.ruta_pdf(CANTABRIA.identificador, ayer)
    meta_ayer = ruta_meta_ayer.read_bytes()
    pdf_ayer = ruta_pdf_ayer.read_bytes()

    piezas.tarea.iniciar()
    try:
        assert _esperar(
            lambda: piezas.almacen.ruta_meta(
                CANTABRIA.identificador, HOY
            ).is_file()
        )
    finally:
        piezas.tarea.detener()

    # El día de ayer no se reprocesa ni se reescribe (DEC-007: sin backfill).
    assert ruta_meta_ayer.read_bytes() == meta_ayer
    assert ruta_pdf_ayer.read_bytes() == pdf_ayer
    lectura = piezas.ejecuciones.leer()
    assert lectura.es_valido
    assert len(lectura.ejecuciones) == 1
    assert lectura.ejecuciones[0].referencias == [
        {"fecha": HOY.isoformat(), "comunidad": CANTABRIA.identificador}
    ]


def test_iniciar_con_el_dia_ya_procesado_no_reprocesa(tmp_path: Path) -> None:
    """Tras un reinicio, un día ya resuelto no se vuelve a comprobar."""
    piezas = _piezas(
        tmp_path, reloj=RelojFijo(datetime(2026, 11, 23, 10, 0, tzinfo=ZONA))
    )
    piezas.almacen.escribir_meta(CANTABRIA.identificador, HOY, _meta("ok"))
    ruta_meta = piezas.almacen.ruta_meta(CANTABRIA.identificador, HOY)
    meta_previo = ruta_meta.read_bytes()

    assert piezas.tarea._hay_meta_hoy() is True
    assert piezas.tarea._decidir_arranque(
        datetime(2026, 11, 23, 10, 0, tzinfo=ZONA), True
    ) is AccionArranque.NINGUNA

    piezas.tarea.iniciar()
    try:
        time.sleep(0.1)
    finally:
        piezas.tarea.detener()

    assert piezas.descarga.llamadas == []
    assert ruta_meta.read_bytes() == meta_previo
    assert not piezas.ejecuciones.ruta_indice.exists()
