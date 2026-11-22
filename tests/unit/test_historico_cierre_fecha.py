"""Pruebas unitarias del evaluador de cierre por fecha de fin de difusión.

Mockea el ``cliente_persistencia`` y el ``reloj`` para controlar las fechas
y las respuestas del cierre sin depender de la red ni de la base de datos.
"""

from datetime import date
from unittest.mock import MagicMock

from source.api.historico.cierre_fecha import (
    EvaluadorCierreFecha,
    RelojFijo,
    ResultadoCierre,
)
from source.api.historico.persistencia_client import (
    ErrorPersistencia,
    Oferta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oferta(
    codigo: str = "062026003633",
    comunidad: str = "Cantabria",
    estado: str = "vigente",
    fecha_fin_difusion: str | None = "20/11/2026",
    texto_libre: str = "Preparación de menús.",
    contacto: str = "contacto@example.com",
) -> Oferta:
    """Crea una oferta de prueba con los campos mínimos necesarios."""
    return Oferta(
        comunidad=comunidad,
        codigo=codigo,
        estado=estado,
        fecha_fin_difusion=fecha_fin_difusion,
        texto_libre=texto_libre,
        contacto=contacto,
    )


def _crear_cliente_mock() -> MagicMock:
    """Crea un mock de ``cliente_persistencia`` que cierra con éxito."""
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = True
    return cliente


# ---------------------------------------------------------------------------
# Pruebas: cierre por fecha pasada
# ---------------------------------------------------------------------------

def test_fecha_fin_anterior_a_hoy_cierra_la_oferta():
    """fecha_fin_difusion = 20/11/2026, hoy = 21/11/2026 → cerrada."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(codigo="062026003633", fecha_fin_difusion="20/11/2026")]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == ["062026003633"]
    assert resultado.errores == []
    # La fecha_cierre debe ser la marca ISO del día actual.
    cliente.cerrar_oferta.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )


def test_fecha_fin_igual_a_hoy_no_cierra():
    """fecha_fin_difusion = 21/11/2026, hoy = 21/11/2026 → vigente."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(fecha_fin_difusion="21/11/2026")]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert resultado.errores == []
    cliente.cerrar_oferta.assert_not_called()


def test_fecha_fin_futura_no_cierra():
    """fecha_fin_difusion futura → la oferta permanece vigente."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(fecha_fin_difusion="30/12/2026")]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: idempotencia del cierre
# ---------------------------------------------------------------------------

def test_reevaluar_oferta_ya_cerrada_no_cambia_fecha_cierre():
    """Reevaluar una oferta que ya está cerrada no genera un segundo cierre.

    El cliente de persistencia es idempotente (TASK-009): si la oferta ya
    está cerrada, cerrar_oferta devuelve True sin modificar la fecha_cierre.
    El evaluador no tiene forma de distinguir una oferta ya cerrada de una
    que no lo está (solo recibe vigentes), pero el cliente sí lo maneja.
    """
    cliente = _crear_cliente_mock()
    # Simular que el cliente devuelve True (idempotente) sin cambiar nada.
    cliente.cerrar_oferta.return_value = True

    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(fecha_fin_difusion="20/11/2026")]

    resultado1 = evaluador.evaluar(ofertas)
    resultado2 = evaluador.evaluar(ofertas)

    assert resultado1.cerradas == ["062026003633"]
    assert resultado2.cerradas == ["062026003633"]
    # El cliente se llama en ambas evaluaciones (el evaluador no cachea).
    assert cliente.cerrar_oferta.call_count == 2


# ---------------------------------------------------------------------------
# Pruebas: ofertas sin fecha_fin_difusion
# ---------------------------------------------------------------------------

def test_fecha_fin_vacia_se_devuelve_como_candidata_a_desaparicion():
    """Oferta sin fecha_fin_difusion → candidata a cierre por desaparición."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    oferta_sin_fecha = _oferta(
        codigo="062026009999", fecha_fin_difusion=None
    )
    ofertas = [oferta_sin_fecha]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert len(resultado.candidatas_desaparicion) == 1
    assert resultado.candidatas_desaparicion[0].codigo == "062026009999"
    cliente.cerrar_oferta.assert_not_called()


def test_fecha_fin_texto_vacio_se_devuelve_como_candidata_a_desaparicion():
    """Oferta con fecha_fin_difusion = '' → candidata a desaparición."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    oferta = _oferta(codigo="062026008888", fecha_fin_difusion="")
    resultado = evaluador.evaluar([oferta])

    assert resultado.cerradas == []
    assert len(resultado.candidatas_desaparicion) == 1
    assert resultado.candidatas_desaparicion[0].codigo == "062026008888"


# ---------------------------------------------------------------------------
# Pruebas: fechas inválidas
# ---------------------------------------------------------------------------

def test_fecha_con_formato_incorrecto_se_descarta():
    """Fecha con formato distinto de dd/mm/aaaa → descartada e informada."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [
        _oferta(codigo="062026001111", fecha_fin_difusion="2026-11-20"),
    ]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert "062026001111" in resultado.fechas_invalidas
    assert any("062026001111" in error for error in resultado.errores)
    cliente.cerrar_oferta.assert_not_called()


def test_fecha_imposible_se_descarta():
    """Fecha imposible (31/02/2026) → descartada e informada (ALT-005)."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [
        _oferta(codigo="062026002222", fecha_fin_difusion="31/02/2026"),
    ]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert "062026002222" in resultado.fechas_invalidas
    assert any("062026002222" in error for error in resultado.errores)
    cliente.cerrar_oferta.assert_not_called()


def test_fecha_con_mes_fuera_de_rango_se_descarta():
    """Fecha con mes > 12 → descartada e informada."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [
        _oferta(codigo="062026007777", fecha_fin_difusion="15/13/2026"),
    ]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert "062026007777" in resultado.fechas_invalidas
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: estado sin_ficha
# ---------------------------------------------------------------------------

def test_oferta_sin_ficha_nunca_se_cierra_por_fecha():
    """Oferta en estado sin_ficha permanece sin_ficha (REQ-009)."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [
        _oferta(
            codigo="062026005555",
            estado="sin_ficha",
            fecha_fin_difusion="20/11/2026",
        ),
    ]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: zona horaria configurable
# ---------------------------------------------------------------------------

def test_con_otra_zona_horaria_se_usa_esa_zona():
    """Con otra zona configurada, la comparación usa esa zona (NFR-001)."""
    cliente = _crear_cliente_mock()
    # En America/New_York hoy es 20/11/2026 cuando en Europe/Madrid es 21/11.
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="America/New_York",
        reloj=RelojFijo(date(2026, 11, 20)),
    )
    ofertas = [_oferta(fecha_fin_difusion="19/11/2026")]

    resultado = evaluador.evaluar(ofertas)

    # 19/11 < 20/11 → se cierra.
    assert resultado.cerradas == ["062026003633"]
    cliente.cerrar_oferta.assert_called_once()


# ---------------------------------------------------------------------------
# Pruebas: errores al cerrar
# ---------------------------------------------------------------------------

def test_error_al_cerrar_no_lanza_excepcion():
    """Un error al cerrar se captura sin lanzar excepción."""
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = ErrorPersistencia(
        motivo="Error de red al cerrar la oferta."
    )
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(fecha_fin_difusion="20/11/2026")]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "062026003633" in resultado.errores[0]
    assert "Error de red" in resultado.errores[0]


def test_oferta_no_encontrada_al_cerrar_genera_error():
    """Si la oferta no existe en persistencia, se registra un error."""
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = False
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [_oferta(fecha_fin_difusion="20/11/2026")]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "no existe" in resultado.errores[0]


# ---------------------------------------------------------------------------
# Pruebas: el cierre no vacía texto ni contacto
# ---------------------------------------------------------------------------

def test_cerrar_no_vacia_texto_ni_contacto():
    """El cierre no vacía texto_libre ni contacto (REQ-010).

    El evaluador no toca esos campos; es responsabilidad del cliente de
    persistencia (TASK-009) preservarlos. Esta prueba verifica que el
    evaluador no pasa argumentos que pudieran vaciarlos.
    """
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    oferta = _oferta(
        texto_libre="Texto importante.",
        contacto="correo@example.com",
        fecha_fin_difusion="20/11/2026",
    )

    evaluador.evaluar([oferta])

    # El evaluador solo pasa comunidad, codigo y fecha_cierre al cliente.
    cliente.cerrar_oferta.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )
    # No se pasan texto_libre ni contacto como argumentos.
    args, kwargs = cliente.cerrar_oferta.call_args
    assert "texto_libre" not in kwargs
    assert "contacto" not in kwargs


# ---------------------------------------------------------------------------
# Pruebas: mezcla de escenarios
# ---------------------------------------------------------------------------

def test_evaluar_varias_ofertas_con_distintos_estados():
    """Evaluar varias ofertas con distintos estados y fechas."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    ofertas = [
        _oferta(codigo="000000000001", fecha_fin_difusion="20/11/2026"),  # cierra
        _oferta(codigo="000000000002", fecha_fin_difusion="21/11/2026"),  # vigente
        _oferta(codigo="000000000003", fecha_fin_difusion=None),  # candidata
        _oferta(codigo="000000000004", fecha_fin_difusion="31/02/2026"),  # inválida
        _oferta(codigo="000000000005", estado="sin_ficha", fecha_fin_difusion="20/11/2026"),  # sin_ficha
    ]

    resultado = evaluador.evaluar(ofertas)

    assert resultado.cerradas == ["000000000001"]
    assert "000000000003" in [o.codigo for o in resultado.candidatas_desaparicion]
    assert "000000000004" in resultado.fechas_invalidas
    # sin_ficha no aparece en ningún lado.
    assert "000000000005" not in resultado.cerradas
    assert "000000000005" not in resultado.fechas_invalidas


def test_oferta_vigente_con_fecha_fin_difusion_vacia_se_incluye_en_candidatas():
    """Una oferta vigente sin fecha_fin_difusion se incluye en candidatas_desaparicion (REQ-004)."""
    cliente = _crear_cliente_mock()
    evaluador = EvaluadorCierreFecha(
        cliente_persistencia=cliente,
        zona_horaria="Europe/Madrid",
        reloj=RelojFijo(date(2026, 11, 21)),
    )
    oferta = _oferta(codigo="062026004444", fecha_fin_difusion=None)
    resultado = evaluador.evaluar([oferta])

    assert resultado.cerradas == []
    assert len(resultado.candidatas_desaparicion) == 1
    assert resultado.candidatas_desaparicion[0].codigo == "062026004444"
    # La oferta sigue vigente.
    assert resultado.candidatas_desaparicion[0].estado == "vigente"
