"""Verificación de integración de extremo a extremo de la integridad (TASK-018).

Montan la aplicación real de ``source/api/main.py`` con ``TestClient`` y un
entorno temporal (configuraciones de persistencia, histórico e integridad y
ruta base de PDFs en ``tmp_path``). Sólo se sustituyen los dobles externos
permitidos por la ficha:

- el cliente HTTP de ``GET /buscador/status``, con un ``httpx.MockTransport``;
- el descargador y el parser del PDF, con dobles en proceso inyectados en los
  adaptadores reales;
- la ruta base de PDFs, que apunta a ``tmp_path``;
- el reloj de la tarea diaria, con un reloj fijo controlado.

Con eso se recorre la cadena completa (configuración, almacén, adaptadores,
comparador, avisos, índice de ejecuciones, tarea diaria, purga y los tres
endpoints de consulta) sin ninguna petición de red real ni escritura en
``data/pdfs``. Se cubren la concordancia, la divergencia por tolerancia y por
umbral, el fallo de descarga y de parseo, el buscador sin datos, la doble
ejecución diaria, el día fallido previo, el arranque dentro del margen de
catch-up, la purga por antigüedad y la no regresión sobre ``data/job_emcan.db``
(SUP-003) y sobre la ausencia de SQLite propio (DEC-001).
"""

import hashlib
import importlib
import time
from dataclasses import dataclass
from datetime import date, datetime, time as hora_del_dia, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from source.api.buscador.scheduler import Scheduler
from source.api.downloader import ErrorDescarga
from source.api.historico.task import TareaHistorico
from source.api.integridad import task as task_mod
from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia
from source.api.integridad.task import TareaIntegridad
from source.api.parser import ErrorParseoPDF
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga

ZONA = ZoneInfo("Europe/Madrid")

# La fecha del día se toma de la real: los endpoints calculan "hoy" con
# `datetime.now(zona)` y así la recomendación de cierre resulta coherente sin
# parchear el reloj de la propia API.
HOY: date = datetime.now(ZONA).date()

# Instante controlado de la tarea en los escenarios de veredicto: después de la
# hora configurada (02:00) y de su margen (03:00), así el día es "hoy".
AHORA = datetime.combine(HOY, hora_del_dia(10, 0), tzinfo=ZONA)

# Instante dentro de la ventana de catch-up [02:00, 03:00]: la ejecución
# diferida queda a 0,5 s de espera real y se dispara una sola vez.
MOMENTO_CATCHUP = datetime.combine(
    HOY, hora_del_dia(2, 59, 59, 500_000), tzinfo=ZONA
)

CONTENIDO_PDF = b"%PDF-1.4 contenido simulado del PDF de difusion de prueba"
RUTA_BD_REAL = Path("data/job_emcan.db")
ESPERA_MAXIMA = 5.0


# ---------------------------------------------------------------------------
# Dobles externos permitidos
# ---------------------------------------------------------------------------


class RelojFijo:
    """Reloj de prueba que devuelve siempre el mismo instante."""

    def __init__(self, momento: datetime) -> None:
        self._momento = momento

    def ahora(self) -> datetime:
        """Devuelve el instante fijo configurado."""
        return self._momento


class DescargaDoble:
    """Descargador del PDF simulado, con el mismo contrato que el real.

    ``AdaptadorDescarga`` invoca ``descargador(url, cliente=...)`` y distingue
    ``ErrorDescarga``; el doble respeta esa firma y anota cada llamada.
    """

    def __init__(self) -> None:
        self.resultado: bytes | ErrorDescarga = CONTENIDO_PDF
        self.llamadas: list[str] = []

    def __call__(
        self, url: str, *, cliente: httpx.Client | None = None
    ) -> bytes | ErrorDescarga:
        """Devuelve el resultado configurado y anota la URL solicitada."""
        self.llamadas.append(url)
        return self.resultado


class ParseoDoble:
    """Parser del PDF simulado, compuesto por texto y ofertas como el real.

    ``AdaptadorParseo`` llama primero al extractor de texto (que puede lanzar
    ``ErrorParseoPDF``) y después al extractor de ofertas.
    """

    def __init__(self) -> None:
        self.recuento: int = 92
        self.error: str = ""
        self.texto_llamadas: list[int] = []
        self.ofertas_llamadas: list[str] = []

    def texto(self, contenido: bytes) -> str:
        """Devuelve un texto ficticio o lanza el error de parseo configurado."""
        self.texto_llamadas.append(len(contenido))
        if self.error:
            raise ErrorParseoPDF(self.error)
        return "texto simulado del PDF de difusión"

    def ofertas(self, texto: str, comunidad: str = "") -> list:
        """Devuelve tantas ofertas como indique el recuento configurado."""
        self.ofertas_llamadas.append(comunidad)
        return list(range(self.recuento))


def _estado_buscador_ok(total: int) -> dict:
    """Cuerpo real de ``GET /buscador/status`` con una pasada correcta."""
    return {
        "in_progress": False,
        "progreso": 100,
        "ultima_pasada": {
            "timestamp": f"{HOY.isoformat()}T01:30:00+01:00",
            "comunidad": "Cantabria",
            "total_listado": total,
            "error_global": "",
            "errores_por_oferta": [],
        },
    }


# ---------------------------------------------------------------------------
# Entorno temporal
# ---------------------------------------------------------------------------


@dataclass
class Entorno:
    """Rutas y dobles del entorno de prueba dentro de ``tmp_path``."""

    tmp_path: Path
    pdfs_dir: Path
    seen_codes_path: Path
    config_persistencia_path: Path
    config_historico_path: Path
    config_integridad_path: Path
    reloj: RelojFijo
    descarga: DescargaDoble
    parseo: ParseoDoble
    estado_buscador: dict
    cliente_http: httpx.Client
    peticiones: list[str]


def _crear_entorno(tmp_path: Path, momento: datetime) -> Entorno:
    """Crea configuraciones y dobles temporales para montar la app real."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    pdfs_dir = data_dir / "pdfs"

    ruta_bd = str(data_dir / "persistencia.db")
    ruta_bd_historico = str(data_dir / "historico.db")

    seen_codes_path = data_dir / "seen_codes.json"
    seen_codes_path.write_text("[]", encoding="utf-8")

    config_persistencia = config_dir / "persistencia.yaml"
    config_persistencia.write_text(
        "base_de_datos:\n"
        f"  ruta: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "ingesta:\n"
        "  cadencia_segundos: 3600\n"
        "purga:\n"
        "  dias_retencion: 7\n"
        "  frecuencia_segundos: 86400\n",
        encoding="utf-8",
    )

    config_historico = config_dir / "historico.yaml"
    config_historico.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "ausencias_consecutivas: 2\n"
        "umbral_caida_pct: 30\n"
        "recuento_minimo: 70\n"
        "rutas:\n"
        f"  sqlite_historico: {ruta_bd_historico}\n"
        f"  sqlite_persistencia: {ruta_bd}\n"
        "buscador:\n"
        "  url_base: http://localhost:19999\n"
        "persistencia:\n"
        "  url_base: http://localhost:19999\n"
        "pdf:\n"
        "  comunidad: Cantabria\n"
        "  identificador: cantabria\n",
        encoding="utf-8",
    )

    config_integridad = config_dir / "integridad.yaml"
    config_integridad.write_text(
        "zona_horaria: Europe/Madrid\n"
        "hora_ejecucion: 2\n"
        "margen_catchup: 60\n"
        "dias_retencion: 30\n"
        "tolerancia_absoluta: 1\n"
        "tolerancia_relativa_pct: 5\n"
        "umbral_cordura: 70\n"
        "rutas:\n"
        f"  base_pdfs: {pdfs_dir}\n"
        "buscador:\n"
        "  url_base: http://testserver\n"
        "comunidades:\n"
        "  - identificador: cantabria\n"
        "    url_pdf: http://testserver/cantabria.pdf\n",
        encoding="utf-8",
    )

    estado_buscador = {"cuerpo": _estado_buscador_ok(93)}
    peticiones: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Responde sólo ``GET /buscador/status`` desde el cuerpo mutable."""
        peticiones.append(request.url.path)
        if request.url.path != "/buscador/status":
            return httpx.Response(
                404, json={"detail": f"ruta no simulada: {request.url.path}"}
            )
        return httpx.Response(200, json=estado_buscador["cuerpo"])

    cliente_http = httpx.Client(transport=httpx.MockTransport(handler))

    return Entorno(
        tmp_path=tmp_path,
        pdfs_dir=pdfs_dir,
        seen_codes_path=seen_codes_path,
        config_persistencia_path=config_persistencia,
        config_historico_path=config_historico,
        config_integridad_path=config_integridad,
        reloj=RelojFijo(momento),
        descarga=DescargaDoble(),
        parseo=ParseoDoble(),
        estado_buscador=estado_buscador,
        cliente_http=cliente_http,
        peticiones=peticiones,
    )


def _parchear(monkeypatch, entorno: Entorno) -> None:
    """Aplica los parches de configuración, tareas y dobles externos."""
    from source.api.buscador.models import ConfigBuscador

    config_buscador = ConfigBuscador(
        ruta_seen_codes=str(entorno.seen_codes_path),
    )
    monkeypatch.setattr(
        "source.api.buscador.config.cargar_configuracion",
        lambda: config_buscador,
    )
    monkeypatch.setattr(
        "source.api.persistencia.config.DEFAULT_CONFIG_PATH",
        entorno.config_persistencia_path,
    )
    monkeypatch.setattr(
        "source.api.historico.config.DEFAULT_CONFIG_PATH",
        entorno.config_historico_path,
    )
    monkeypatch.setattr(
        "source.api.integridad.config.DEFAULT_CONFIG_PATH",
        entorno.config_integridad_path,
    )

    # Las demás tareas siguen vivas en el proceso, pero no ejecutan trabajo
    # real: ni peticiones HTTP, ni escrituras en sus bases de datos.
    monkeypatch.setattr(Scheduler, "iniciar", lambda self: None)
    monkeypatch.setattr(TareaIngesta, "_ejecutar_ciclo", lambda self: None)
    monkeypatch.setattr(
        TareaPurga, "_ejecutar_purga_si_posible", lambda self: None
    )
    monkeypatch.setattr(
        TareaHistorico, "ejecutar_cierre_diario", lambda self: None
    )
    monkeypatch.setattr(
        TareaHistorico,
        "_esperar_hora_configurada",
        lambda self: self._evento_parada.wait(timeout=0.05),
    )

    # El reloj lo consulta la propia tarea: se sustituye en su módulo.
    monkeypatch.setattr(task_mod, "RelojReal", lambda zona: entorno.reloj)


def _parchear_dobles_de_main(monkeypatch, main_mod, entorno: Entorno) -> None:
    """Sustituye, en el ``main`` recargado, sólo los dobles externos.

    Se parchean los nombres que el ``lifespan`` resuelve en el módulo ``main``
    después de recargarlo, de modo que ``monkeypatch`` los restaure al acabar
    la prueba y no quede ninguna referencia colgando para otras pruebas.
    """
    adaptador_descarga = main_mod.AdaptadorDescarga
    monkeypatch.setattr(
        main_mod,
        "AdaptadorDescarga",
        lambda *args, **kwargs: adaptador_descarga(
            descargador=entorno.descarga, cliente=None
        ),
    )
    adaptador_parseo = main_mod.AdaptadorParseo
    monkeypatch.setattr(
        main_mod,
        "AdaptadorParseo",
        lambda *args, **kwargs: adaptador_parseo(
            extractor_texto=entorno.parseo.texto,
            extractor_ofertas=entorno.parseo.ofertas,
        ),
    )
    cliente_buscador = main_mod.ClienteEstadoBuscadorIntegridad
    monkeypatch.setattr(
        main_mod,
        "ClienteEstadoBuscadorIntegridad",
        lambda url_base, *args, **kwargs: cliente_buscador(
            url_base, cliente=entorno.cliente_http
        ),
    )


def _arrancar(monkeypatch, entorno: Entorno):
    """Recarga ``main``, aplica los dobles y devuelve el módulo."""
    import source.api.main as main_mod

    main_mod = importlib.reload(main_mod)
    _parchear_dobles_de_main(monkeypatch, main_mod, entorno)
    return main_mod


@pytest.fixture
def app_e2e(tmp_path, monkeypatch):
    """App real con el entorno temporal y la tarea sin hilo de disparo.

    La tarea diaria se crea y queda en ``app_state``, pero su ``iniciar`` no
    arranca el hilo: cada escenario dispara la comprobación llamando a
    ``_ejecutar_dia()``, de forma controlada y sin esperas.
    """
    entorno = _crear_entorno(tmp_path, AHORA)
    _parchear(monkeypatch, entorno)
    monkeypatch.setattr(TareaIntegridad, "iniciar", lambda self: None)

    main_mod = _arrancar(monkeypatch, entorno)
    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno

    entorno.cliente_http.close()


@pytest.fixture
def app_catchup(tmp_path, monkeypatch):
    """App real con el reloj dentro de la ventana de catch-up (ALT-009)."""
    entorno = _crear_entorno(tmp_path, MOMENTO_CATCHUP)
    _parchear(monkeypatch, entorno)

    llamadas: list[int] = []
    ejecutar_dia = TareaIntegridad._ejecutar_dia

    def espia(self):
        """Cuenta las comprobaciones del día y delega en la implementación."""
        llamadas.append(1)
        return ejecutar_dia(self)

    monkeypatch.setattr(TareaIntegridad, "_ejecutar_dia", espia)

    main_mod = _arrancar(monkeypatch, entorno)
    with TestClient(main_mod.app) as client:
        yield client, main_mod, entorno, llamadas

    entorno.cliente_http.close()


# ---------------------------------------------------------------------------
# Utilidades de comprobación
# ---------------------------------------------------------------------------


def _esperar(condicion, timeout: float = ESPERA_MAXIMA) -> bool:
    """Espera a que se cumpla una condición, sondeando en intervalos cortos."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return condicion()


def _ejecutar_dia(main_mod) -> object:
    """Dispara la comprobación del día con la tarea real de ``app_state``."""
    tarea = main_mod.app_state.get("tarea_integridad")
    assert tarea is not None, "la integridad no se inicializó en el arranque"
    return tarea._ejecutar_dia()


def _almacen(main_mod) -> AlmacenPDFs:
    """Devuelve el almacén real que dejó el ``lifespan`` en ``app_state``."""
    almacen = main_mod.app_state.get("almacen_integridad")
    assert almacen is not None
    return almacen


def _meta(
    veredicto: str = "concordante",
    recuento_pdf: int = 92,
    recuento_buscador: int = 93,
) -> MetaDia:
    """Metadatos del día como los dejaría una ejecución completa."""
    return MetaDia(
        recuento_pdf=recuento_pdf,
        recuento_buscador=recuento_buscador,
        diferencia=abs(recuento_pdf - recuento_buscador),
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        veredicto=veredicto,
    )


def _aviso_del_dia(almacen: AlmacenPDFs, comunidad: str = "cantabria") -> dict:
    """Devuelve el primer aviso registrado hoy en el ``.meta.json``."""
    lectura = almacen.leer_meta(comunidad, HOY)
    assert lectura.es_valido, "el día no tiene metadatos legibles"
    assert lectura.meta.avisos, "el día no registró ningún aviso"
    return lectura.meta.avisos[0]


def _huella(ruta: Path):
    """Tamaño, mtime y SHA-256 de un fichero, o ``None`` si no existe."""
    if not ruta.exists():
        return None
    contenido = ruta.read_bytes()
    return (
        len(contenido),
        hashlib.sha256(contenido).hexdigest(),
        ruta.stat().st_mtime_ns,
    )


# ---------------------------------------------------------------------------
# Concordancia (92 / 93)
# ---------------------------------------------------------------------------


class TestConcordante:
    """Recuentos dentro de la tolerancia: día concordante y cierre recomendado."""

    def test_92_y_93_concordante_y_cierre_recomendado(self, app_e2e):
        """El día queda concordante y el endpoint recomienda cerrar (REQ-004)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(93)

        resultado = _ejecutar_dia(main_mod)

        assert resultado is not None
        assert resultado.veredicto_global == "concordante"

        almacen = _almacen(main_mod)
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "concordante"
        assert lectura.meta.recuento_pdf == 92
        assert lectura.meta.recuento_buscador == 93
        assert lectura.meta.diferencia == 1
        assert lectura.meta.avisos == []

        respuesta = client.get("/integridad/ultimo")
        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["fecha"] == HOY.isoformat()
        assert datos["veredicto_global"] == "concordante"
        assert datos["cierre_recomendado"] is True
        assert datos["comunidades"][0]["recuento_pdf"] == 92
        assert datos["comunidades"][0]["recuento_buscador"] == 93

    def test_el_dia_deja_el_pdf_y_el_meta_esperados_sin_sqlite(self, app_e2e):
        """El árbol de datos tiene lo esperado y ningún SQLite nuevo (DEC-001)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(93)

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        assert almacen.ruta_pdf("cantabria", HOY).is_file()
        assert almacen.ruta_meta("cantabria", HOY).is_file()
        ficheros = sorted(
            ruta.relative_to(entorno.pdfs_dir).as_posix()
            for ruta in entorno.pdfs_dir.rglob("*")
            if ruta.is_file()
        )
        assert ficheros == [
            "cantabria/%s.meta.json" % HOY.isoformat(),
            "cantabria/%s.pdf" % HOY.isoformat(),
            "ejecuciones.json",
        ]
        assert not list(entorno.pdfs_dir.rglob("*.tmp"))

        sqlites = [
            ruta
            for ruta in entorno.pdfs_dir.rglob("*")
            if ruta.suffix in {".db", ".sqlite", ".sqlite3"}
        ]
        assert sqlites == []
        nuevos = [
            ruta
            for ruta in entorno.tmp_path.rglob("*")
            if "integridad" in ruta.name
            and ruta.suffix in {".db", ".sqlite", ".sqlite3"}
        ]
        assert nuevos == []

    def test_solo_consulta_el_estado_del_buscador(self, app_e2e):
        """La tarea sólo emite peticiones a ``GET /buscador/status`` (SUP-004)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(93)

        _ejecutar_dia(main_mod)

        assert entorno.peticiones == ["/buscador/status"]
        assert client.get("/integridad/pdfs").status_code == 200


# ---------------------------------------------------------------------------
# Divergencia por tolerancia (92 / 80)
# ---------------------------------------------------------------------------


class TestDivergentePorTolerancia:
    """Una diferencia fuera de ambas tolerancias deja el día divergente."""

    def test_92_y_80_divergente_con_aviso_y_cierre_no_recomendable(
        self, app_e2e
    ):
        """El aviso lleva recuentos, diferencia, umbral y motivo (REQ-003)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(80)

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "divergente"
        assert lectura.meta.recuento_pdf == 92
        assert lectura.meta.recuento_buscador == 80
        assert lectura.meta.diferencia == 12

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "divergencia"
        assert aviso["fecha"] == HOY.isoformat()
        assert aviso["comunidad"] == "cantabria"
        assert aviso["recuento_pdf"] == 92
        assert aviso["total_listado"] == 80
        assert aviso["diferencia"] == 12
        assert aviso["tolerancia_absoluta"] == 1
        assert aviso["tolerancia_relativa_pct"] == 5
        assert aviso["umbral_cordura"] == 70
        assert "fuera de la tolerancia" in aviso["motivo"]

        respuesta = client.get("/integridad/ultimo").json()
        assert respuesta["veredicto_global"] == "divergente"
        assert respuesta["cierre_recomendado"] is False

    def test_el_endpoint_de_ejecuciones_devuelve_el_aviso(self, app_e2e):
        """Las ejecuciones del mes exponen su veredicto y sus avisos (REQ-008)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(80)

        _ejecutar_dia(main_mod)

        respuesta = client.get("/integridad/ejecuciones")
        assert respuesta.status_code == 200
        ejecuciones = respuesta.json()
        assert len(ejecuciones) == 1
        ejecucion = ejecuciones[0]
        assert ejecucion["resultado_global"] == "ok"
        assert ejecucion["veredicto_agregado"] == "divergente"
        assert ejecucion["errores_por_comunidad"] == []
        assert ejecucion["timestamp"].startswith(HOY.isoformat())
        assert ejecucion["avisos"]
        aviso = ejecucion["avisos"][0]
        assert aviso["tipo"] == "divergencia"
        assert aviso["comunidad"] == "cantabria"
        assert aviso["recuento_pdf"] == 92
        assert aviso["total_listado"] == 80


# ---------------------------------------------------------------------------
# Divergencia por umbral de cordura (65)
# ---------------------------------------------------------------------------


class TestDivergentePorUmbral:
    """Un recuento por debajo del umbral diverge aunque los recuentos cuadren."""

    def test_65_con_recuentos_iguales_diverge_por_umbral(self, app_e2e):
        """Con ``65`` y umbral ``70`` el veredicto es divergente (NFR-002)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 65
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(65)

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "divergente"
        assert lectura.meta.recuento_pdf == 65
        assert lectura.meta.recuento_buscador == 65
        assert lectura.meta.diferencia == 0
        assert lectura.meta.umbral_cordura == 70

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "divergencia"
        assert aviso["recuento_pdf"] == 65
        assert aviso["diferencia"] == 0
        assert aviso["umbral_cordura"] == 70
        assert "umbral de cordura" in aviso["motivo"]

        assert client.get("/integridad/ultimo").json()[
            "cierre_recomendado"
        ] is False


# ---------------------------------------------------------------------------
# Fallo de descarga
# ---------------------------------------------------------------------------


class TestDescargaFallida:
    """Una descarga fallida deja el día fallido, sin PDF y con aviso."""

    def test_descarga_en_error_fallido_sin_pdf_y_con_aviso(self, app_e2e):
        """El día queda fallido sin PDF conservado y aviso con motivo."""
        client, main_mod, entorno = app_e2e
        entorno.descarga.resultado = ErrorDescarga(
            "Error de descarga: HTTP 503."
        )

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        assert not almacen.ruta_pdf("cantabria", HOY).exists()
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "fallido"
        assert lectura.meta.errores
        assert "HTTP 503" in lectura.meta.errores[0]

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "fallo"
        assert aviso["fecha"] == HOY.isoformat()
        assert aviso["comunidad"] == "cantabria"
        assert "No se pudo descargar" in aviso["motivo"]

        respuesta = client.get("/integridad/ultimo").json()
        assert respuesta["veredicto_global"] == "fallido"
        assert respuesta["cierre_recomendado"] is False


# ---------------------------------------------------------------------------
# Fallo de parseo
# ---------------------------------------------------------------------------


class TestParseoFallido:
    """Un parseo fallido conserva el PDF y deja el día fallido con aviso."""

    def test_parseo_en_error_conserva_pdf_y_fallido(self, app_e2e):
        """El PDF descargado se conserva y el día queda fallido (DEC-002)."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.error = "PDF de difusión ilegible"

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        assert almacen.ruta_pdf("cantabria", HOY).is_file()
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "fallido"
        assert lectura.meta.hash
        assert any(
            "No se pudo parsear" in error for error in lectura.meta.errores
        )

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "fallo"
        assert aviso["comunidad"] == "cantabria"
        assert "No se pudo parsear" in aviso["motivo"]

        assert client.get("/integridad/ultimo").json()[
            "cierre_recomendado"
        ] is False


# ---------------------------------------------------------------------------
# Buscador sin datos (ALT-005, ALT-006)
# ---------------------------------------------------------------------------


class TestBuscadorSinDatos:
    """Sin `ultima_pasada` o con `error_global` el día no puede ser concordante."""

    def test_sin_ultima_pasada_divergente_con_motivo(self, app_e2e):
        """La ausencia de ``ultima_pasada`` deja un día divergente."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = {
            "in_progress": False,
            "progreso": 0,
            "ultima_pasada": None,
        }

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.meta.veredicto == "divergente"
        assert lectura.meta.recuento_buscador is None

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "divergencia"
        assert "ultima_pasada" in aviso["motivo"]
        assert client.get("/integridad/ultimo").json()[
            "cierre_recomendado"
        ] is False

    def test_con_error_global_divergente_con_motivo(self, app_e2e):
        """Un ``error_global`` no vacío deja un día divergente con motivo."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        cuerpo = _estado_buscador_ok(93)
        cuerpo["ultima_pasada"]["error_global"] = "Error al consultar Emplea"
        entorno.estado_buscador["cuerpo"] = cuerpo

        _ejecutar_dia(main_mod)

        almacen = _almacen(main_mod)
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.meta.veredicto == "divergente"

        aviso = _aviso_del_dia(almacen)
        assert aviso["tipo"] == "divergencia"
        assert aviso["motivo"]
        assert "error_global" in aviso["motivo"]
        assert client.get("/integridad/ultimo").json()[
            "cierre_recomendado"
        ] is False


# ---------------------------------------------------------------------------
# Idempotencia diaria (ALT-001, ALT-002)
# ---------------------------------------------------------------------------


class TestIdempotenciaDiaria:
    """Una segunda ejecución y un día fallido previo no rehacen el trabajo."""

    def test_segunda_ejecucion_no_descarga_ni_cambia_el_veredicto(
        self, app_e2e
    ):
        """El mismo día no se descarga dos veces ni gana un segundo veredicto."""
        client, main_mod, entorno = app_e2e
        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(93)

        _ejecutar_dia(main_mod)
        almacen = _almacen(main_mod)
        ruta_meta = almacen.ruta_meta("cantabria", HOY)
        meta_previo = ruta_meta.read_bytes()
        assert len(entorno.descarga.llamadas) == 1
        assert len(entorno.parseo.texto_llamadas) == 1

        _ejecutar_dia(main_mod)

        assert len(entorno.descarga.llamadas) == 1
        assert len(entorno.parseo.texto_llamadas) == 1
        assert ruta_meta.read_bytes() == meta_previo
        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.meta.veredicto == "concordante"
        assert lectura.meta.avisos == []

    def test_dia_fallido_previo_no_se_reintenta(self, app_e2e):
        """Un día ya fallido no se vuelve a descargar (ALT-002)."""
        client, main_mod, entorno = app_e2e
        almacen = _almacen(main_mod)
        almacen.escribir_fallido(
            "cantabria", HOY, "No se pudo descargar el PDF: HTTP 503"
        )
        ruta_meta = almacen.ruta_meta("cantabria", HOY)
        meta_previo = ruta_meta.read_bytes()

        resultado = _ejecutar_dia(main_mod)

        assert resultado is not None
        assert resultado.veredicto_global == "fallido"
        assert entorno.descarga.llamadas == []
        assert entorno.parseo.texto_llamadas == []
        assert ruta_meta.read_bytes() == meta_previo
        assert client.get("/integridad/ultimo").json()[
            "cierre_recomendado"
        ] is False


# ---------------------------------------------------------------------------
# Arranque dentro del margen de catch-up (ALT-009, DEC-007)
# ---------------------------------------------------------------------------


class TestArranqueEnElMargen:
    """Dentro de la ventana se programa una única ejecución a hora + margen."""

    def test_una_unica_ejecucion_a_hora_mas_margen(self, app_catchup):
        """La comprobación del día se adelanta una sola vez (ALT-009)."""
        client, main_mod, entorno, llamadas = app_catchup
        almacen = _almacen(main_mod)
        ruta_meta = almacen.ruta_meta("cantabria", HOY)

        assert _esperar(ruta_meta.is_file), (
            "no se ejecutó la comprobación diferida a hora + margen"
        )
        # La ejecución normal de mañana no se adelanta ni se duplica.
        time.sleep(0.3)
        assert len(llamadas) == 1
        assert len(entorno.descarga.llamadas) == 1

        lectura = almacen.leer_meta("cantabria", HOY)
        assert lectura.es_valido
        assert lectura.meta.veredicto == "concordante"

        respuesta = client.get("/integridad/ultimo").json()
        assert respuesta["fecha"] == HOY.isoformat()
        assert respuesta["cierre_recomendado"] is True


# ---------------------------------------------------------------------------
# Purga por antigüedad (REQ-002, DEC-004)
# ---------------------------------------------------------------------------


class TestPurga:
    """Tras la ejecución, el endpoint de PDFs refleja lo que queda tras la purga."""

    def test_los_pdfs_fuera_de_la_ventana_desaparecen(self, app_e2e):
        """El día en curso se conserva y el de hace 40 días no se lista."""
        client, main_mod, entorno = app_e2e
        almacen = _almacen(main_mod)
        hace_40 = HOY - timedelta(days=40)
        almacen.guardar_pdf("cantabria", hace_40, CONTENIDO_PDF, _meta())
        assert almacen.ruta_pdf("cantabria", hace_40).is_file()

        entorno.parseo.recuento = 92
        entorno.estado_buscador["cuerpo"] = _estado_buscador_ok(93)
        _ejecutar_dia(main_mod)

        assert not almacen.ruta_pdf("cantabria", hace_40).exists()
        assert not almacen.ruta_meta("cantabria", hace_40).exists()
        assert almacen.ruta_pdf("cantabria", HOY).is_file()

        datos = client.get("/integridad/pdfs").json()
        fechas = {fila["fecha"] for fila in datos}
        assert hace_40.isoformat() not in fechas
        assert HOY.isoformat() in fechas

        actual = next(
            fila for fila in datos if fila["fecha"] == HOY.isoformat()
        )
        assert actual["comunidad"] == "cantabria"
        assert actual["ruta"] == f"cantabria/{HOY.isoformat()}.pdf"
        assert actual["veredicto"] == "concordante"


# ---------------------------------------------------------------------------
# No regresión sobre la base de datos de persistencia (SUP-003)
# ---------------------------------------------------------------------------


class TestNoRegresion:
    """La integración no toca ``data/job_emcan.db`` ni crea SQLite propio."""

    def test_la_bd_de_persistencia_conserva_contenido_y_mtime(
        self, tmp_path, monkeypatch
    ):
        """``data/job_emcan.db`` mantiene tamaño, hash y ``mtime`` (SUP-003)."""
        antes = _huella(RUTA_BD_REAL)

        entorno = _crear_entorno(tmp_path, AHORA)
        _parchear(monkeypatch, entorno)
        monkeypatch.setattr(TareaIntegridad, "iniciar", lambda self: None)

        main_mod = _arrancar(monkeypatch, entorno)
        with TestClient(main_mod.app) as client:
            _ejecutar_dia(main_mod)
            assert client.get("/health").status_code == 200

        entorno.cliente_http.close()
        assert _huella(RUTA_BD_REAL) == antes
