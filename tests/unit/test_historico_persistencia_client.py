"""Pruebas unitarias del cliente de persistencia-api para el histórico.

Mockea ``httpx.Client`` para simular las respuestas de los tres endpoints
consumidos: ``GET /persistencia/ofertas/vigentes``, ``GET
/persistencia/ofertas/{comunidad}/{codigo}`` y ``POST /persistencia/ofertas``.
"""

from unittest.mock import MagicMock

import httpx

from source.api.historico.persistencia_client import (
    ClientePersistencia,
    ErrorPersistencia,
    Oferta,
    ResultadoConsulta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _respuesta_json(status_code: int, datos: object) -> MagicMock:
    """Crea un mock de ``httpx.Response`` con un JSON determinado."""
    respuesta = MagicMock(spec=httpx.Response)
    respuesta.status_code = status_code
    respuesta.json.return_value = datos
    if status_code >= 400:
        # Simular el comportamiento de raise_for_status
        error = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=respuesta,
        )
        respuesta.raise_for_status.side_effect = error
    else:
        respuesta.raise_for_status.return_value = None
    return respuesta


def _oferta_vigente_json(
    comunidad: str = "Cantabria",
    codigo: str = "062026003633",
    estado: str = "vigente",
    **campos: object,
) -> dict:
    """Crea un diccionario JSON con los campos de ``OfertaSalida``."""
    datos = {
        "comunidad": comunidad,
        "provincia": "CANTABRIA",
        "codigo": codigo,
        "ocupacion": "Cocinero/a",
        "municipio": "SANTANDER",
        "sector": "",
        "nivel": "",
        "contrato": "",
        "fecha_inicio_difusion": "18/11/2026",
        "fecha_fin_difusion": "03/12/2026",
        "estado": estado,
        "texto_libre": "Preparación de menús.",
        "contacto": "contacto@example.com",
        "embedding": None,
        "embedding_model_name": None,
        "embedding_model_version": None,
        "embedding_dim": None,
        "interesada": False,
        "fecha_alta": "2026-11-18T01:05:00+00:00",
        "fecha_cierre": None,
        "fecha_ultima_actualizacion": "2026-11-18T01:05:00+00:00",
    }
    datos.update(campos)
    return datos


def _crear_cliente_mock() -> MagicMock:
    """Crea un mock de ``httpx.Client``."""
    return MagicMock(spec=httpx.Client)


# ---------------------------------------------------------------------------
# Tests de listar_vigentes
# ---------------------------------------------------------------------------

class TestListarVigentes:
    """Pruebas de ``ClientePersistencia.listar_vigentes()``."""

    def test_devuelve_solo_ofertas_vigentes(self) -> None:
        """listar_vigentes devuelve solo ofertas con estado 'vigente'."""
        cliente_mock = _crear_cliente_mock()
        ofertas_json = [
            _oferta_vigente_json(codigo="062026003633", estado="vigente"),
            _oferta_vigente_json(
                codigo="062026011705", estado="vigente",
                ocupacion="Auxiliar de enfermería",
            ),
        ]
        cliente_mock.get.return_value = _respuesta_json(200, ofertas_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.listar_vigentes()

        assert isinstance(resultado, list)
        assert len(resultado) == 2
        assert all(isinstance(o, Oferta) for o in resultado)
        assert resultado[0].codigo == "062026003633"
        assert resultado[0].estado == "vigente"
        assert resultado[1].codigo == "062026011705"
        assert resultado[1].ocupacion == "Auxiliar de enfermería"

    def test_url_correcta(self) -> None:
        """listar_vigentes consulta la URL correcta."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(200, [])

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        cliente.listar_vigentes()

        cliente_mock.get.assert_called_once_with(
            "http://localhost:8000/persistencia/ofertas/vigentes"
        )

    def test_url_base_con_trailing_slash(self) -> None:
        """listar_vigentes normaliza la URL base eliminando la barra final."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(200, [])

        cliente = ClientePersistencia(
            url_base="http://localhost:8000/", cliente_http=cliente_mock
        )
        cliente.listar_vigentes()

        cliente_mock.get.assert_called_once_with(
            "http://localhost:8000/persistencia/ofertas/vigentes"
        )

    def test_lista_vacia(self) -> None:
        """listar_vigentes devuelve lista vacía si no hay ofertas vigentes."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(200, [])

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.listar_vigentes()

        assert isinstance(resultado, list)
        assert len(resultado) == 0

    def test_campos_de_la_oferta(self) -> None:
        """Cada oferta devuelta tiene los campos del esquema de persistencia-api."""
        cliente_mock = _crear_cliente_mock()
        ofertas_json = [
            _oferta_vigente_json(
                codigo="062026003633",
                estado="vigente",
                embedding="AACAPwAAAAA=",
                embedding_model_name="nomic-embed-text",
                embedding_model_version="1.5",
                embedding_dim=3,
            ),
        ]
        cliente_mock.get.return_value = _respuesta_json(200, ofertas_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.listar_vigentes()

        assert isinstance(resultado, list)
        oferta = resultado[0]
        assert oferta.comunidad == "Cantabria"
        assert oferta.codigo == "062026003633"
        assert oferta.estado == "vigente"
        assert oferta.fecha_alta == "2026-11-18T01:05:00+00:00"
        assert oferta.fecha_cierre is None
        assert oferta.fecha_fin_difusion == "03/12/2026"
        assert oferta.texto_libre == "Preparación de menús."
        assert oferta.contacto == "contacto@example.com"
        assert oferta.embedding == "AACAPwAAAAA="
        assert oferta.embedding_model_name == "nomic-embed-text"
        assert oferta.embedding_model_version == "1.5"
        assert oferta.embedding_dim == 3

    def test_error_http(self) -> None:
        """Error HTTP en listar_vigentes devuelve ErrorPersistencia."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(503, {
            "detail": "El repositorio de persistencia no está disponible"
        })

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.listar_vigentes()

        assert isinstance(resultado, ErrorPersistencia)
        assert "503" in resultado.motivo

    def test_error_de_red(self) -> None:
        """Error de red en listar_vigentes devuelve ErrorPersistencia."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.side_effect = httpx.ConnectError("Connection refused")

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.listar_vigentes()

        assert isinstance(resultado, ErrorPersistencia)
        assert "Error de red" in resultado.motivo


# ---------------------------------------------------------------------------
# Tests de consultar_por_clave
# ---------------------------------------------------------------------------

class TestConsultarPorClave:
    """Pruebas de ``ClientePersistencia.consultar_por_clave()``."""

    def test_devuelve_oferta_encontrada(self) -> None:
        """Consultar por clave existente devuelve ResultadoConsulta con encontrada=True."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json(
            comunidad="Cantabria", codigo="062026003633", estado="vigente"
        )
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.consultar_por_clave("Cantabria", "062026003633")

        assert isinstance(resultado, ResultadoConsulta)
        assert resultado.encontrada is True
        assert resultado.oferta is not None
        assert resultado.oferta.estado == "vigente"
        assert resultado.oferta.codigo == "062026003633"
        assert resultado.oferta.comunidad == "Cantabria"
        assert resultado.error is None

    def test_devuelve_estado_y_fechas(self) -> None:
        """Consultar por clave devuelve el estado actual y las fechas de la oferta."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json(
            estado="cerrada",
            fecha_cierre="2026-11-20T02:00:00+00:00",
        )
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.consultar_por_clave("Cantabria", "062026003633")

        assert resultado.encontrada is True
        assert resultado.oferta is not None
        assert resultado.oferta.estado == "cerrada"
        assert resultado.oferta.fecha_cierre == "2026-11-20T02:00:00+00:00"
        assert resultado.oferta.fecha_alta == "2026-11-18T01:05:00+00:00"

    def test_url_correcta(self) -> None:
        """Consultar por clave usa la URL correcta con comunidad y codigo."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json()
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        cliente.consultar_por_clave("Cantabria", "062026003633")

        cliente_mock.get.assert_called_once_with(
            "http://localhost:8000/persistencia/ofertas/Cantabria/062026003633"
        )

    def test_clave_inexistente_sin_excepcion(self) -> None:
        """Consultar clave inexistente devuelve encontrada=False sin excepción."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(404, {
            "detail": "No se encontró la oferta (Cantabria, 062026999999)"
        })

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.consultar_por_clave("Cantabria", "062026999999")

        assert isinstance(resultado, ResultadoConsulta)
        assert resultado.encontrada is False
        assert resultado.oferta is None
        assert resultado.error is None

    def test_error_http_distinto_de_404(self) -> None:
        """Error HTTP distinto de 404 devuelve error de comunicación."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(503, {
            "detail": "El repositorio no está disponible"
        })

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.consultar_por_clave("Cantabria", "062026003633")

        assert isinstance(resultado, ResultadoConsulta)
        assert resultado.encontrada is False
        assert resultado.oferta is None
        assert resultado.error is not None
        assert isinstance(resultado.error, ErrorPersistencia)
        assert "503" in resultado.error.motivo

    def test_error_de_red(self) -> None:
        """Error de red devuelve error de comunicación."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.side_effect = httpx.ConnectError("Connection refused")

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.consultar_por_clave("Cantabria", "062026003633")

        assert isinstance(resultado, ResultadoConsulta)
        assert resultado.error is not None
        assert "Error de red" in resultado.error.motivo


# ---------------------------------------------------------------------------
# Tests de cerrar_oferta
# ---------------------------------------------------------------------------

class TestCerrarOferta:
    """Pruebas de ``ClientePersistencia.cerrar_oferta()``."""

    def _configurar_consulta_exitosa(
        self,
        cliente_mock: MagicMock,
        oferta_json: dict | None = None,
    ) -> None:
        """Configura el mock para que la primera llamada (GET) devuelva la oferta."""
        if oferta_json is None:
            oferta_json = _oferta_vigente_json()
        respuesta_get = _respuesta_json(200, oferta_json)
        respuesta_post = _respuesta_json(200, {
            "comunidad": oferta_json["comunidad"],
            "codigo": oferta_json["codigo"],
            "estado": "cerrada",
            "mensaje": "oferta persistida correctamente",
        })
        cliente_mock.get.return_value = respuesta_get
        cliente_mock.post.return_value = respuesta_post

    def test_cerrar_oferta_vigente(self) -> None:
        """Cerrar una oferta vigente devuelve True."""
        cliente_mock = _crear_cliente_mock()
        self._configurar_consulta_exitosa(cliente_mock)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        assert resultado is True

    def test_cerrar_preserva_texto_y_contacto(self) -> None:
        """Cerrar no vacía texto_libre ni contacto (REQ-010)."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json(
            texto_libre="Preparación de menús.",
            contacto="contacto@example.com",
            embedding="AACAPwAAAAA=",
            embedding_model_name="nomic-embed-text",
            embedding_model_version="1.5",
            embedding_dim=3,
        )
        self._configurar_consulta_exitosa(cliente_mock, oferta_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        # Comprobar que el POST incluye el cuerpo completo con texto y contacto.
        cliente_mock.post.assert_called_once()
        _, kwargs = cliente_mock.post.call_args
        cuerpo = kwargs["json"]
        assert cuerpo["estado"] == "cerrada"
        assert cuerpo["texto_libre"] == "Preparación de menús."
        assert cuerpo["contacto"] == "contacto@example.com"
        assert cuerpo["embedding"] == "AACAPwAAAAA="
        assert cuerpo["embedding_model_name"] == "nomic-embed-text"
        assert cuerpo["embedding_model_version"] == "1.5"
        assert cuerpo["embedding_dim"] == 3

    def test_ya_cerrada_no_cambia_fecha_cierre(self) -> None:
        """Cerrar una oferta ya cerrada no modifica su fecha_cierre (idempotente)."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json(
            estado="cerrada",
            fecha_cierre="2026-11-19T02:00:00+00:00",
        )
        # La consulta devuelve la oferta ya cerrada.
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        # Debe devolver True sin hacer POST.
        assert resultado is True
        cliente_mock.post.assert_not_called()

    def test_clave_inexistente_devuelve_false(self) -> None:
        """Cerrar una oferta inexistente devuelve False sin excepción."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.return_value = _respuesta_json(404, {
            "detail": "No se encontró la oferta (Cantabria, 062026999999)"
        })

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026999999", "2026-11-21T02:00:00+00:00"
        )

        assert resultado is False
        cliente_mock.post.assert_not_called()

    def test_error_en_consulta_pre_cierre(self) -> None:
        """Si la consulta previa al cierre falla, devuelve ErrorPersistencia."""
        cliente_mock = _crear_cliente_mock()
        cliente_mock.get.side_effect = httpx.ConnectError("Connection refused")

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        assert isinstance(resultado, ErrorPersistencia)
        assert "Error de red" in resultado.motivo

    def test_error_http_en_post(self) -> None:
        """Error HTTP en el POST de cierre devuelve ErrorPersistencia."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json()
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)
        cliente_mock.post.return_value = _respuesta_json(500, {
            "detail": "Error interno"
        })

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        assert isinstance(resultado, ErrorPersistencia)
        assert "500" in resultado.motivo

    def test_url_del_post(self) -> None:
        """El POST de cierre se envía a la URL correcta."""
        cliente_mock = _crear_cliente_mock()
        self._configurar_consulta_exitosa(cliente_mock)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        cliente_mock.post.assert_called_once()
        args, _ = cliente_mock.post.call_args
        assert args[0] == "http://localhost:8000/persistencia/ofertas"

    def test_cuerpo_del_post_tiene_estado_cerrada(self) -> None:
        """El cuerpo del POST tiene estado='cerrada' y la fecha_cierre indicada."""
        cliente_mock = _crear_cliente_mock()
        self._configurar_consulta_exitosa(cliente_mock)

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        _, kwargs = cliente_mock.post.call_args
        cuerpo = kwargs["json"]
        assert cuerpo["estado"] == "cerrada"
        assert cuerpo["fecha_cierre"] == "2026-11-21T02:00:00+00:00"
        assert cuerpo["comunidad"] == "Cantabria"
        assert cuerpo["codigo"] == "062026003633"

    def test_error_de_red_en_post(self) -> None:
        """Error de red en el POST devuelve ErrorPersistencia."""
        cliente_mock = _crear_cliente_mock()
        oferta_json = _oferta_vigente_json()
        cliente_mock.get.return_value = _respuesta_json(200, oferta_json)
        cliente_mock.post.side_effect = httpx.ConnectError("Connection refused")

        cliente = ClientePersistencia(
            url_base="http://localhost:8000", cliente_http=cliente_mock
        )
        resultado = cliente.cerrar_oferta(
            "Cantabria", "062026003633", "2026-11-21T02:00:00+00:00"
        )

        assert isinstance(resultado, ErrorPersistencia)
        assert "Error de red" in resultado.motivo


# ---------------------------------------------------------------------------
# Tests de restricciones de alcance
# ---------------------------------------------------------------------------

class TestRestriccionesAlcance:
    """El cliente no expone creación de ofertas nuevas ni listado de códigos."""

    def test_no_expone_creacion_de_ofertas(self) -> None:
        """El cliente no tiene un método para crear ofertas nuevas."""
        cliente = ClientePersistencia(url_base="http://localhost:8000")
        assert not hasattr(cliente, "crear_oferta")
        assert not hasattr(cliente, "insertar_oferta")
        assert not hasattr(cliente, "persistir_oferta")

    def test_no_expone_listado_codigos_vistos(self) -> None:
        """El cliente no tiene un método para listar códigos vistos."""
        cliente = ClientePersistencia(url_base="http://localhost:8000")
        assert not hasattr(cliente, "listar_codigos_vistos")
        assert not hasattr(cliente, "codigos_vistos")

    def test_no_expone_lectura_por_rango(self) -> None:
        """El cliente no tiene un método para leer por rango de fechas."""
        cliente = ClientePersistencia(url_base="http://localhost:8000")
        assert not hasattr(cliente, "altas_por_fecha")
        assert not hasattr(cliente, "cierres_por_fecha")
        assert not hasattr(cliente, "consultar_por_rango")
