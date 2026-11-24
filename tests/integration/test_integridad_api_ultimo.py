"""Pruebas de integración del endpoint del último veredicto (TASK-015).

Montan con ``TestClient`` una aplicación mínima que incluye el router de la
integridad y un entorno temporal: la configuración de la integridad se escribe
en ``tmp_path``, la ruta base de PDFs apunta a ``tmp_path`` y los
``.meta.json`` se siembran con el almacén real. Comprueban que se devuelve el
día más reciente con sus campos, la recomendación de cierre según el veredicto
de hoy (REQ-006), la agregación por gravedad con varias comunidades (ALT-008),
la omisión de metadatos ilegibles, el 503 cuando la feature no está disponible
y que la consulta no escribe nada ni altera ``data/job_emcan.db`` (SUP-002).
"""

import hashlib
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


def _meta(
    veredicto: str,
    recuento_pdf: int | None = 92,
    recuento_buscador: int | None = 93,
) -> MetaDia:
    """Metadatos del día con los campos del modelo lógico (REQ-005)."""
    diferencia = (
        abs(recuento_pdf - recuento_buscador)
        if recuento_pdf is not None and recuento_buscador is not None
        else None
    )
    return MetaDia(
        hash="0" * 64,
        recuento_pdf=recuento_pdf,
        recuento_buscador=recuento_buscador,
        diferencia=diferencia,
        tolerancia_absoluta=1,
        tolerancia_relativa_pct=5,
        umbral_cordura=70,
        veredicto=veredicto,
    )


def _sembrar(
    almacen: AlmacenPDFs,
    comunidad: str,
    fecha: date,
    veredicto: str = "concordante",
    recuento_pdf: int | None = 92,
    recuento_buscador: int | None = 93,
) -> None:
    """Escribe el ``.meta.json`` del día de una comunidad."""
    almacen.escribir_meta(
        comunidad,
        fecha,
        _meta(veredicto, recuento_pdf, recuento_buscador),
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
# El más reciente y sus campos
# ---------------------------------------------------------------------------


class TestUltimoVeredictoAlmacenado:
    """El endpoint devuelve el veredicto del día más reciente (REQ-009)."""

    def test_devuelve_el_mas_reciente_con_sus_campos(self, entorno):
        """Con días distintos, elige la fecha máxima y expone sus campos."""
        ayer = entorno.hoy - timedelta(days=1)
        anteayer = ayer - timedelta(days=1)
        _sembrar(entorno.almacen, "cantabria", anteayer, "concordante")
        _sembrar(entorno.almacen, "cantabria", ayer, "divergente", 80, 93)

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["fecha"] == ayer.isoformat()
        assert datos["veredicto_global"] == "divergente"
        assert datos["cierre_recomendado"] is False
        assert len(datos["comunidades"]) == 1
        fila = datos["comunidades"][0]
        assert fila["fecha"] == ayer.isoformat()
        assert fila["comunidad"] == "cantabria"
        assert fila["recuento_pdf"] == 80
        assert fila["recuento_buscador"] == 93
        assert fila["diferencia"] == 13
        assert fila["tolerancia_absoluta"] == 1
        assert fila["tolerancia_relativa_pct"] == 5
        assert fila["umbral_cordura"] == 70
        assert fila["veredicto"] == "divergente"

    def test_sin_metadatos_devuelve_respuesta_vacia(self, entorno):
        """Sin ningún ``.meta.json`` responde 200 sin veredicto ni cierre."""
        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["fecha"] is None
        assert datos["veredicto_global"] is None
        assert datos["cierre_recomendado"] is False
        assert datos["comunidades"] == []


# ---------------------------------------------------------------------------
# Recomendación de cierre (REQ-006)
# ---------------------------------------------------------------------------


class TestCierreRecomendado:
    """Solo un veredicto ``concordante`` de hoy recomienda cerrar."""

    def test_divergente_de_hoy_no_es_recomendable(self, entorno):
        """Un día divergente de hoy indica que no se recomienda cerrar."""
        _sembrar(
            entorno.almacen, "cantabria", entorno.hoy, "divergente", 80, 93
        )

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["veredicto_global"] == "divergente"
        assert datos["cierre_recomendado"] is False

    def test_fallido_de_hoy_no_es_recomendable(self, entorno):
        """Un día fallido de hoy no recomienda cerrar ofertas."""
        entorno.almacen.escribir_fallido(
            "cantabria", entorno.hoy, "error HTTP 503 al descargar el PDF"
        )

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["veredicto_global"] == "fallido"
        assert datos["cierre_recomendado"] is False
        assert datos["comunidades"][0]["veredicto"] == "fallido"

    def test_sin_veredicto_de_hoy_no_es_recomendable(self, entorno):
        """Un veredicto de ayer, aunque sea concordante, no recomienda cerrar."""
        ayer = entorno.hoy - timedelta(days=1)
        _sembrar(entorno.almacen, "cantabria", ayer, "concordante")

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["fecha"] == ayer.isoformat()
        assert datos["veredicto_global"] == "concordante"
        assert datos["cierre_recomendado"] is False

    def test_concordante_de_hoy_es_recomendable(self, entorno):
        """Un día concordante de hoy sí recomienda cerrar ofertas."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["fecha"] == entorno.hoy.isoformat()
        assert datos["veredicto_global"] == "concordante"
        assert datos["cierre_recomendado"] is True

    def test_sin_cabeceras_de_autenticacion(self, entorno):
        """El endpoint no exige autenticación ni devuelve 401/403."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        assert respuesta.status_code not in (401, 403)


# ---------------------------------------------------------------------------
# Varias comunidades (ALT-008)
# ---------------------------------------------------------------------------


class TestVariasComunidades:
    """El veredicto global es el más grave y el desglose las incluye a todas."""

    def test_global_mas_grave_y_desglose_completo(self, entorno):
        """Una concordante y una divergente dan global divergente."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")
        _sembrar(entorno.almacen, "asturias", entorno.hoy, "divergente", 80, 93)

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["veredicto_global"] == "divergente"
        assert datos["cierre_recomendado"] is False
        comunidades = {fila["comunidad"]: fila for fila in datos["comunidades"]}
        assert set(comunidades) == {"cantabria", "asturias"}
        assert comunidades["cantabria"]["veredicto"] == "concordante"
        assert comunidades["asturias"]["veredicto"] == "divergente"

    def test_fallido_prevalece_sobre_divergente(self, entorno):
        """``fallido`` es más grave que ``divergente`` (ALT-008)."""
        _sembrar(
            entorno.almacen, "cantabria", entorno.hoy, "divergente", 80, 93
        )
        entorno.almacen.escribir_fallido(
            "asturias", entorno.hoy, "error de red"
        )

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["veredicto_global"] == "fallido"
        assert datos["cierre_recomendado"] is False

    def test_todas_concordantes_recomienda_cerrar(self, entorno):
        """Con todas las comunidades concordantes, se recomienda cerrar."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")
        _sembrar(entorno.almacen, "asturias", entorno.hoy, "concordante")

        datos = entorno.client.get("/integridad/ultimo").json()

        assert datos["veredicto_global"] == "concordante"
        assert datos["cierre_recomendado"] is True
        assert len(datos["comunidades"]) == 2

    def test_orden_por_la_ultima_ejecucion_del_indice(self, entorno):
        """A igualdad de fecha, ordena como la última ejecución del índice."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")
        _sembrar(entorno.almacen, "asturias", entorno.hoy, "concordante")
        entorno.indice.registrar(
            Ejecucion(
                resultado_global="ok",
                veredicto_agregado="concordante",
                referencias=[
                    {"fecha": entorno.hoy.isoformat(), "comunidad": "asturias"},
                    {"fecha": entorno.hoy.isoformat(), "comunidad": "cantabria"},
                ],
                timestamp=f"{entorno.hoy.isoformat()}T02:00:00+01:00",
            )
        )

        datos = entorno.client.get("/integridad/ultimo").json()

        assert [fila["comunidad"] for fila in datos["comunidades"]] == [
            "asturias",
            "cantabria",
        ]


# ---------------------------------------------------------------------------
# Metadatos ilegibles y feature no disponible
# ---------------------------------------------------------------------------


class TestCasosDeError:
    """Los metadatos corruptos se omiten y la feature ausente da 503."""

    def test_meta_ilegible_se_omite_sin_error(self, entorno):
        """Un ``.meta.json`` corrupto no aparece ni rompe la respuesta."""
        ayer = entorno.hoy - timedelta(days=1)
        _sembrar(entorno.almacen, "cantabria", ayer, "concordante")
        ruta_corrupta = entorno.almacen.ruta_meta("asturias", entorno.hoy)
        ruta_corrupta.parent.mkdir(parents=True, exist_ok=True)
        ruta_corrupta.write_text("{esto no es json", encoding="utf-8")

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert datos["fecha"] == ayer.isoformat()
        assert [fila["comunidad"] for fila in datos["comunidades"]] == [
            "cantabria"
        ]

    def test_sin_almacen_responde_503(self, entorno, monkeypatch):
        """Sin ``almacen_integridad`` la respuesta es 503 con mensaje claro."""
        monkeypatch.delitem(entorno.app_state, "almacen_integridad")

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 503
        assert "integridad" in respuesta.json()["detail"].lower()

    def test_almacen_nulo_responde_503(self, entorno, monkeypatch):
        """Un ``almacen_integridad`` a ``None`` también da 503."""
        monkeypatch.setitem(entorno.app_state, "almacen_integridad", None)

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 503


# ---------------------------------------------------------------------------
# Solo lectura (SUP-002)
# ---------------------------------------------------------------------------


class TestSoloLectura:
    """La consulta no escribe ficheros ni toca ``data/job_emcan.db``."""

    def test_no_escribe_en_el_arbol_de_pdfs(self, entorno):
        """Tras la consulta, el árbol de PDFs queda igual que antes."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")
        antes = _huella_arbol(entorno.pdfs_dir)

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        assert _huella_arbol(entorno.pdfs_dir) == antes

    def test_no_modifica_la_base_de_persistencia(self, entorno):
        """La consulta no altera el contenido ni el mtime de la BD real."""
        _sembrar(entorno.almacen, "cantabria", entorno.hoy, "concordante")
        antes = _huella(RUTA_BD_REAL)

        respuesta = entorno.client.get("/integridad/ultimo")

        assert respuesta.status_code == 200
        assert _huella(RUTA_BD_REAL) == antes
