"""Pruebas unitarias de las entidades de dominio."""

from source.api.models import Oferta, ResultadoPorComunidad, SectorProfesional


def test_oferta_conserva_todos_los_campos() -> None:
    sector = SectorProfesional(nombre="Hostelería")
    oferta = Oferta(
        denominacion="Cocinero/a",
        municipio="Santander",
        codigo_oferta="062026003484",
        fecha_publicacion="01/02/2026",
        oficina="Santander",
        descripcion="Preparación de menús.",
        sector_profesional=sector,
        comunidad="cantabria",
    )

    assert oferta.denominacion == "Cocinero/a"
    assert oferta.municipio == "Santander"
    assert oferta.codigo_oferta == "062026003484"
    assert oferta.fecha_publicacion == "01/02/2026"
    assert oferta.oficina == "Santander"
    assert oferta.descripcion == "Preparación de menús."
    assert oferta.sector_profesional is sector
    assert oferta.comunidad == "cantabria"


def test_oferta_permite_campos_ausentes_sin_empresa() -> None:
    oferta = Oferta(denominacion="Cocinero/a")

    assert oferta.municipio == ""
    assert oferta.oficina == ""
    assert not hasattr(oferta, "empresa")


def test_resultado_por_comunidad_admite_estado_ok_y_error() -> None:
    correcto = ResultadoPorComunidad(comunidad="cantabria", estado="ok")
    fallido = ResultadoPorComunidad(
        comunidad="asturias",
        estado="error",
        mensaje_error="No se pudo descargar el PDF.",
    )

    assert correcto.estado == "ok"
    assert correcto.ofertas == []
    assert fallido.estado == "error"
    assert fallido.mensaje_error == "No se pudo descargar el PDF."
