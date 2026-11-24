"""Pruebas unitarias de la tarea diaria de integridad (TASK-012).

Cubren el disparo a la hora configurada sin solapamiento, la idempotencia por
`.meta.json` del día (`ok` y `fallido`), el fallo de descarga y de parseo, el
PDF huérfano, varias comunidades con el veredicto global más grave, el cálculo
del día con la zona configurada, la independencia de las demás tareas
programadas (sin avisos externos) y la cancelación limpia. Todos los dobles
viven en `tmp_path`; el reloj se inyecta y `_ejecutar_dia()` se llama
directamente siempre que se puede, de modo que ninguna prueba duerme de
verdad.
"""

import ast
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from source.api.integridad import task as modulo_task
from source.api.integridad.avisos import AlmacenAvisos
from source.api.integridad.buscador_client import (
    EstadoBuscador,
    EstadoBuscadorNoUtilizable,
    UltimaPasada,
)
from source.api.integridad.comparador import ComparadorRecuentos
from source.api.integridad.config import ConfigIntegridad
from source.api.integridad.downloader_adapter import ErrorDescargaIntegridad
from source.api.integridad.ejecuciones import IndiceEjecuciones
from source.api.integridad.parser_adapter import (
    ErrorParseoIntegridad,
    RecuentoPDF,
)
from source.api.integridad.pdf_store import (
    VEREDICTO_CONCORDANTE,
    VEREDICTO_DIVERGENTE,
    VEREDICTO_FALLIDO,
    AlmacenPDFs,
    MetaDia,
)
from source.api.integridad.task import RelojReal, ResultadoDia, TareaIntegridad
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


class RelojControlado:
    """Reloj con una secuencia de instantes; repite el último."""

    def __init__(self, momentos: list[datetime]) -> None:
        self._momentos = list(momentos)

    def ahora(self) -> datetime:
        if len(self._momentos) > 1:
            return self._momentos.pop(0)
        return self._momentos[0]


class DescargaDoble:
    """Descargador de prueba que devuelve bytes o un error controlado."""

    def __init__(
        self,
        resultado: bytes | ErrorDescargaIntegridad = CONTENIDO_PDF,
    ) -> None:
        self.resultado = resultado
        self.llamadas: list[str] = []
        self.antes_de_responder = None

    def descargar(self, url: str) -> bytes | ErrorDescargaIntegridad:
        self.llamadas.append(url)
        if self.antes_de_responder is not None:
            self.antes_de_responder()
        return self.resultado


class ParseoDoble:
    """Parser de prueba con recuento por comunidad y errores por comunidad."""

    def __init__(
        self,
        recuento: int | dict[str, int] = 92,
        errores: dict[str, str] | None = None,
    ) -> None:
        self.recuento = recuento
        self.errores = errores or {}
        self.llamadas: list[str] = []

    def parsear(
        self, contenido: bytes, comunidad: str
    ) -> RecuentoPDF | ErrorParseoIntegridad:
        self.llamadas.append(comunidad)
        if comunidad in self.errores:
            return ErrorParseoIntegridad(motivo=self.errores[comunidad])
        valor = (
            self.recuento.get(comunidad, 0)
            if isinstance(self.recuento, dict)
            else self.recuento
        )
        return RecuentoPDF(recuento=valor, comunidad=comunidad)


class BuscadorDoble:
    """Cliente del estado del buscador con un total o un estado no utilizable."""

    def __init__(self, total_listado: int = 93, motivo: str = "") -> None:
        self.total_listado = total_listado
        self.motivo = motivo
        self.llamadas = 0

    def consultar_estado(self) -> EstadoBuscador | EstadoBuscadorNoUtilizable:
        self.llamadas += 1
        if self.motivo:
            return EstadoBuscadorNoUtilizable(motivo=self.motivo)
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


class PurgaDoble:
    """Purga de prueba que solo anota con qué argumentos se la llamó."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, int, date]] = []

    def __call__(self, base: str, dias: int, hoy: date) -> list[Path]:
        self.llamadas.append((base, dias, hoy))
        return []


@dataclass
class Piezas:
    """Colaboradores usados por una tarea de prueba."""

    tarea: TareaIntegridad
    config: ConfigIntegridad
    almacen: AlmacenPDFs
    avisos: AlmacenAvisos
    ejecuciones: IndiceEjecuciones
    descarga: DescargaDoble
    parseo: ParseoDoble
    buscador: BuscadorDoble
    purga: PurgaDoble = field(default_factory=PurgaDoble)


def _config(
    tmp_path: Path,
    comunidades: tuple[ComunidadConfigurada, ...] = (CANTABRIA,),
    *,
    zona_horaria: str = "Europe/Madrid",
) -> ConfigIntegridad:
    """Configuración de prueba con la ruta base dentro de `tmp_path`."""
    return ConfigIntegridad(
        zona_horaria=zona_horaria,
        hora_ejecucion=2,
        margen_catchup=60,
        dias_retencion=30,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        ruta_base_pdfs=str(tmp_path / "pdfs"),
        url_base_buscador="http://localhost:8000",
        comunidades=list(comunidades),
    )


def _tarea(
    tmp_path: Path,
    *,
    config: ConfigIntegridad | None = None,
    descarga: DescargaDoble | None = None,
    parseo: ParseoDoble | None = None,
    buscador: BuscadorDoble | None = None,
    reloj: RelojControlado | None = None,
    purga: PurgaDoble | None = None,
) -> Piezas:
    """Compone la tarea con dobles sobre el directorio temporal."""
    config = config or _config(tmp_path)
    almacen = AlmacenPDFs(config.ruta_base_pdfs, config.zona_horaria)
    avisos = AlmacenAvisos(almacen)
    ejecuciones = IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria)
    piezas = Piezas(
        tarea=None,
        config=config,
        almacen=almacen,
        avisos=avisos,
        ejecuciones=ejecuciones,
        descarga=descarga or DescargaDoble(),
        parseo=parseo or ParseoDoble(),
        buscador=buscador or BuscadorDoble(),
        purga=purga or PurgaDoble(),
    )
    piezas.tarea = TareaIntegridad(
        config,
        almacen,
        piezas.descarga,
        piezas.parseo,
        piezas.buscador,
        ComparadorRecuentos(
            config.tolerancia_absoluta,
            config.tolerancia_relativa_pct,
            config.umbral_cordura,
        ),
        avisos,
        ejecuciones,
        piezas.purga,
        reloj=reloj or RelojControlado([AHORA]),
    )
    return piezas


def _esperar(condicion, timeout: float = 5.0) -> bool:
    """Espera a que se cumpla una condición, sondeando en intervalos cortos."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


def _ejecuciones_guardadas(piezas: Piezas) -> list:
    """Ejecuciones leídas del índice, sin filtrar por la fecha real."""
    lectura = piezas.ejecuciones.leer()
    assert lectura.es_valido
    return lectura.ejecuciones


# ---------------------------------------------------------------------------
# Programación: disparo a la hora configurada (NFR-001, DEC-006)
# ---------------------------------------------------------------------------


def test_segundos_hasta_proxima_usa_la_hora_configurada(
    tmp_path: Path,
) -> None:
    """La espera apunta a la hora entera configurada, no a otra (NFR-001)."""
    piezas = _tarea(tmp_path)

    assert piezas.tarea._segundos_hasta_proxima(
        datetime(2026, 11, 23, 1, 0, tzinfo=ZONA)
    ) == pytest.approx(3600.0)
    assert piezas.tarea._segundos_hasta_proxima(
        datetime(2026, 11, 23, 10, 0, tzinfo=ZONA)
    ) == pytest.approx(16 * 3600.0)


def test_segundos_hasta_proxima_respeta_otra_hora_configurada(
    tmp_path: Path,
) -> None:
    """Con la hora a las 05:00 la espera no apunta a las 02:00 (NFR-001)."""
    config = _config(tmp_path)
    config.hora_ejecucion = 5
    piezas = _tarea(tmp_path, config=config)

    assert piezas.tarea._segundos_hasta_proxima(
        datetime(2026, 11, 23, 2, 0, tzinfo=ZONA)
    ) == pytest.approx(3 * 3600.0)


def test_se_dispara_una_vez_al_llegar_la_hora(tmp_path: Path) -> None:
    """El hilo se dispara al vencer la espera y solo una vez (DEC-006)."""
    reloj = RelojControlado(
        [
            datetime(2026, 11, 23, 1, 59, 59, 900_000, tzinfo=ZONA),
            datetime(2026, 11, 23, 2, 0, 5, tzinfo=ZONA),
        ]
    )
    piezas = _tarea(tmp_path, reloj=reloj)
    disparos: list[int] = []
    primero = threading.Event()

    def doble() -> None:
        disparos.append(1)
        primero.set()

    piezas.tarea._ejecutar_dia = doble
    piezas.tarea.iniciar()
    try:
        assert primero.wait(timeout=5.0), "no se disparó a la hora configurada"
        assert _esperar(lambda: len(disparos) == 1)
        assert len(disparos) == 1
    finally:
        piezas.tarea.detener()

    assert piezas.tarea._hilo is not None
    assert not piezas.tarea._hilo.is_alive()


def test_no_se_solapa_con_una_ejecucion_en_curso(tmp_path: Path) -> None:
    """Un segundo disparo durante la ejecución se omite (DEC-006)."""
    estado: dict = {"tarea": None, "anidado": "sin llamar"}
    descarga = DescargaDoble()

    def reentrar() -> None:
        estado["anidado"] = estado["tarea"]._ejecutar_dia()

    descarga.antes_de_responder = reentrar
    piezas = _tarea(tmp_path, descarga=descarga)
    estado["tarea"] = piezas.tarea

    resultado = piezas.tarea._ejecutar_dia()

    assert estado["anidado"] is None
    assert descarga.llamadas == [CANTABRIA.url_pdf]
    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_CONCORDANTE


def test_detener_cancela_el_hilo_sin_ejecutar(tmp_path: Path) -> None:
    """`detener()` corta la espera y no deja ejecuciones en curso."""
    piezas = _tarea(tmp_path)  # reloj a las 02:30: la próxima es mañana
    disparos: list[int] = []

    def doble() -> None:
        disparos.append(1)

    piezas.tarea._ejecutar_dia = doble
    piezas.tarea.iniciar()
    assert _esperar(lambda: piezas.tarea._hilo is not None)

    inicio = time.monotonic()
    piezas.tarea.detener()
    transcurrido = time.monotonic() - inicio

    assert transcurrido < 5.0
    assert not piezas.tarea._hilo.is_alive()
    assert disparos == []
    assert piezas.descarga.llamadas == []


def test_reloj_real_devuelve_el_instante_en_la_zona(tmp_path: Path) -> None:
    """`RelojReal` devuelve un datetime aware en la zona configurada."""
    ahora = RelojReal("Pacific/Kiritimati").ahora()

    assert ahora.tzinfo is not None
    assert ahora.utcoffset() is not None
    assert str(ahora.tzinfo) == "Pacific/Kiritimati"


# ---------------------------------------------------------------------------
# Idempotencia por el .meta.json del día (ALT-001, ALT-002, NFR-003)
# ---------------------------------------------------------------------------


def _meta_completo(veredicto: str) -> MetaDia:
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


def test_meta_ok_de_hoy_omite_descarga_parseo_y_comparacion(
    tmp_path: Path,
) -> None:
    """Con el día ya `ok` no se descarga, ni parsea, ni compara (ALT-001)."""
    piezas = _tarea(tmp_path)
    piezas.almacen.escribir_meta(
        CANTABRIA.identificador, HOY, _meta_completo("ok")
    )

    primero = piezas.tarea._ejecutar_dia()
    segundo = piezas.tarea._ejecutar_dia()

    assert piezas.descarga.llamadas == []
    assert piezas.parseo.llamadas == []
    assert piezas.buscador.llamadas == 0
    assert primero is not None and segundo is not None
    assert primero.veredicto_global == VEREDICTO_CONCORDANTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    assert lectura.meta.veredicto == "ok"
    assert lectura.meta.avisos == []


def test_meta_fallido_de_hoy_no_reintenta(tmp_path: Path) -> None:
    """Un día ya `fallido` no se reintenta y el veredicto permanece (ALT-002)."""
    piezas = _tarea(tmp_path)
    piezas.almacen.escribir_fallido(
        CANTABRIA.identificador, HOY, "error HTTP 503"
    )

    resultado = piezas.tarea._ejecutar_dia()

    assert piezas.descarga.llamadas == []
    assert piezas.parseo.llamadas == []
    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_FALLIDO
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.meta.veredicto == VEREDICTO_FALLIDO
    assert lectura.meta.errores == ["error HTTP 503"]


# ---------------------------------------------------------------------------
# Fallos de descarga y de parseo (ALT-003, DEC-002, REQ-007)
# ---------------------------------------------------------------------------


def test_descarga_en_error_deja_el_dia_fallido_sin_pdf_y_con_aviso(
    tmp_path: Path,
) -> None:
    """Una descarga fallida deja `fallido`, sin PDF y con aviso (ALT-003)."""
    descarga = DescargaDoble(
        ErrorDescargaIntegridad(mensaje="error HTTP 503")
    )
    piezas = _tarea(tmp_path, descarga=descarga)

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_FALLIDO
    assert not piezas.almacen.ruta_pdf(CANTABRIA.identificador, HOY).exists()
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    assert lectura.meta.veredicto == VEREDICTO_FALLIDO
    assert "error HTTP 503" in lectura.meta.errores[0]
    assert len(lectura.meta.avisos) == 1
    aviso = lectura.meta.avisos[0]
    assert aviso["comunidad"] == CANTABRIA.identificador
    assert aviso["fecha"] == HOY.isoformat()
    assert "error HTTP 503" in aviso["motivo"]
    assert piezas.parseo.llamadas == []
    assert piezas.buscador.llamadas == 0


def test_parseo_en_error_conserva_el_pdf_y_deja_fallido(
    tmp_path: Path,
) -> None:
    """Un parseo fallido conserva el PDF y marca el día `fallido` (DEC-002)."""
    parseo = ParseoDoble(errores={CANTABRIA.identificador: "PDF ilegible"})
    piezas = _tarea(tmp_path, parseo=parseo)

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_FALLIDO
    ruta_pdf = piezas.almacen.ruta_pdf(CANTABRIA.identificador, HOY)
    assert ruta_pdf.is_file()
    assert ruta_pdf.read_bytes() == CONTENIDO_PDF
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.meta.veredicto == VEREDICTO_FALLIDO
    assert any("PDF ilegible" in error for error in lectura.meta.errores)
    assert lectura.meta.hash
    assert len(lectura.meta.avisos) == 1
    assert piezas.buscador.llamadas == 0


# ---------------------------------------------------------------------------
# Día completo y PDF huérfano (ALT-007, REQ-005)
# ---------------------------------------------------------------------------


def test_comparacion_correcta_completa_el_meta_y_registra_la_ejecucion(
    tmp_path: Path,
) -> None:
    """Un día normal deja recuentos, umbrales, veredicto y ejecución."""
    piezas = _tarea(tmp_path)

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.fecha == HOY
    assert resultado.veredicto_global == VEREDICTO_CONCORDANTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    meta = lectura.meta
    assert meta.veredicto == VEREDICTO_CONCORDANTE
    assert meta.recuento_pdf == 92
    assert meta.recuento_buscador == 93
    assert meta.diferencia == 1
    assert meta.tolerancia_absoluta == 1
    assert meta.tolerancia_relativa_pct == 5
    assert meta.umbral_cordura == 70
    assert meta.hash
    assert meta.timestamp
    assert meta.avisos == []

    ejecuciones = _ejecuciones_guardadas(piezas)
    assert len(ejecuciones) == 1
    ejecucion = ejecuciones[0]
    assert ejecucion.resultado_global == "ok"
    assert ejecucion.veredicto_agregado == VEREDICTO_CONCORDANTE
    assert ejecucion.referencias == [
        {"fecha": HOY.isoformat(), "comunidad": CANTABRIA.identificador}
    ]
    assert ejecucion.errores_por_comunidad == []
    assert ejecucion.timestamp
    assert piezas.purga.llamadas == [
        (piezas.config.ruta_base_pdfs, 30, HOY)
    ]


def test_divergencia_deja_el_dia_divergente_y_registra_el_aviso(
    tmp_path: Path,
) -> None:
    """Unos recuentos fuera de tolerancia generan aviso (REQ-004, REQ-007)."""
    piezas = _tarea(tmp_path, parseo=ParseoDoble(recuento=80))

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_DIVERGENTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.meta.veredicto == VEREDICTO_DIVERGENTE
    assert len(lectura.meta.avisos) == 1
    aviso = lectura.meta.avisos[0]
    assert aviso["recuento_pdf"] == 80
    assert aviso["total_listado"] == 93
    assert aviso["diferencia"] == 13
    assert aviso["umbral_cordura"] == 70


def test_pdf_sin_meta_se_reprocesa_y_completa_el_dia(
    tmp_path: Path,
) -> None:
    """Un PDF huérfano se reparsea sin descargar y regenera su meta (ALT-007)."""
    piezas = _tarea(tmp_path)
    ruta_pdf = piezas.almacen.ruta_pdf(CANTABRIA.identificador, HOY)
    ruta_pdf.parent.mkdir(parents=True, exist_ok=True)
    ruta_pdf.write_bytes(CONTENIDO_PDF)

    resultado = piezas.tarea._ejecutar_dia()

    assert piezas.descarga.llamadas == []
    assert piezas.parseo.llamadas == [CANTABRIA.identificador]
    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_CONCORDANTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    assert lectura.meta.veredicto == VEREDICTO_CONCORDANTE
    assert lectura.meta.recuento_pdf == 92
    assert len(lectura.meta.hash) == 64
    assert ruta_pdf.read_bytes() == CONTENIDO_PDF


def test_meta_ilegible_con_pdf_se_regenera(tmp_path: Path) -> None:
    """Un `.meta.json` corrupto con PDF presente se regenera (ALT-007)."""
    piezas = _tarea(tmp_path)
    ruta_pdf = piezas.almacen.ruta_pdf(CANTABRIA.identificador, HOY)
    ruta_pdf.parent.mkdir(parents=True, exist_ok=True)
    ruta_pdf.write_bytes(CONTENIDO_PDF)
    piezas.almacen.ruta_meta(CANTABRIA.identificador, HOY).write_text(
        "{no es JSON", encoding="utf-8"
    )

    resultado = piezas.tarea._ejecutar_dia()

    assert piezas.descarga.llamadas == []
    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_CONCORDANTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.es_valido
    assert lectura.meta.recuento_pdf == 92


# ---------------------------------------------------------------------------
# Varias comunidades (ALT-008) y errores inesperados
# ---------------------------------------------------------------------------


def test_dos_comunidades_tienen_su_meta_y_el_global_es_el_mas_grave(
    tmp_path: Path,
) -> None:
    """Cada comunidad deja su `.meta.json` y el global es el más grave."""
    config = _config(tmp_path, (CANTABRIA, MADRID))
    parseo = ParseoDoble(errores={MADRID.identificador: "PDF ilegible"})
    piezas = _tarea(tmp_path, config=config, parseo=parseo)

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredictos_por_comunidad == {
        CANTABRIA.identificador: VEREDICTO_CONCORDANTE,
        MADRID.identificador: VEREDICTO_FALLIDO,
    }
    assert resultado.veredicto_global == VEREDICTO_FALLIDO
    for comunidad in (CANTABRIA, MADRID):
        lectura = piezas.almacen.leer_meta(comunidad.identificador, HOY)
        assert lectura.es_valido
        assert (
            piezas.almacen.ruta_meta(comunidad.identificador, HOY)
        ).is_file()
    assert piezas.descarga.llamadas == [CANTABRIA.url_pdf, MADRID.url_pdf]
    ejecuciones = _ejecuciones_guardadas(piezas)
    assert len(ejecuciones) == 1
    assert ejecuciones[0].veredicto_agregado == VEREDICTO_FALLIDO
    assert ejecuciones[0].referencias == [
        {"fecha": HOY.isoformat(), "comunidad": CANTABRIA.identificador},
        {"fecha": HOY.isoformat(), "comunidad": MADRID.identificador},
    ]


def test_el_global_es_divergente_si_una_comunidad_diverge(
    tmp_path: Path,
) -> None:
    """`divergente` pesa más que `concordante` en el global (ALT-008)."""
    config = _config(tmp_path, (CANTABRIA, MADRID))
    parseo = ParseoDoble(recuento={CANTABRIA.identificador: 92, "madrid": 40})
    piezas = _tarea(tmp_path, config=config, parseo=parseo)

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_DIVERGENTE
    assert resultado.veredictos_por_comunidad[MADRID.identificador] == (
        VEREDICTO_DIVERGENTE
    )


def test_una_excepcion_de_una_comunidad_no_tumba_las_demas(
    tmp_path: Path,
) -> None:
    """Una excepción inesperada se anota y las demás comunidades siguen."""
    config = _config(tmp_path, (CANTABRIA, MADRID))

    class DescargaQueFalla(DescargaDoble):
        def descargar(self, url: str):
            if url == CANTABRIA.url_pdf:
                raise RuntimeError("disco lleno")
            return super().descargar(url)

    piezas = _tarea(
        tmp_path, config=config, descarga=DescargaQueFalla()
    )

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredictos_por_comunidad[CANTABRIA.identificador] == (
        VEREDICTO_FALLIDO
    )
    assert resultado.veredictos_por_comunidad[MADRID.identificador] == (
        VEREDICTO_CONCORDANTE
    )
    assert resultado.errores_por_comunidad[0]["comunidad"] == (
        CANTABRIA.identificador
    )
    assert "disco lleno" in resultado.errores_por_comunidad[0]["mensaje"]
    ejecuciones = _ejecuciones_guardadas(piezas)
    assert ejecuciones[0].resultado_global == "parcial"
    assert ejecuciones[0].errores_por_comunidad[0]["comunidad"] == (
        CANTABRIA.identificador
    )


def test_buscador_no_utilizable_deja_el_dia_no_concordante(
    tmp_path: Path,
) -> None:
    """Sin estado del buscador el veredicto nunca es concordante (ALT-005)."""
    piezas = _tarea(tmp_path, buscador=BuscadorDoble(motivo="sin ultima_pasada"))

    resultado = piezas.tarea._ejecutar_dia()

    assert resultado is not None
    assert resultado.veredicto_global == VEREDICTO_DIVERGENTE
    lectura = piezas.almacen.leer_meta(CANTABRIA.identificador, HOY)
    assert lectura.meta.veredicto == VEREDICTO_DIVERGENTE
    assert len(lectura.meta.avisos) == 1


# ---------------------------------------------------------------------------
# Zona horaria configurada (NFR-004)
# ---------------------------------------------------------------------------


def test_el_dia_se_calcula_con_la_zona_configurada(tmp_path: Path) -> None:
    """El día sale de la zona configurada y no de la del sistema (NFR-004)."""
    config = _config(tmp_path, zona_horaria="Pacific/Kiritimati")
    reloj = RelojControlado(
        [datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)]
    )
    piezas = _tarea(tmp_path, config=config, reloj=reloj)

    resultado = piezas.tarea._ejecutar_dia()

    # UTC 12:00 del 23 es 02:00 del 24 en Pacific/Kiritimati (+14).
    assert resultado is not None
    assert resultado.fecha == date(2026, 11, 24)
    assert (
        piezas.almacen.ruta_meta(CANTABRIA.identificador, date(2026, 11, 24))
    ).is_file()
    assert not piezas.almacen.ruta_meta(
        CANTABRIA.identificador, date(2026, 11, 23)
    ).exists()


# ---------------------------------------------------------------------------
# Independencia de las demás tareas y sin avisos externos (SUP-004, SUP-007)
# ---------------------------------------------------------------------------

_PREFIJOS_PROHIBIDOS = (
    "source.api.buscador",
    "source.api.persistencia",
    "source.api.historico",
    "sqlite3",
    "telegram",
    "telebot",
    "smtplib",
)


def _modulos_importados(arbol: ast.AST) -> set[str]:
    """Nombres de todos los módulos importados por un módulo Python."""
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            nombres.add(nodo.module)
            nombres.update(
                f"{nodo.module}.{alias.name}" for alias in nodo.names
            )
    return nombres


def test_la_tarea_no_importa_otros_modulos_ni_canales_externos() -> None:
    """No importa buscador, persistencia, histórico, SQLite ni Telegram."""
    fuente = Path(modulo_task.__file__).read_text(encoding="utf-8")
    importados = _modulos_importados(ast.parse(fuente))

    for nombre in importados:
        for prefijo in _PREFIJOS_PROHIBIDOS:
            assert not (
                nombre == prefijo or nombre.startswith(prefijo + ".")
            ), f"la tarea de integridad no debe importar '{prefijo}': {nombre}"


def test_la_tarea_no_importa_el_descargador_ni_el_parser() -> None:
    """La descarga y el parseo se invocan a través de sus adaptadores."""
    fuente = Path(modulo_task.__file__).read_text(encoding="utf-8")
    importados = _modulos_importados(ast.parse(fuente))

    assert "source.api.downloader" not in importados
    assert "source.api.parser" not in importados


def test_la_tarea_expone_los_adaptadores_del_subpaquete() -> None:
    """La tarea orquesta los componentes del propio subpaquete de integridad."""
    fuente = Path(modulo_task.__file__).read_text(encoding="utf-8")
    importados = _modulos_importados(ast.parse(fuente))

    for modulo in (
        "source.api.integridad.avisos",
        "source.api.integridad.buscador_client",
        "source.api.integridad.comparador",
        "source.api.integridad.downloader_adapter",
        "source.api.integridad.ejecuciones",
        "source.api.integridad.parser_adapter",
        "source.api.integridad.pdf_store",
    ):
        assert modulo in importados


# ---------------------------------------------------------------------------
# Resultado del día y utilidades
# ---------------------------------------------------------------------------


def test_resultado_dia_por_defecto_no_tiene_errores() -> None:
    """El resultado nace en `concordante` y sin errores por comunidad."""
    resultado = ResultadoDia(fecha=HOY)

    assert resultado.veredicto_global == VEREDICTO_CONCORDANTE
    assert resultado.veredictos_por_comunidad == {}
    assert resultado.errores_por_comunidad == []
    assert resultado.referencias == []


def test_veredicto_mas_grave_ordena_por_gravedad() -> None:
    """`fallido` pesa más que `divergente`, y este más que `concordante`."""
    assert modulo_task._veredicto_mas_grave(
        [VEREDICTO_CONCORDANTE, VEREDICTO_DIVERGENTE]
    ) == VEREDICTO_DIVERGENTE
    assert modulo_task._veredicto_mas_grave(
        [VEREDICTO_DIVERGENTE, VEREDICTO_FALLIDO, VEREDICTO_CONCORDANTE]
    ) == VEREDICTO_FALLIDO
    assert modulo_task._veredicto_mas_grave([]) == VEREDICTO_CONCORDANTE
