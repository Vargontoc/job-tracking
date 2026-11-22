"""Pruebas unitarias del evaluador de desaparición y ausencias consecutivas.

Mockea el ``cliente_persistencia``, el ``repositorio_presencia`` y el
repositorio de ``abstenciones`` para controlar las respuestas sin depender
de la red ni de la base de datos.
"""

from unittest.mock import MagicMock

from source.api.historico.desaparicion import (
    EvaluadorDesaparicion,
    ResultadoDesaparicion,
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
    fecha_fin_difusion: str | None = None,
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


def _crear_repositorio_mock(ausencias_consecutivas: bool = False) -> MagicMock:
    """Crea un mock de ``repositorio_presencia``.

    Por defecto, ``ausencias_consecutivas`` devuelve ``False`` (la oferta
    no se cierra). Si se pasa ``True``, devuelve ``True`` (se cierra).
    """
    repo = MagicMock()
    repo.registrar_presencia.return_value = None
    repo.registrar_ausencia.return_value = None
    repo.ausencias_consecutivas.return_value = ausencias_consecutivas
    return repo


def _crear_cliente_mock() -> MagicMock:
    """Crea un mock de ``cliente_persistencia`` que cierra con éxito."""
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = True
    return cliente


def _crear_abstenciones_mock() -> MagicMock:
    """Crea un mock de ``repositorio_abstenciones``."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Pruebas: presencia en el listado → vigente
# ---------------------------------------------------------------------------


def test_presente_en_listado_oficial_permanece_vigente():
    """Candidata presente en el listado oficial permanece vigente (REQ-005)."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=False)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = {"062026003633", "062026004444"}

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert resultado.errores == []
    # Se registró presencia.
    repo.registrar_presencia.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )
    repo.registrar_ausencia.assert_not_called()
    # No se intentó cerrar.
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: ausente en el listado actual pero presente en el anterior → vigente
# ---------------------------------------------------------------------------


def test_ausente_actual_presente_anterior_permanece_vigente():
    """Ausente en el listado actual, pero ausencias_consecutivas=False
    (por presencia anterior) → la oferta permanece vigente (margen de 1 día).
    """
    repo = _crear_repositorio_mock(ausencias_consecutivas=False)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()  # No está en el listado actual.

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert resultado.errores == []
    # Se registró ausencia.
    repo.registrar_ausencia.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )
    repo.registrar_presencia.assert_not_called()
    # No se intentó cerrar (el repositorio indica que no hay N ausencias).
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: ausente en dos listados consecutivos → cerrada
# ---------------------------------------------------------------------------


def test_ausente_en_dos_listados_consecutivos_se_cierra():
    """Ausente en el actual y en el anterior (N=2) → se cierra (REQ-005)."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()  # No está en el listado actual.

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == ["062026003633"]
    assert resultado.errores == []
    # Se intentó cerrar con la fecha del listado.
    cliente.cerrar_oferta.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )


# ---------------------------------------------------------------------------
# Pruebas: N=1, cierre inmediato tras 1 ausencia
# ---------------------------------------------------------------------------


def test_con_n_1_cierre_inmediato_tras_una_ausencia():
    """Con N=1, basta una sola ausencia para cerrar."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=1)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()  # Ausente.

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == ["062026003633"]
    repo.ausencias_consecutivas.assert_called_once_with(
        "062026003633", "Cantabria", 1
    )
    cliente.cerrar_oferta.assert_called_once()


def test_con_n_3_se_requieren_tres_ausencias():
    """Con N=3, se requieren tres listados sin el código."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=False)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=3)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    # El repositorio indica que aún no hay 3 ausencias consecutivas.
    assert resultado.cerradas == []
    repo.ausencias_consecutivas.assert_called_once_with(
        "062026003633", "Cantabria", 3
    )
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: errores al cerrar
# ---------------------------------------------------------------------------


def test_error_al_cerrar_no_lanza_excepcion():
    """Un error al cerrar se captura sin lanzar excepción."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = ErrorPersistencia(
        motivo="Error de red al cerrar la oferta."
    )
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "062026003633" in resultado.errores[0]
    assert "Error de red" in resultado.errores[0]


def test_oferta_no_encontrada_al_cerrar_genera_error():
    """Si la oferta no existe en persistencia, se registra un error."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = MagicMock()
    cliente.cerrar_oferta.return_value = False
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "no existe" in resultado.errores[0]


def test_excepcion_al_cerrar_se_captura():
    """Una excepción del cliente al cerrar se captura sin lanzar."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = MagicMock()
    cliente.cerrar_oferta.side_effect = RuntimeError("Fallo inesperado")
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "Fallo inesperado" in resultado.errores[0]


# ---------------------------------------------------------------------------
# Pruebas: verificación del registro de presencia/ausencia
# ---------------------------------------------------------------------------


def test_se_registra_presencia_cuando_codigo_esta_en_listado():
    """La presencia queda registrada para la fecha del listado (REQ-005)."""
    repo = _crear_repositorio_mock()
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones)

    ofertas = [_oferta(codigo="062026003633")]
    listado = {"062026003633"}

    evaluador.evaluar(ofertas, listado, set(), "2026-11-22")

    repo.registrar_presencia.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-22"
    )
    repo.registrar_ausencia.assert_not_called()


def test_se_registra_ausencia_cuando_codigo_no_esta_en_listado():
    """La ausencia queda registrada para la fecha del listado (REQ-005)."""
    repo = _crear_repositorio_mock()
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()  # Ausente.

    evaluador.evaluar(ofertas, listado, set(), "2026-11-22")

    repo.registrar_ausencia.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-22"
    )
    repo.registrar_presencia.assert_not_called()


def test_registrar_presencia_fallido_genera_error_y_no_intenta_cerrar():
    """Si el registro de presencia falla, se genera error y no se cierra."""
    repo = MagicMock()
    repo.registrar_ausencia.side_effect = RuntimeError("BD corrupta")
    repo.registrar_presencia.side_effect = RuntimeError("BD corrupta")
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    assert len(resultado.errores) == 1
    assert "BD corrupta" in resultado.errores[0]
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: códigos con error (errores_por_oferta)
# ---------------------------------------------------------------------------


def test_codigo_con_error_no_se_cierra_y_se_registra_abstencion():
    """Código en errores_por_oferta no se cierra; se registra abstención
    con el código y motivo (REQ-007, ALT-003).
    """
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = set()
    errores = {"062026003633"}

    resultado = evaluador.evaluar(ofertas, listado, errores, "2026-11-21")

    assert resultado.cerradas == []
    # No se registró presencia/ausencia ni se intentó cerrar.
    repo.registrar_presencia.assert_not_called()
    repo.registrar_ausencia.assert_not_called()
    cliente.cerrar_oferta.assert_not_called()
    # Se registró abstención con el código.
    abstenciones.registrar.assert_called_once_with(
        motivo="Código con error en la pasada del buscador",
        timestamp="2026-11-21",
        codigos_afectados=["062026003633"],
    )


# ---------------------------------------------------------------------------
# Pruebas: estado sin_ficha
# ---------------------------------------------------------------------------


def test_oferta_sin_ficha_no_se_cierra():
    """Oferta en estado sin_ficha no se cierra aunque no aparezca (REQ-009)."""
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026005555", estado="sin_ficha")]
    listado = set()

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    assert resultado.cerradas == []
    repo.registrar_presencia.assert_not_called()
    repo.registrar_ausencia.assert_not_called()
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: idempotencia y reaparición
# ---------------------------------------------------------------------------


def test_oferta_ya_cerrada_no_se_reabre():
    """Una oferta cerrada por desaparición que reaparece permanece cerrada.

    El evaluador solo recibe candidatas vigentes; si una oferta ya está
    cerrada, no entra en el evaluador. Esta prueba simula que una oferta
    que ya fue cerrada en evaluaciones previas vuelve a aparecer en el
    listado. Como el repositorio indica que la última marca es presencia
    (ausencias_consecutivas=False), el evaluador no intenta cerrar.
    """
    repo = _crear_repositorio_mock(ausencias_consecutivas=False)
    cliente = _crear_cliente_mock()
    cliente.cerrar_oferta.return_value = True  # Idempotente.
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [_oferta(codigo="062026003633")]
    listado = {"062026003633"}  # Ha reaparecido en el listado.

    resultado = evaluador.evaluar(ofertas, listado, set(), "2026-11-21")

    # La oferta está presente → se registró presencia.
    repo.registrar_presencia.assert_called_once()
    # El repositorio indica que la última marca es presencia → no se cierra.
    assert resultado.cerradas == []
    cliente.cerrar_oferta.assert_not_called()


# ---------------------------------------------------------------------------
# Pruebas: cierre no vacía texto ni contacto
# ---------------------------------------------------------------------------


def test_cerrar_no_vacia_texto_ni_contacto():
    """El cierre no vacía texto_libre ni contacto (REQ-010).

    El evaluador no toca esos campos; es responsabilidad del cliente de
    persistencia (TASK-009) preservarlos.
    """
    repo = _crear_repositorio_mock(ausencias_consecutivas=True)
    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    oferta = _oferta(
        texto_libre="Texto importante.",
        contacto="correo@example.com",
    )
    listado = set()

    evaluador.evaluar([oferta], listado, set(), "2026-11-21")

    # El evaluador solo pasa comunidad, codigo y fecha_cierre al cliente.
    cliente.cerrar_oferta.assert_called_once_with(
        "Cantabria", "062026003633", "2026-11-21"
    )
    args, kwargs = cliente.cerrar_oferta.call_args
    assert "texto_libre" not in kwargs
    assert "contacto" not in kwargs


# ---------------------------------------------------------------------------
# Pruebas: mezcla de escenarios
# ---------------------------------------------------------------------------


def test_evaluar_varias_ofertas_con_distintos_escenarios():
    """Evaluar varias candidatas con distintos estados simultáneos."""
    repo = MagicMock()
    repo.registrar_presencia.return_value = None
    repo.registrar_ausencia.return_value = None
    # Las ausencias consecutivas dependen del código.
    def ausencias_side_effect(codigo, comunidad, n):
        return codigo == "000000000003"  # Solo la tercera se cierra.
    repo.ausencias_consecutivas.side_effect = ausencias_side_effect

    cliente = _crear_cliente_mock()
    abstenciones = _crear_abstenciones_mock()
    evaluador = EvaluadorDesaparicion(repo, cliente, abstenciones, n_ausencias=2)

    ofertas = [
        _oferta(codigo="000000000001"),  # Presente → vigente
        _oferta(codigo="000000000002"),  # Ausente pero sin N ausencias → vigente
        _oferta(codigo="000000000003"),  # Ausente con N ausencias → cerrada
        _oferta(codigo="000000000004", estado="sin_ficha"),  # sin_ficha → skip
        _oferta(codigo="000000000005"),  # Con error → abstención
    ]
    listado = {"000000000001"}  # Solo la primera está presente.
    errores = {"000000000005"}

    resultado = evaluador.evaluar(ofertas, listado, errores, "2026-11-21")

    assert resultado.cerradas == ["000000000003"]
    # La 1 se registró como presente.
    repo.registrar_presencia.assert_any_call(
        "Cantabria", "000000000001", "2026-11-21"
    )
    # La 2 y 3 se registraron como ausentes.
    repo.registrar_ausencia.assert_any_call(
        "Cantabria", "000000000002", "2026-11-21"
    )
    repo.registrar_ausencia.assert_any_call(
        "Cantabria", "000000000003", "2026-11-21"
    )
    # La 4 (sin_ficha) no se procesó: ni presencia ni ausencia ni cierre.
    for call in repo.registrar_presencia.call_args_list:
        assert call[0][1] != "000000000004"
    for call in repo.registrar_ausencia.call_args_list:
        assert call[0][1] != "000000000004"
    # La 5 (con error) generó abstención, no presencia/ausencia ni cierre.
    abstenciones.registrar.assert_called_once_with(
        motivo="Código con error en la pasada del buscador",
        timestamp="2026-11-21",
        codigos_afectados=["000000000005"],
    )
    # La 5 no pasó por registro de presencia/ausencia.
    for call in repo.registrar_presencia.call_args_list:
        assert call[0][1] != "000000000005"
    for call in repo.registrar_ausencia.call_args_list:
        assert call[0][1] != "000000000005"