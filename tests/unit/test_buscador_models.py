"""Pruebas unitarias de las entidades de dominio del rastreador del buscador."""

from source.api.buscador.models import (
    CodigoVisto,
    ConfigBuscador,
    ErrorOferta,
    HtmlFallido,
    OfertaBuscador,
    ResultadoPasada,
)


def test_oferta_buscador_conserva_todos_los_campos_publicados() -> None:
    """OfertaBuscador conserva los ocho campos que publica la ficha."""
    oferta = OfertaBuscador(
        numero_oferta="062026003633",
        ocupacion="Cocinero/a",
        municipio="SANTANDER",
        provincia="CANTABRIA",
        fecha_inicio_difusion="18/11/2026",
        fecha_fin_difusion="03/12/2026",
        texto_libre="Preparación de menús diarios.",
        contacto="Email: ejemplo@empresa.com",
    )

    assert oferta.numero_oferta == "062026003633"
    assert oferta.ocupacion == "Cocinero/a"
    assert oferta.municipio == "SANTANDER"
    assert oferta.provincia == "CANTABRIA"
    assert oferta.fecha_inicio_difusion == "18/11/2026"
    assert oferta.fecha_fin_difusion == "03/12/2026"
    assert oferta.texto_libre == "Preparación de menús diarios."
    assert oferta.contacto == "Email: ejemplo@empresa.com"


def test_oferta_buscador_sector_nivel_contrato_vacios() -> None:
    """sector, nivel y contrato quedan vacíos sin inferir de otros campos."""
    oferta = OfertaBuscador(
        numero_oferta="062026003633",
        ocupacion="Cocinero/a",
        municipio="SANTANDER",
        provincia="CANTABRIA",
        fecha_inicio_difusion="18/11/2026",
        fecha_fin_difusion="03/12/2026",
        texto_libre="Hostelería y turismo en Cantabria.",
        contacto="Tel: 942000000",
    )

    # Los campos reservados están presentes pero vacíos
    assert oferta.sector == ""
    assert oferta.nivel == ""
    assert oferta.contrato == ""

    # No se infieren del texto libre ni de la ocupación
    assert "Hostelería" not in oferta.sector
    assert "Hostelería" not in oferta.nivel
    assert "Hostelería" not in oferta.contrato


def test_oferta_buscador_sin_contacto_no_inventa_empresa() -> None:
    """Sin contacto el campo queda vacío y no aparece ningún campo empresa."""
    oferta = OfertaBuscador(
        numero_oferta="062026003633",
        ocupacion="Cocinero/a",
        municipio="SANTANDER",
        provincia="CANTABRIA",
        fecha_inicio_difusion="18/11/2026",
        fecha_fin_difusion="03/12/2026",
        texto_libre="Descripción de la oferta.",
    )

    assert oferta.contacto == ""
    assert not hasattr(oferta, "empresa")
    assert not hasattr(oferta, "nombre_empresa")
    # No hay campos de persistencia en base de datos
    assert not hasattr(oferta, "id")
    assert not hasattr(oferta, "sqlite_id")


def test_oferta_buscador_comunidad_por_defecto_cantabria() -> None:
    """La comunidad por defecto es Cantabria (SUP-003)."""
    oferta = OfertaBuscador(
        numero_oferta="062026003633",
        ocupacion="Cocinero/a",
        municipio="SANTANDER",
        provincia="CANTABRIA",
        fecha_inicio_difusion="18/11/2026",
        fecha_fin_difusion="03/12/2026",
        texto_libre="Descripción.",
        contacto="Email: ejemplo@empresa.com",
    )

    assert oferta.comunidad == "Cantabria"
    # La provincia es el dato publicado por la ficha, no una copia de la comunidad
    assert oferta.provincia == "CANTABRIA"
    assert oferta.comunidad != oferta.provincia


def test_resultado_pasada_con_errores_vacios() -> None:
    """ResultadoPasada puede construirse con lista de errores vacía."""
    resultado = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=93,
        ofertas_nuevas=[
            OfertaBuscador(numero_oferta="062026003633"),
            OfertaBuscador(numero_oferta="062026003484"),
        ],
    )

    assert resultado.error_global == ""
    assert resultado.errores_por_oferta == []
    assert len(resultado.ofertas_nuevas) == 2


def test_resultado_pasada_con_error_global_y_error_por_oferta() -> None:
    """ResultadoPasada acepta un error global más errores por oferta."""
    resultado = ResultadoPasada(
        timestamp="2026-11-18T01:00:00",
        comunidad="Cantabria",
        total_listado=93,
        error_global="El portal no respondió en el timeout esperado.",
        errores_por_oferta=[
            ErrorOferta(
                codigo="062026003633",
                mensaje="No se pudo extraer el campo de contacto.",
            ),
        ],
        ofertas_nuevas=[],
    )

    assert resultado.error_global == "El portal no respondió en el timeout esperado."
    assert len(resultado.errores_por_oferta) == 1
    assert resultado.errores_por_oferta[0].codigo == "062026003633"
    assert resultado.errores_por_oferta[0].mensaje == "No se pudo extraer el campo de contacto."
    assert resultado.ofertas_nuevas == []


def test_config_buscador_valores_por_defecto() -> None:
    """ConfigBuscador tiene valores por defecto razonables."""
    config = ConfigBuscador()

    assert config.hora_pasada == 1
    assert config.delay_peticiones == 10
    assert config.tamano_pagina == 75
    assert config.dias_purga == 7


def test_codigo_visto_simple() -> None:
    """CodigoVisto es una entidad simple con código."""
    codigo_visto = CodigoVisto(codigo="062026003633")

    assert codigo_visto.codigo == "062026003633"


def test_html_fallido_con_codigo_y_fecha() -> None:
    """HtmlFallido almacena código, fecha y contenido HTML."""
    html_fallido = HtmlFallido(
        codigo="062026003633",
        fecha="2026-11-18",
        html="<html><body>Ficha fallida</body></html>",
    )

    assert html_fallido.codigo == "062026003633"
    assert html_fallido.fecha == "2026-11-18"
    assert "Ficha fallida" in html_fallido.html


def test_error_oferta_con_codigo_y_mensaje() -> None:
    """ErrorOferta almacena código y mensaje de error."""
    error = ErrorOferta(
        codigo="062026003633",
        mensaje="Timeout al descargar la ficha.",
    )

    assert error.codigo == "062026003633"
    assert error.mensaje == "Timeout al descargar la ficha."
