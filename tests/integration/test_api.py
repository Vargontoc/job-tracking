"""Pruebas de integración del endpoint de parseo."""

from pathlib import Path

from fastapi.testclient import TestClient

from source.api import main
from source.api.config import ErrorConfiguracion
from source.api.downloader import ErrorDescarga
from source.api.models import ComunidadConfigurada, Oferta, SectorProfesional


def test_el_endpoint_parse_no_tiene_parametros_ni_cuerpo() -> None:
    operacion = main.app.openapi()["paths"]["/parse"]["get"]

    assert "parameters" not in operacion
    assert "requestBody" not in operacion


def test_parse_devuelve_resultados_por_comunidad(monkeypatch) -> None:
    comunidades = [
        ComunidadConfigurada("cantabria", "https://ejemplo.test/cantabria.pdf"),
        ComunidadConfigurada("asturias", "https://ejemplo.test/asturias.pdf"),
    ]

    monkeypatch.setattr(main, "cargar_comunidades", lambda: comunidades)
    monkeypatch.setattr(
        main,
        "descargar_pdf",
        lambda url: (
            b"%PDF-cantabria"
            if "cantabria" in url
            else ErrorDescarga("Error de descarga: HTTP 404.")
        ),
    )
    monkeypatch.setattr(
        main,
        "extraer_ofertas_desde_pdf",
        lambda contenido, comunidad: [
            Oferta(
                denominacion="Cocinero/a",
                sector_profesional=SectorProfesional(nombre="Hostelería"),
                comunidad=comunidad,
            )
        ],
    )

    respuesta = TestClient(main.app).get("/parse")

    assert respuesta.status_code == 200
    resultados = respuesta.json()["resultados"]
    assert resultados[0]["estado"] == "ok"
    assert resultados[0]["ofertas"][0]["comunidad"] == "cantabria"
    assert resultados[1] == {
        "comunidad": "asturias",
        "estado": "error",
        "error": "Error de descarga: HTTP 404.",
    }


def test_configuracion_ausente_devuelve_error_global(monkeypatch) -> None:
    def configuracion_ausente() -> list[ComunidadConfigurada]:
        raise ErrorConfiguracion("Error de configuración: no existe el fichero.")

    monkeypatch.setattr(main, "cargar_comunidades", configuracion_ausente)

    respuesta = TestClient(main.app).get("/parse")

    assert respuesta.status_code == 500


def test_no_importa_ni_crea_ficheros_de_base_de_datos(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "cargar_comunidades", lambda: [])

    respuesta = TestClient(main.app).get("/parse")

    codigo_api = [
        fichero.read_text(encoding="utf-8").lower()
        for fichero in Path(main.__file__).parent.rglob("*.py")
    ]
    assert respuesta.status_code == 200
    assert all("sqlite" not in codigo for codigo in codigo_api)
    assert all("sqlalchemy" not in codigo for codigo in codigo_api)
    assert not list(tmp_path.glob("*.db"))
    assert not list(tmp_path.glob("*.sqlite"))


def test_parse_integra_tres_comunidades_con_resultados_distintos(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    comunidades = [
        ComunidadConfigurada("cantabria", "https://ejemplo.test/accesible.pdf"),
        ComunidadConfigurada("asturias", "https://ejemplo.test/inaccesible.pdf"),
        ComunidadConfigurada("galicia", "https://ejemplo.test/sin-ofertas.pdf"),
    ]
    monkeypatch.setattr(main, "cargar_comunidades", lambda: comunidades)
    monkeypatch.setattr(
        main,
        "descargar_pdf",
        lambda url: (
            ErrorDescarga("Error de descarga: HTTP 503.")
            if "inaccesible" in url
            else (b"%PDF-sin-ofertas" if "sin-ofertas" in url else b"%PDF-ofertas")
        ),
    )

    def parsear_pdf(contenido: bytes, comunidad: str) -> list[Oferta]:
        if contenido == b"%PDF-sin-ofertas":
            return []
        return [
            Oferta(
                denominacion="Cocinero/a",
                municipio="Santander",
                codigo_oferta="062026003484",
                fecha_publicacion="04/11/2026",
                oficina="SANTANDER",
                descripcion="Preparación de menús.",
                sector_profesional=SectorProfesional(nombre="Hostelería"),
                comunidad=comunidad,
            )
        ]

    monkeypatch.setattr(main, "extraer_ofertas_desde_pdf", parsear_pdf)

    respuesta = TestClient(main.app).get("/parse")

    assert respuesta.status_code == 200
    resultados = respuesta.json()["resultados"]
    assert len(resultados) == 3
    assert resultados[0]["estado"] == "ok"
    assert resultados[0]["ofertas"] == [
        {
            "denominacion": "Cocinero/a",
            "municipio": "Santander",
            "codigo_oferta": "062026003484",
            "fecha_publicacion": "04/11/2026",
            "oficina": "SANTANDER",
            "descripcion": "Preparación de menús.",
            "sector_profesional": {"nombre": "Hostelería"},
            "comunidad": "cantabria",
        }
    ]
    assert resultados[1] == {
        "comunidad": "asturias",
        "estado": "error",
        "error": "Error de descarga: HTTP 503.",
    }
    assert resultados[2] == {
        "comunidad": "galicia",
        "estado": "ok",
        "ofertas": [],
    }
    assert respuesta.json()["metadatos"]["total_ofertas"] == 1
    assert not list(tmp_path.glob("*.db"))
    assert not list(tmp_path.glob("*.sqlite"))
