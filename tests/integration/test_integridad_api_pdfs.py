"""Pruebas de integración del endpoint de PDFs conservados (TASK-017).

Montan con ``TestClient`` una aplicación mínima que incluye el router de la
integridad y un entorno temporal: la configuración de la integridad se escribe
en ``tmp_path``, la ruta base de PDFs apunta a ``tmp_path`` y el árbol se siembra
con el almacén real. Comprueban que se devuelve un elemento por PDF con su
fecha, su comunidad y su ruta identificable (REQ-009), los metadatos del día
cuando existen (REQ-005), el PDF sin ``.meta.json`` listado sin datos y sin
error (ALT-007), el ``.meta.json`` ilegible omitido sin impedir listar, la lista
vacía sin directorio, la desaparición de los PDFs purgados (REQ-002, DEC-004),
que la consulta no escribe ni borra y no altera ``data/job_emcan.db``
(SUP-003) y que no exige autenticación.
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
from source.api.integridad.pdf_store import AlmacenPDFs, MetaDia
from source.api.integridad.purger import purgar

RUTA_BD_REAL = Path("data/job_emcan.db")

_CONTENIDO_PDF = b"%PDF-1.4 contenido de prueba"


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

    app_state = {
        "config_integridad": config,
        "almacen_integridad": almacen,
        "indice_ejecuciones": None,
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
            pdfs_dir=pdfs_dir,
        )


# ---------------------------------------------------------------------------
# Siembra de datos
# ---------------------------------------------------------------------------


def _sembrar_pdf(
    almacen: AlmacenPDFs,
    comunidad: str,
    fecha: date,
    veredicto: str = "concordante",
    recuento_pdf: int = 92,
    recuento_buscador: int = 93,
) -> MetaDia:
    """Guarda el PDF del día con sus metadatos y devuelve el ``MetaDia``."""
    return almacen.guardar_pdf(
        comunidad,
        fecha,
        _CONTENIDO_PDF,
        MetaDia(
            recuento_pdf=recuento_pdf,
            recuento_buscador=recuento_buscador,
            diferencia=abs(recuento_pdf - recuento_buscador),
            tolerancia_absoluta=1,
            tolerancia_relativa_pct=5,
            umbral_cordura=70,
            veredicto=veredicto,
        ),
    )


def _sembrar_pdf_sin_meta(
    almacen: AlmacenPDFs, comunidad: str, fecha: date
) -> Path:
    """Deja un PDF huérfano en el árbol, sin su ``.meta.json`` (ALT-007)."""
    ruta = almacen.ruta_pdf(comunidad, fecha)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(_CONTENIDO_PDF)
    return ruta


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
# Un elemento por PDF con fecha, comunidad y ruta (REQ-009)
# ---------------------------------------------------------------------------


class TestListadoDePdfs:
    """El endpoint devuelve un elemento por cada PDF conservado."""

    def test_un_elemento_por_pdf_con_fecha_comunidad_y_ruta(self, entorno):
        """Dos PDFs de dos comunidades dan dos elementos identificables."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 22))
        _sembrar_pdf(entorno.almacen, "asturias", date(2026, 11, 23))

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert [(fila["comunidad"], fila["fecha"]) for fila in datos] == [
            ("asturias", "2026-11-23"),
            ("cantabria", "2026-11-22"),
        ]

    def test_la_ruta_es_relativa_a_la_base(self, entorno):
        """La ruta identifica el PDF sin exponer la ruta absoluta del sistema."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))

        datos = entorno.client.get("/integridad/pdfs").json()

        assert datos[0]["ruta"] == "cantabria/2026-11-23.pdf"
        assert str(entorno.pdfs_dir) not in datos[0]["ruta"]

    def test_varios_dias_de_la_misma_comunidad(self, entorno):
        """Cada día de una comunidad es un elemento distinto."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 22))
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))

        datos = entorno.client.get("/integridad/pdfs").json()

        assert [fila["fecha"] for fila in datos] == [
            "2026-11-22",
            "2026-11-23",
        ]
        assert {fila["comunidad"] for fila in datos} == {"cantabria"}

    def test_nombres_fuera_del_patron_no_se_listan(self, entorno):
        """Un fichero que no es ``<aaaa-mm-dd>.pdf`` no aparece (SUP-003)."""
        entorno.pdfs_dir.mkdir(parents=True, exist_ok=True)
        (entorno.pdfs_dir / "suelto.pdf").write_bytes(_CONTENIDO_PDF)
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))

        datos = entorno.client.get("/integridad/pdfs").json()

        assert [fila["ruta"] for fila in datos] == [
            "cantabria/2026-11-23.pdf"
        ]


# ---------------------------------------------------------------------------
# Metadatos disponibles (REQ-005)
# ---------------------------------------------------------------------------


class TestMetadatos:
    """Los datos del ``.meta.json`` se incluyen cuando existe."""

    def test_incluye_hash_recuentos_y_veredicto(self, entorno):
        """El elemento lleva los campos del día guardados por la tarea."""
        meta = _sembrar_pdf(
            entorno.almacen,
            "cantabria",
            date(2026, 11, 23),
            veredicto="divergente",
            recuento_pdf=80,
            recuento_buscador=93,
        )

        datos = entorno.client.get("/integridad/pdfs").json()

        assert datos[0]["hash"] == meta.hash
        assert datos[0]["recuento_pdf"] == 80
        assert datos[0]["recuento_buscador"] == 93
        assert datos[0]["veredicto"] == "divergente"

    def test_el_hash_corresponde_al_contenido_del_pdf(self, entorno):
        """El hash expuesto es el SHA-256 del PDF conservado (DEC-003)."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))

        datos = entorno.client.get("/integridad/pdfs").json()

        assert datos[0]["hash"] == hashlib.sha256(_CONTENIDO_PDF).hexdigest()

    def test_veredicto_fallido_se_expone(self, entorno):
        """Un día ``fallido`` conserva su veredicto en el listado."""
        _sembrar_pdf(
            entorno.almacen,
            "cantabria",
            date(2026, 11, 23),
            veredicto="fallido",
        )

        datos = entorno.client.get("/integridad/pdfs").json()

        assert datos[0]["veredicto"] == "fallido"


# ---------------------------------------------------------------------------
# PDF sin metadatos y metadatos ilegibles (ALT-007, design@3)
# ---------------------------------------------------------------------------


class TestMetadatosAusentesOIlegibles:
    """El PDF se lista aunque no haya metadatos utilizables."""

    def test_pdf_sin_meta_se_lista_sin_metadatos(self, entorno):
        """Un PDF huérfano aparece con los campos de metadatos en nulo."""
        _sembrar_pdf_sin_meta(entorno.almacen, "cantabria", date(2026, 11, 23))

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert len(datos) == 1
        assert datos[0]["comunidad"] == "cantabria"
        assert datos[0]["fecha"] == "2026-11-23"
        assert datos[0]["ruta"] == "cantabria/2026-11-23.pdf"
        assert datos[0]["hash"] is None
        assert datos[0]["recuento_pdf"] is None
        assert datos[0]["recuento_buscador"] is None
        assert datos[0]["veredicto"] is None

    def test_meta_ilegible_no_impide_listar(self, entorno):
        """Un ``.meta.json`` corrupto se omite y el resto se lista."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))
        ruta_corrupta = entorno.almacen.ruta_meta(
            "asturias", date(2026, 11, 23)
        )
        ruta_corrupta.parent.mkdir(parents=True, exist_ok=True)
        ruta_corrupta.write_text("{esto no es json", encoding="utf-8")
        _sembrar_pdf_sin_meta(entorno.almacen, "asturias", date(2026, 11, 23))

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        datos = respuesta.json()
        assert [(fila["comunidad"], fila["fecha"]) for fila in datos] == [
            ("asturias", "2026-11-23"),
            ("cantabria", "2026-11-23"),
        ]
        corrupto = datos[0]
        assert corrupto["veredicto"] is None
        assert corrupto["hash"] is None
        assert datos[1]["veredicto"] == "concordante"

    def test_meta_ilegible_no_se_reescribe(self, entorno):
        """La consulta deja intacto el ``.meta.json`` corrupto."""
        ruta_corrupta = entorno.almacen.ruta_meta(
            "cantabria", date(2026, 11, 23)
        )
        ruta_corrupta.parent.mkdir(parents=True, exist_ok=True)
        ruta_corrupta.write_text("{esto no es json", encoding="utf-8")
        _sembrar_pdf_sin_meta(entorno.almacen, "cantabria", date(2026, 11, 23))
        antes = _huella(ruta_corrupta)

        entorno.client.get("/integridad/pdfs")

        assert _huella(ruta_corrupta) == antes


# ---------------------------------------------------------------------------
# Sin directorio de PDFs (REQ-009)
# ---------------------------------------------------------------------------


class TestSinDirectorio:
    """Sin árbol de PDFs la respuesta es una lista vacía sin error."""

    def test_sin_directorio_devuelve_lista_vacia(self, entorno):
        """La ruta base inexistente no produce error."""
        assert not entorno.pdfs_dir.exists()

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        assert respuesta.json() == []

    def test_directorio_vacio_devuelve_lista_vacia(self, entorno):
        """Un árbol sin PDFs responde con una lista vacía."""
        entorno.pdfs_dir.mkdir(parents=True, exist_ok=True)

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        assert respuesta.json() == []


# ---------------------------------------------------------------------------
# Lo que queda tras la purga (REQ-002, DEC-004)
# ---------------------------------------------------------------------------


class TestTrasLaPurga:
    """El listado refleja el árbol después de la purga por antigüedad."""

    def test_los_pdfs_fuera_de_la_ventana_no_aparecen(self, entorno):
        """Tras purgar, solo quedan el día en curso y la ventana de retención."""
        hoy = entorno.hoy
        hace_40 = hoy - timedelta(days=40)
        hace_30 = hoy - timedelta(days=30)
        _sembrar_pdf(entorno.almacen, "cantabria", hace_40)
        _sembrar_pdf(entorno.almacen, "cantabria", hace_30)
        _sembrar_pdf(entorno.almacen, "cantabria", hoy)

        purgar(entorno.almacen.base, entorno.config.dias_retencion, hoy)

        datos = entorno.client.get("/integridad/pdfs").json()

        assert [fila["fecha"] for fila in datos] == [
            hace_30.isoformat(),
            hoy.isoformat(),
        ]


# ---------------------------------------------------------------------------
# Solo lectura y sin autenticación (SUP-003)
# ---------------------------------------------------------------------------


class TestSoloLecturaYSinAutenticacion:
    """La consulta no escribe, no borra y no exige autenticación."""

    def test_no_escribe_ni_borra_en_el_arbol(self, entorno):
        """Tras la consulta, el árbol de PDFs queda igual."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))
        _sembrar_pdf_sin_meta(entorno.almacen, "asturias", date(2026, 11, 22))
        antes = _huella_arbol(entorno.pdfs_dir)

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        assert _huella_arbol(entorno.pdfs_dir) == antes

    def test_no_modifica_la_base_de_persistencia(self, entorno):
        """La consulta no altera el contenido ni el mtime de la BD real."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))
        antes = _huella(RUTA_BD_REAL)

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        assert _huella(RUTA_BD_REAL) == antes

    def test_sin_autenticacion(self, entorno):
        """La consulta responde 200 sin cabeceras de autenticación."""
        _sembrar_pdf(entorno.almacen, "cantabria", date(2026, 11, 23))

        respuesta = entorno.client.get("/integridad/pdfs")

        assert respuesta.status_code == 200
        assert respuesta.status_code not in (401, 403)
