"""Tests unitarios para el parser de fichas del buscador."""

from pathlib import Path

import pytest

from source.api.buscador.parser import (
    ResultadoFicha,
    _extraer_bloque,
    _extraer_campos,
    _extraer_input,
    _normalizar_espacios,
    parsear_ficha,
)
from source.api.buscador.rate_limiter import LimitadorPeticiones
from selectolax.lexbor import LexborHTMLParser


# Cargar el fixture real de la ficha
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "buscador"
FICHA_REAL = (FIXTURES_DIR / "ficha_062026003633.html").read_text(encoding="utf-8")


class ClienteMock:
    """Cliente HTTP mock para testing."""

    def __init__(self, respuestas: list):
        """
        Args:
            respuestas: Lista de tuplas (status_code, text, exception)
                       Si exception no es None, se lanza esa excepción.
        """
        self.respuestas = respuestas
        self.intentos = []
        self.user_agent_usado = None

    def get(self, url: str, timeout: float):
        if not self.respuestas:
            raise RuntimeError("No hay más respuestas mock")

        status_code, text, exception = self.respuestas.pop(0)
        self.intentos.append({"url": url, "timeout": timeout})

        if exception:
            raise exception

        class RespuestaMock:
            def __init__(self, status, text):
                self.status_code = status
                self.text = text

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        return RespuestaMock(status_code, text)


class RelojFalso:
    """Reloj falso para testing del rate limiter."""

    def __init__(self):
        self.tiempo_actual = 0.0

    def __call__(self):
        return self.tiempo_actual

    def avanzar(self, segundos: float):
        self.tiempo_actual += segundos


class DormirFalso:
    """Función de dormir falsa para testing."""

    def __init__(self):
        self.tiempos_dormidos = []

    def __call__(self, segundos: float):
        self.tiempos_dormidos.append(segundos)


@pytest.fixture
def limitador_rapido():
    """Limitador sin espera para tests rápidos."""
    return LimitadorPeticiones(
        delay_segundos=0.0,
        user_agent="test-agent"
    )


@pytest.fixture
def limitador_con_delay():
    """Limitador con delay de 10 segundos para tests de timing."""
    reloj = RelojFalso()
    dormir = DormirFalso()
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        user_agent="test-agent",
        reloj=reloj,
        dormir=dormir
    )
    return limitador, reloj, dormir


# --- Tests de extracción de campos ---


def test_extraer_campos_ficha_real():
    """Con la ficha real se extraen todos los campos correctamente."""
    oferta = _extraer_campos(FICHA_REAL)

    assert oferta.numero_oferta == "062026003633"
    assert oferta.ocupacion == "ORIENTADORES PROFESIONALES PARA LA INSERCIÓN"
    assert oferta.municipio == "SANTANDER"
    assert oferta.provincia == "CANTABRIA"
    assert oferta.fecha_inicio_difusion == "18/11/2026"
    assert oferta.fecha_fin_difusion == "03/12/2026"
    assert "INSTITUCIÓN SOCIAL" in oferta.texto_libre
    assert "ADMINISTRACON@COCINAECONOMICASANTANDER.ORG" in oferta.contacto


def test_campos_reservados_vacios():
    """sector/nivel/contrato vacíos sin inferencia (DEC-009)."""
    oferta = _extraer_campos(FICHA_REAL)

    assert oferta.sector == ""
    assert oferta.nivel == ""
    assert oferta.contrato == ""


def test_texto_libre_normalizado():
    """Texto libre y contacto normalizados (espacios colapsados)."""
    oferta = _extraer_campos(FICHA_REAL)

    # No debe haber múltiples espacios consecutivos
    assert "  " not in oferta.texto_libre
    assert "  " not in oferta.contacto
    # No debe haber saltos de línea
    assert "\n" not in oferta.texto_libre
    assert "\n" not in oferta.contacto


def test_fechas_formato_dd_mm_aaaa():
    """Fechas en formato dd/mm/aaaa."""
    oferta = _extraer_campos(FICHA_REAL)

    # Verificar formato dd/mm/aaaa
    import re
    patron_fecha = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    assert patron_fecha.match(oferta.fecha_inicio_difusion)
    assert patron_fecha.match(oferta.fecha_fin_difusion)


def test_numero_oferta_12_digitos():
    """Número de oferta como texto de 12 dígitos."""
    oferta = _extraer_campos(FICHA_REAL)

    assert len(oferta.numero_oferta) == 12
    assert oferta.numero_oferta.isdigit()
    assert oferta.numero_oferta == "062026003633"


def test_ficha_sin_contacto():
    """Variante sin contacto → contacto vacío y resto conservado."""
    # Crear variante sin el bloque de contacto
    html_sin_contacto = FICHA_REAL.replace(
        '<div class="col-lg-10 dContacto">',
        '<div class="col-lg-10 dContacto"></div><!--'
    )
    # Cerrar el comentario para eliminar el contenido
    html_sin_contacto = html_sin_contacto.replace(
        "LAS PERSONAS INTERESADAS DEBERÁN ENVIAR SU CURRÍCULUM VITAE A: ADMINISTRACON@COCINAECONOMICASANTANDER.ORG, INDICANDO EN EL ASUNTO EL NUMERO DE OFERTA 3633.",
        ""
    )

    oferta = _extraer_campos(html_sin_contacto)

    assert oferta.contacto == ""
    # El resto de campos se conservan
    assert oferta.numero_oferta == "062026003633"
    assert oferta.municipio == "SANTANDER"
    assert oferta.provincia == "CANTABRIA"


def test_ficha_con_inputs_vacios():
    """Variante con inputs vacíos → campos vacíos sin inventar."""
    # Crear variante con inputs vacíos
    html_inputs_vacios = FICHA_REAL
    html_inputs_vacios = html_inputs_vacios.replace(
        'value="SANTANDER"', 'value=""'
    )
    html_inputs_vacios = html_inputs_vacios.replace(
        'value="CANTABRIA"', 'value=""'
    )

    oferta = _extraer_campos(html_inputs_vacios)

    assert oferta.municipio == ""
    assert oferta.provincia == ""
    # Otros campos no afectados
    assert oferta.numero_oferta == "062026003633"


# --- Tests de parsear_ficha con reintentos ---


def test_parsear_ficha_exito_primer_intento(limitador_rapido):
    """Éxito en el primer intento, no se conserva el HTML."""
    cliente = ClienteMock([
        (200, FICHA_REAL, None),
    ])

    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador_rapido
    )

    assert resultado.oferta is not None
    assert resultado.oferta.numero_oferta == "062026003633"
    assert resultado.html == ""  # No se conserva el HTML en éxito
    assert resultado.error == ""
    assert len(cliente.intentos) == 1


def test_parsear_ficha_falla_primero_exito_segundo(limitador_con_delay):
    """Cliente que falla en la 1ª y responde en la 2ª → éxito con dos peticiones separadas ≥10 s."""
    limitador, reloj, dormir = limitador_con_delay

    cliente = ClienteMock([
        (500, "", RuntimeError("HTTP 500")),
        (200, FICHA_REAL, None),
    ])

    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador
    )

    assert resultado.oferta is not None
    assert resultado.oferta.numero_oferta == "062026003633"
    assert resultado.html == ""
    assert resultado.error == ""
    assert len(cliente.intentos) == 2
    # Verificar que se llamó a dormir al menos una vez (entre los intentos)
    assert len(dormir.tiempos_dormidos) >= 1


def test_parsear_ficha_falla_siempre(limitador_rapido):
    """Cliente que falla siempre → exactamente 2 peticiones y error por oferta persistente."""
    cliente = ClienteMock([
        (500, "", RuntimeError("HTTP 500")),
        (500, "", RuntimeError("HTTP 500")),
    ])

    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador_rapido
    )

    assert resultado.oferta is None
    assert resultado.error != ""
    assert "062026003633" in resultado.error
    assert len(cliente.intentos) == 2  # Exactamente 2 intentos


def test_parsear_ficha_no_conserva_html_en_exito(limitador_rapido):
    """En éxito no devuelve el HTML (REQ-010)."""
    cliente = ClienteMock([
        (200, FICHA_REAL, None),
    ])

    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador_rapido
    )

    assert resultado.oferta is not None
    assert resultado.html == ""  # HTML vacío en éxito


def test_parsear_ficha_conserva_html_en_error(limitador_rapido):
    """En error conserva el HTML para diagnóstico."""
    html_parcial = "<html><body>Error</body></html>"
    cliente = ClienteMock([
        (500, html_parcial, None),
        (500, html_parcial, None),
    ])

    resultado = parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador_rapido
    )

    assert resultado.oferta is None
    assert resultado.html == html_parcial  # Se conserva el HTML en error


def test_parsear_ficha_todas_peticiones_pasan_por_limitador(limitador_rapido):
    """Todas las peticiones pasan por el limitador."""
    # Mock del limitador para verificar que se llama a esperar()
    class LimitadorMock:
        def __init__(self):
            self.llamadas_esperar = 0
            self.user_agent = "test-agent"

        def esperar(self):
            self.llamadas_esperar += 1

    limitador_mock = LimitadorMock()
    cliente = ClienteMock([
        (200, FICHA_REAL, None),
    ])

    parsear_ficha(
        cliente=cliente,
        url_base="https://example.com/oferta",
        codigo="062026003633",
        limitador=limitador_mock
    )

    assert limitador_mock.llamadas_esperar == 1


# --- Tests de funciones auxiliares ---


def test_extraer_input_presente():
    """_extraer_input devuelve el valor cuando el input existe."""
    arbol = LexborHTMLParser(FICHA_REAL)
    valor = _extraer_input(arbol, "_numeroOferta")
    assert valor == "062026003633"


def test_extraer_input_ausente():
    """_extraer_input devuelve cadena vacía cuando el input no existe."""
    arbol = LexborHTMLParser(FICHA_REAL)
    valor = _extraer_input(arbol, "_campoInexistente")
    assert valor == ""


def test_extraer_bloque_presente():
    """_extraer_bloque devuelve el texto cuando el bloque existe."""
    arbol = LexborHTMLParser(FICHA_REAL)
    texto = _extraer_bloque(arbol, "dAdicionales")
    assert "INSTITUCIÓN SOCIAL" in texto


def test_extraer_bloque_ausente():
    """_extraer_bloque devuelve cadena vacía cuando el bloque no existe."""
    arbol = LexborHTMLParser(FICHA_REAL)
    texto = _extraer_bloque(arbol, "claseInexistente")
    assert texto == ""


def test_normalizar_espacios():
    """_normalizar_espacios colapsa múltiples espacios y saltos de línea."""
    texto_original = "Texto   con   múltiples    espacios\n\ny saltos\tde línea"
    resultado = _normalizar_espacios(texto_original)
    assert resultado == "Texto con múltiples espacios y saltos de línea"


def test_normalizar_espacios_vacio():
    """_normalizar_espacios maneja cadenas vacías."""
    assert _normalizar_espacios("") == ""
    assert _normalizar_espacios("   ") == ""
