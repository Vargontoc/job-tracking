"""Pruebas unitarias del ensamblador de resultados."""

from source.api.buscador.assembler import ensamblar_resultado_pasada
from source.api.buscador.models import OfertaBuscador, ErrorOferta


def test_ensamblar_resultado_exitoso():
    """Debe ensamblar un resultado con ofertas nuevas y errores por oferta."""
    ofertas = [
        OfertaBuscador(
            numero_oferta="062026003484",
            ocupacion="Desarrollador",
            municipio="Santander",
        ),
        OfertaBuscador(
            numero_oferta="062026003485",
            ocupacion="Analista",
            municipio="Madrid",
        ),
    ]
    errores = [
        ErrorOferta(
            codigo="062026003486",
            mensaje="Error al parsear la oferta",
        ),
    ]

    resultado = ensamblar_resultado_pasada(
        timestamp_inicio="2024-01-15T10:00:00",
        timestamp_fin="2024-01-15T10:30:00",
        ofertas_nuevas=ofertas,
        errores_por_oferta=errores,
        error_global="",
        total_listado=10,
        comunidad="Cantabria",
    )

    assert resultado.timestamp == "2024-01-15T10:00:00"
    assert resultado.comunidad == "Cantabria"
    assert resultado.total_listado == 10
    assert resultado.error_global == ""
    assert len(resultado.errores_por_oferta) == 1
    assert len(resultado.ofertas_nuevas) == 2
    assert resultado.ofertas_nuevas[0].numero_oferta == "062026003484"


def test_ensamblar_resultado_con_error_global():
    """Con error global, debe excluir las ofertas nuevas."""
    ofertas = [
        OfertaBuscador(
            numero_oferta="062026003484",
            ocupacion="Desarrollador",
            municipio="Santander",
        ),
    ]
    errores = [
        ErrorOferta(
            codigo="062026003485",
            mensaje="Error al parsear",
        ),
    ]

    resultado = ensamblar_resultado_pasada(
        timestamp_inicio="2024-01-15T10:00:00",
        timestamp_fin="2024-01-15T10:30:00",
        ofertas_nuevas=ofertas,
        errores_por_oferta=errores,
        error_global="Timeout al conectar con el portal",
        total_listado=0,
        comunidad="Cantabria",
    )

    assert resultado.error_global == "Timeout al conectar con el portal"
    assert len(resultado.ofertas_nuevas) == 0
    assert len(resultado.errores_por_oferta) == 1


def test_ensamblar_resultado_listado_vacio():
    """Con listado vacío, debe retornar total cero y sin errores."""
    resultado = ensamblar_resultado_pasada(
        timestamp_inicio="2024-01-15T10:00:00",
        timestamp_fin="2024-01-15T10:01:00",
        ofertas_nuevas=[],
        errores_por_oferta=[],
        error_global="",
        total_listado=0,
        comunidad="Cantabria",
    )

    assert resultado.total_listado == 0
    assert resultado.error_global == ""
    assert len(resultado.ofertas_nuevas) == 0
    assert len(resultado.errores_por_oferta) == 0


def test_ensamblar_resultado_comunidad_por_defecto():
    """La comunidad por defecto debe ser Cantabria."""
    resultado = ensamblar_resultado_pasada(
        timestamp_inicio="2024-01-15T10:00:00",
        timestamp_fin="2024-01-15T10:01:00",
        ofertas_nuevas=[],
        errores_por_oferta=[],
        error_global="",
        total_listado=5,
    )

    assert resultado.comunidad == "Cantabria"


def test_ensamblar_resultado_sin_campos_de_persistencia():
    """El resultado no debe contener campos de persistencia en base de datos."""
    resultado = ensamblar_resultado_pasada(
        timestamp_inicio="2024-01-15T10:00:00",
        timestamp_fin="2024-01-15T10:30:00",
        ofertas_nuevas=[],
        errores_por_oferta=[],
        error_global="",
        total_listado=10,
        comunidad="Cantabria",
    )

    # Verificar que no hay campos de persistencia
    assert not hasattr(resultado, "id")
    assert not hasattr(resultado, "db_id")
    assert not hasattr(resultado, "sqlite_id")

    # Verificar que tiene solo los campos esperados
    atributos_esperados = {
        "timestamp",
        "comunidad",
        "total_listado",
        "error_global",
        "errores_por_oferta",
        "ofertas_nuevas",
    }
    atributos_reales = set(vars(resultado).keys())
    assert atributos_reales == atributos_esperados
