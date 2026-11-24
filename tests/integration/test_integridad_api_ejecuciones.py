"""Pruebas de integración del endpoint de ejecuciones del último mes (TASK-016).

Montan con ``TestClient`` una aplicación mínima que incluye el router de la
integridad y un entorno temporal: la configuración de la integridad se escribe
en ``tmp_path``, la ruta base de PDFs apunta a ``tmp_path`` y el índice de
ejecuciones se siembra con el índice y el almacén reales. Comprueban que se
devuelven las ejecuciones de la ventana de 30 días con su marca de tiempo y su
resultado (REQ-009), los errores parciales por comunidad y mensaje (REQ-008),
el orden de más reciente a más antigua, los avisos de los ``.meta.json``
referenciados (REQ-007), la lista vacía sin error con un índice ausente o
ilegible y que la consulta no escribe nada, no altera ``data/job_emcan.db`` ni
usa canales de notificación externos (SUP-002, SUP-007).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.integridad import routes
from source.api.integridad.config import ConfigIntegridad, cargar_configuracion
from source.api.integridad.ejecuciones import Ejecucion, IndiceEjecuciones
from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia

RUTA_BD_REAL = Path("data/job_emcan.db")


# ---------------------------------------------------------------------------
# Entorno temporal
# ---------------------------------------------------------------------------


@dataclass
class Entorno:
    """Aplicación de prueba y dependencias sembradas del entorno temporal."""

    client: TestClient
    app_state: dict
    config: ConfigIntegridad
    almacen: AlmacenPDFs
    indice: IndiceEjecuciones
    pdfs_dir: Path

    @property
    def hoy(self) -> date:
        """Día actual en la zona configurada (NFR-004)."""
        return datetime.now(self.config.zona).date()


def _crear_config(tmp_path: Path, pdfs_dir: Path) -> Path:
    """Escribe una configuración de la integridad apuntando a ``tmp_path``."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    ruta = config_dir / "integridad.yaml"
    ruta.write_text(
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
        "  url_base: http://localhost:19999\n"
        "comunidades:\n"
        "  - identificador: cantabria\n"
        "    url_pdf: http://localhost:19999/cantabria.pdf\n"
        "  - identificador: asturias\n"
        "    url_pdf: http://localhost:19999/asturias.pdf\n",
        encoding="utf-8",
    )
    return ruta


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Devuelve la app de prueba con el entorno temporal ya configurado."""
    pdfs_dir = tmp_path / "data" / "pdfs"
    config = cargar_configuracion(_crear_config(tmp_path, pdfs_dir))
    almacen = AlmacenPDFs(config.ruta_base_pdfs, config.zona_horaria)
    indice = IndiceEjecuciones(config.ruta_base_pdfs, config.zona_horaria)

    app_state = {
        "config_integridad": config,
        "almacen_integridad": almacen,
        "indice_ejecuciones": indice,
    }
    import source.api.main as main_mod

    # Los endpoints leen ``app_state`` de ``main`` en cada petición.
    monkeypatch.setattr(main_mod, "app_state", app_state)

    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield Entorno(
            client=client,
            app_state=app_state,
            config=config,
            almacen=almacen,
            indice=indice,
            pdfs_dir=pdfs_dir,
        )


# ---------------------------------------------------------------------------
# Siembra de datos
# ---------------------------------------------------------------------------


def _timestamp(fecha: date, hora: str = "02:00:00") -> str:
    """Marca de tiempo ISO 8601 del día en la zona configurada."""
    return f"{fecha.isoformat()}T{hora}+01:00"


def _registrar(
    indice: IndiceEjecuciones,
    fecha: date,
    resultado: str = "ok",
    veredicto: str = "concordante",
    errores: list[dict] | None = None,
    referencias: list[dict] | None = None,
    hora: str = "02:00:00",
) -> Ejecucion:
    """Registra en el índice una ejecución del día indicado."""
    return indice.registrar(
        Ejecucion(
            resultado_global=resultado,
            veredicto_agregado=veredicto,
            errores_por_comunidad=list(errores or []),
            referencias=list(referencias or []),
            timestamp=_timestamp(fecha, hora),
        )
    )


def _sembrar_meta(
    almacen: AlmacenPDFs,
    comunidad: str,
    fecha: date,
    avisos: list[dict] | None = None,
) -> None:
    """Escribe el ``.meta.json`` del día de una comunidad con sus avisos."""
    almacen.escribir_meta(
        comunidad,
        fecha,
        MetaDia(
            hash="0" * 64,
            recuento_pdf=80,
            recuento_buscador=93,
            diferencia=13,
            tolerancia_absoluta=1,
            tolerancia_relativa_pct=5,
            umbral_cordura=70,
            veredicto="divergente",
            avisos=list(avisos or []),
        ),
    )


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


def _huella_arbol(base: Path):
    """Huella de todos los ficheros del árbol, con su ruta relativa."""
    if not base.is_dir():
        return []
    return sorted(
        (ruta.relative_to(base).as_posix(), _huella(ruta))
        for ruta in base.rglob("*")
        if ruta.is_file()
    )


# ---------------------------------------------------------------------------
# Ventana de 30 días y orden (REQ-009)
# ---------------------------------------------------------------------------


class TestVentanaUltimoMes:
    """El endpoint devuelve la ventana de 30 días, de reciente a antigua."""

    def test_devuelve_las_de_los_ultimos_30_dias(self, entorno):
        """Las ejecuciones de los últimos días aparecen con su resultado."""
        ayer = entorno.hoy - timedelta(days=1)
        hace_29 = entorno.hoy - timedelta(days=29)
        _registrar(entorno.indice, ayer, resultado="ok")
        _registrar(entorno.indice, hace_29, resultado="parcial")

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert [fila["timestamp"] for fila in datos] == [
            _timestamp(ayer),
            _timestamp(hace_29),
        ]
        assert [fila["resultado_global"] for fila in datos] == [
            "ok",
            "parcial",
        ]

    def test_el_limite_de_la_ventana_es_inclusivo(self, entorno):
        """Una ejecución de hace exactamente 30 días sigue dentro."""
        hace_30 = entorno.hoy - timedelta(days=30)
        _registrar(entorno.indice, hace_30)

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert len(datos) == 1
        assert datos[0]["timestamp"] == _timestamp(hace_30)

    def test_mas_de_30_dias_no_aparecen(self, entorno):
        """Una ejecución de hace 31 días queda fuera de la respuesta."""
        _registrar(entorno.indice, entorno.hoy - timedelta(days=31))

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_orden_de_mas_reciente_a_mas_antigua(self, entorno):
        """Aunque se registren desordenadas, responde de reciente a antigua."""
        ayer = entorno.hoy - timedelta(days=1)
        hace_5 = entorno.hoy - timedelta(days=5)
        _registrar(entorno.indice, hace_5, resultado="ok")
        _registrar(entorno.indice, entorno.hoy, resultado="parcial")
        _registrar(entorno.indice, ayer, resultado="ok")

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert [fila["timestamp"] for fila in datos] == [
            _timestamp(entorno.hoy),
            _timestamp(ayer),
            _timestamp(hace_5),
        ]

    def test_devuelve_veredicto_agregado(self, entorno):
        """Cada ejecución expone su veredicto agregado (REQ-008)."""
        _registrar(entorno.indice, entorno.hoy, veredicto="divergente")

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert datos[0]["veredicto_agregado"] == "divergente"


# ---------------------------------------------------------------------------
# Errores parciales (REQ-008)
# ---------------------------------------------------------------------------


class TestErroresParciales:
    """Una ejecución con errores expone la comunidad afectada y su mensaje."""

    def test_expone_comunidad_y_mensaje(self, entorno):
        """Los errores por comunidad llegan con sus dos campos."""
        _registrar(
            entorno.indice,
            entorno.hoy,
            resultado="parcial",
            veredicto="fallido",
            errores=[
                {
                    "comunidad": "cantabria",
                    "mensaje": "error HTTP 503 al descargar el PDF",
                }
            ],
        )

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert datos[0]["resultado_global"] == "parcial"
        assert datos[0]["errores_por_comunidad"] == [
            {
                "comunidad": "cantabria",
                "mensaje": "error HTTP 503 al descargar el PDF",
            }
        ]

    def test_sin_errores_devuelve_lista_vacia(self, entorno):
        """Una ejecución correcta no inventa errores por comunidad."""
        _registrar(entorno.indice, entorno.hoy, resultado="ok")

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert datos[0]["errores_por_comunidad"] == []


# ---------------------------------------------------------------------------
# Avisos de las ejecuciones (REQ-007)
# ---------------------------------------------------------------------------


class TestAvisos:
    """Los avisos de los ``.meta.json`` referenciados son consultables."""

    def test_incluye_los_avisos_de_la_ejecucion(self, entorno):
        """Una referencia a un día con aviso devuelve ese aviso completo."""
        aviso = {
            "tipo": "divergencia",
            "fecha": entorno.hoy.isoformat(),
            "comunidad": "cantabria",
            "recuento_pdf": 80,
            "total_listado": 93,
            "diferencia": 13,
            "tolerancia_absoluta": 1,
            "tolerancia_relativa_pct": 5,
            "umbral_cordura": 70,
            "motivo": "la diferencia supera las dos tolerancias",
        }
        _sembrar_meta(entorno.almacen, "cantabria", entorno.hoy, [aviso])
        _registrar(
            entorno.indice,
            entorno.hoy,
            veredicto="divergente",
            referencias=[
                {"fecha": entorno.hoy.isoformat(), "comunidad": "cantabria"}
            ],
        )

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert datos[0]["avisos"] == [aviso]

    def test_aviso_de_fallo_tambien_es_consultable(self, entorno):
        """Un aviso de fallo llega con fecha, comunidad y motivo."""
        aviso = {
            "tipo": "fallo",
            "fecha": entorno.hoy.isoformat(),
            "comunidad": "asturias",
            "motivo": "error de red al descargar el PDF",
        }
        _sembrar_meta(entorno.almacen, "asturias", entorno.hoy, [aviso])
        _registrar(
            entorno.indice,
            entorno.hoy,
            resultado="parcial",
            veredicto="fallido",
            referencias=[
                {"fecha": entorno.hoy.isoformat(), "comunidad": "asturias"}
            ],
        )

        datos = entorno.client.get("/integridad/ejecuciones").json()

        assert datos[0]["avisos"][0]["tipo"] == "fallo"
        assert datos[0]["avisos"][0]["comunidad"] == "asturias"
        assert (
            datos[0]["avisos"][0]["motivo"]
            == "error de red al descargar el PDF"
        )

    def test_meta_ilegible_se_omite_sin_error(self, entorno):
        """Una referencia a metadatos corruptos no rompe ni aporta avisos."""
        ruta_corrupta = entorno.almacen.ruta_meta("cantabria", entorno.hoy)
        ruta_corrupta.parent.mkdir(parents=True, exist_ok=True)
        ruta_corrupta.write_text("{esto no es json", encoding="utf-8")
        _registrar(
            entorno.indice,
            entorno.hoy,
            referencias=[
                {"fecha": entorno.hoy.isoformat(), "comunidad": "cantabria"}
            ],
        )

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json()[0]["avisos"] == []

    def test_referencia_sin_metadatos_no_falla(self, entorno):
        """Una referencia a un día sin ``.meta.json`` deja la lista vacía."""
        _registrar(
            entorno.indice,
            entorno.hoy,
            referencias=[
                {"fecha": entorno.hoy.isoformat(), "comunidad": "cantabria"}
            ],
        )

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json()[0]["avisos"] == []


# ---------------------------------------------------------------------------
# Índice ausente o ilegible
# ---------------------------------------------------------------------------


class TestIndiceAusenteOIlegible:
    """Sin índice utilizable la respuesta es una lista vacía sin error."""

    def test_indice_ausente_devuelve_lista_vacia(self, entorno):
        """Sin ``ejecuciones.json`` responde 200 con una lista vacía."""
        assert not entorno.indice.ruta_indice.exists()

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_indice_ilegible_devuelve_lista_vacia(self, entorno):
        """Un ``ejecuciones.json`` corrupto responde 200 con lista vacía."""
        entorno.indice.ruta_indice.parent.mkdir(parents=True, exist_ok=True)
        entorno.indice.ruta_indice.write_text(
            "{esto no es json", encoding="utf-8"
        )

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_indice_con_forma_incorrecta_devuelve_lista_vacia(self, entorno):
        """Un JSON válido sin la forma del índice tampoco rompe la consulta."""
        entorno.indice.ruta_indice.parent.mkdir(parents=True, exist_ok=True)
        entorno.indice.ruta_indice.write_text(
            json.dumps({"version": 1, "ejecuciones": "no es una lista"}),
            encoding="utf-8",
        )

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert respuesta.json() == []


# ---------------------------------------------------------------------------
# Solo lectura y sin notificaciones externas (SUP-002, SUP-007)
# ---------------------------------------------------------------------------


class TestSoloLecturaYNotificaciones:
    """La consulta no escribe ni usa canales de notificación externos."""

    def test_no_escribe_en_el_arbol_de_pdfs(self, entorno):
        """Tras la consulta, el árbol de PDFs y el índice quedan igual."""
        _sembrar_meta(entorno.almacen, "cantabria", entorno.hoy)
        _registrar(
            entorno.indice,
            entorno.hoy,
            referencias=[
                {"fecha": entorno.hoy.isoformat(), "comunidad": "cantabria"}
            ],
        )
        antes = _huella_arbol(entorno.pdfs_dir)

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert _huella_arbol(entorno.pdfs_dir) == antes

    def test_no_modifica_la_base_de_persistencia(self, entorno):
        """La consulta no altera el contenido ni el mtime de la BD real."""
        _registrar(entorno.indice, entorno.hoy)
        antes = _huella(RUTA_BD_REAL)

        respuesta = entorno.client.get("/integridad/ejecuciones")

        assert respuesta.status_code == 200
        assert _huella(RUTA_BD_REAL) == antes

    def test_sin_canales_de_notificacion_externa(self, entorno):
        """Ni la respuesta ni el router exponen Telegram u otro canal."""
        _registrar(entorno.indice, entorno.hoy, resultado="parcial")

        datos = entorno.client.get("/integridad/ejecuciones").json()

        texto = json.dumps(datos).lower()
        for canal in ("telegram", "smtp", "correo", "email"):
            assert canal not in texto
        fuente = Path(routes.__file__).read_text(encoding="utf-8").lower()
        for canal in ("telegram", "smtplib", "requests.post"):
            assert canal not in fuente
