"""Pruebas de integración: frecuencia de peticiones y solapamiento (TASK-022).

Verifican con reloj controlado que:
- El rate-limiting global respeta ≥10 s entre peticiones consecutivas.
- La exclusión mutua del coordinador impide pasadas concurrentes.
- El scheduler no ejecuta pasadas duplicadas.
- Los reintentos también respetan el rate-limiting.
- Una pasada completa se ejecuta sin errores con portal mock.
"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest

from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.models import ConfigBuscador, ResultadoPasada
from source.api.buscador.rate_limiter import LimitadorPeticiones
from source.api.buscador.scheduler import Scheduler


# ---------------------------------------------------------------------------
# Utilidades: reloj controlado
# ---------------------------------------------------------------------------


class RelojControlado:
    """Reloj inyectable que permite avanzar el tiempo de forma controlada.

    Registra cada llamada a ``__call__`` (reloj del limitador) y cada llamada
    a ``dormir`` para poder verificar los intervalos a posteriori.
    """

    def __init__(self, tiempo_inicial: float = 0.0) -> None:
        self._tiempo = tiempo_inicial
        self.marcas: list[float] = []
        self.suennos: list[float] = []

    def __call__(self) -> float:
        """Devuelve el tiempo actual (inyectado en LimitadorPeticiones)."""
        self.marcas.append(self._tiempo)
        return self._tiempo

    def dormir(self, segundos: float) -> None:
        """Simula time.sleep avanzando el reloj la cantidad indicada."""
        self.suennos.append(segundos)
        self._tiempo += segundos

    def avanzar(self, segundos: float) -> None:
        """Avanza el reloj sin registrar sueño (para simular tiempo externo)."""
        self._tiempo += segundos

    @property
    def tiempo_actual(self) -> float:
        return self._tiempo


class RelojControladoScheduler:
    """Reloj controlado compatible con RelojProtocol del scheduler."""

    def __init__(self, inicio: datetime) -> None:
        self._ahora = inicio
        self._slept: list[float] = []

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        self._slept.append(segundos)
        self._ahora += timedelta(seconds=segundos)

    def avanzar(self, **kwargs) -> None:
        self._ahora += timedelta(**kwargs)


# ---------------------------------------------------------------------------
# Utilidades: cliente HTTP mock
# ---------------------------------------------------------------------------


class RespuestaMock:
    """Respuesta HTTP simulada."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ClientePortalMock:
    """Cliente HTTP mock que simula el portal de Emplea Cantabria.

    Devuelve HTML predefinidos para las URLs del listado y de fichas.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir
        self.llamadas: list[str] = []
        self._fichas_fallantes: set[str] = set()
        self._fichas_fallantes_siempre: set[str] = set()
        self._intentos_ficha: dict[str, int] = {}

        # Cargar fixtures HTML
        self._listado_pagina_1 = (
            fixtures_dir / "listado_pagina_1.html"
        ).read_text(encoding="utf-8")
        self._listado_pagina_2 = (
            fixtures_dir / "listado_pagina_2.html"
        ).read_text(encoding="utf-8")
        self._listado_vacio = (
            fixtures_dir / "listado_vacio.html"
        ).read_text(encoding="utf-8")
        self._ficha_062026003633 = (
            fixtures_dir / "ficha_062026003633.html"
        ).read_text(encoding="utf-8")

    def get(self, url: str, *, timeout: float = 30.0) -> RespuestaMock:
        self.llamadas.append(url)

        # Listado
        if "EmpleacanBuscadorOfertasPortlet_cur=1" in url:
            return RespuestaMock(self._listado_pagina_1)
        if "EmpleacanBuscadorOfertasPortlet_cur=2" in url:
            return RespuestaMock(self._listado_pagina_2)

        # Fichas
        for codigo in self._fichas_fallantes_siempre:
            if f"/oferta/{codigo}" in url:
                self._intentos_ficha[codigo] = (
                    self._intentos_ficha.get(codigo, 0) + 1
                )
                # Devolver HTML sin campos válidos
                return RespuestaMock(
                    "<html><body>Sin campos</body></html>", status_code=200
                )

        for codigo in self._fichas_fallantes:
            if f"/oferta/{codigo}" in url:
                self._intentos_ficha[codigo] = (
                    self._intentos_ficha.get(codigo, 0) + 1
                )
                # Fallar solo la primera vez
                if self._intentos_ficha[codigo] <= 1:
                    raise RuntimeError("Error temporal de conexión")
                # Segunda vez: devolver ficha válida (la de 062026003633)
                return RespuestaMock(self._ficha_062026003633)

        # Ficha por defecto: usar la del fixture
        if "/oferta/" in url:
            return RespuestaMock(self._ficha_062026003633)

        raise RuntimeError(f"URL no esperada: {url}")

    def marcar_ficha_fallida_una_vez(self, codigo: str) -> None:
        """La ficha falla en el primer intento y tiene éxito en el segundo."""
        self._fichas_fallantes.add(codigo)

    def marcar_ficha_fallida_siempre(self, codigo: str) -> None:
        """La ficha falla en todos los intentos."""
        self._fichas_fallantes_siempre.add(codigo)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    """Directorio de fixtures HTML del buscador."""
    return Path(__file__).parent.parent / "fixtures" / "buscador"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Directorio temporal de datos (seen_codes.json y failed_htmls)."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def config_test(data_dir: Path) -> ConfigBuscador:
    """Configuración de prueba con rutas temporales."""
    return ConfigBuscador(
        hora_pasada=1,
        url_listado="https://empleacantabria.es/ofertas-cantabria",
        url_ficha="https://empleacantabria.es/ofertas-cantabria/-/oferta",
        user_agent="Test/1.0 (test@example.com)",
        tamano_pagina=75,
        delay_peticiones=10,
        ruta_seen_codes=str(data_dir / "seen_codes.json"),
        ruta_failed_htmls=str(data_dir / "failed_htmls"),
        dias_purga=7,
    )


def _crear_coordinador(
    config: ConfigBuscador,
    cliente: ClientePortalMock,
    limitador: LimitadorPeticiones,
) -> CoordinadorPasada:
    """Crea un CoordinadorPasada con los componentes dados."""
    return CoordinadorPasada(
        config=config,
        cliente=cliente,
        limitador=limitador,
        ruta_seen_codes=Path(config.ruta_seen_codes),
        ruta_failed_htmls=Path(config.ruta_failed_htmls),
        dias_purga=config.dias_purga,
    )


# ---------------------------------------------------------------------------
# Test 1: rate-limiting en una pasada completa
# ---------------------------------------------------------------------------


def test_rate_limiting_en_pasada_completa(
    config_test: ConfigBuscador,
    fixtures_dir: Path,
    data_dir: Path,
) -> None:
    """La secuencia completa de peticiones respeta ≥10 s entre pares consecutivos.

    Simula una pasada con listado de 2 páginas y 3 fichas nuevas.
    Verifica:
    - La primera petición no espera.
    - Todas las peticiones están separadas por ≥10 s (usando reloj controlado).
    """
    reloj = RelojControlado(tiempo_inicial=1000.0)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        user_agent=config_test.user_agent,
        reloj=reloj,
        dormir=reloj.dormir,
    )

    cliente = ClientePortalMock(fixtures_dir)
    coordinador = _crear_coordinador(config_test, cliente, limitador)

    # Ejecutar pasada completa
    resultado = coordinador.ejecutar_pasada()

    # El listado tiene 6 códigos (3 en página 1 y 3 en página 2)
    # Se piden 2 páginas de listado + fichas de los códigos nuevos
    assert len(cliente.llamadas) > 0, "Debe haber al menos una petición"

    # Verificar intervalos: cada sleep() debe ser de al menos ~10 s
    # (puede ser exactamente 10.0 o un poco más por redondeo)
    for sueno in reloj.suennos:
        assert sueno >= 9.99, (
            f"El intervalo de espera {sueno:.2f}s es menor que 10s"
        )

    # La primera petición no espera (no hay sleep antes de ella)
    # El limitador no llama a dormir() para la primera petición
    # Número de peticiones = 2 páginas listado + N fichas
    num_peticiones = len(cliente.llamadas)
    # La primera no espera, las restantes sí
    # Si hay N peticiones, hay N-1 sleeps (uno entre cada par)
    assert len(reloj.suennos) == num_peticiones - 1, (
        f"Se esperaban {num_peticiones - 1} sleeps "
        f"(1ª petición sin espera), pero hubo {len(reloj.suennos)}"
    )

    # Verificar que el resultado es coherente
    assert resultado.total_listado == 93
    assert resultado.error_global == ""


# ---------------------------------------------------------------------------
# Test 2: exclusión mutua del coordinador
# ---------------------------------------------------------------------------


def test_exclusion_mutua_coordinador(
    config_test: ConfigBuscador,
    fixtures_dir: Path,
    data_dir: Path,
) -> None:
    """La segunda pasada se rechaza con "Ya hay una pasada en curso".

    Inicia una pasada en un hilo separado, intenta iniciar una segunda
    y verifica que se rechaza correctamente.
    """
    # Usar delay 0 para que la pasada no tarde eternamente
    limitador = LimitadorPeticiones(delay_segundos=0.0)
    cliente = ClientePortalMock(fixtures_dir)
    coordinador = _crear_coordinador(config_test, cliente, limitador)

    resultado_segunda: list[ResultadoPasada] = []
    evento_pasada_iniciada = threading.Event()
    evento_puede_terminar = threading.Event()

    class ClienteLento(ClientePortalMock):
        """Cliente que permite controlar cuándo termina la pasada."""

        def __init__(self, fixtures: Path) -> None:
            super().__init__(fixtures)
            self._ficha_contador = 0

        def get(self, url: str, *, timeout: float = 30.0) -> RespuestaMock:
            if "/oferta/" in url:
                self._ficha_contador += 1
                if self._ficha_contador == 1:
                    # Señalizar que la pasada ya está en curso
                    evento_pasada_iniciada.set()
                    # Esperar hasta que se pueda terminar
                    evento_puede_terminar.wait(timeout=10.0)
            return super().get(url, timeout=timeout)

    cliente_lento = ClienteLento(fixtures_dir)
    coordinador_lento = _crear_coordinador(config_test, cliente_lento, limitador)

    def ejecutar_primera() -> None:
        coordinador_lento.ejecutar_pasada()

    # Lanzar la primera pasada en un hilo
    hilo = threading.Thread(target=ejecutar_primera, daemon=True)
    hilo.start()

    try:
        # Esperar a que la primera pasada esté en curso
        assert evento_pasada_iniciada.wait(timeout=10.0), (
            "La primera pasada no se inició a tiempo"
        )
        assert coordinador_lento.pasada_en_curso, (
            "La primera pasada debería estar en curso"
        )

        # Intentar iniciar la segunda pasada
        resultado = coordinador_lento.ejecutar_pasada()
        resultado_segunda.append(resultado)

        # Verificar que la segunda se rechazó
        assert resultado.error_global == "Ya hay una pasada en curso", (
            f"Se esperaba 'Ya hay una pasada en curso', "
            f"se obtuvo: {resultado.error_global!r}"
        )
        assert len(resultado.ofertas_nuevas) == 0
    finally:
        # Permitir que la primera pasada termine
        evento_puede_terminar.set()
        hilo.join(timeout=15.0)

    # Verificar que la primera pasada terminó correctamente
    assert not coordinador_lento.pasada_en_curso, (
        "La primera pasada no liberó el flag de pasada en curso"
    )
    assert len(resultado_segunda) == 1


# ---------------------------------------------------------------------------
# Test 3: el scheduler no duplica pasadas
# ---------------------------------------------------------------------------


def test_scheduler_no_duplica_pasadas(
    config_test: ConfigBuscador,
    fixtures_dir: Path,
    data_dir: Path,
) -> None:
    """Solo se ejecuta una pasada aunque el scheduler intente disparar dos.

    Configura el scheduler con hora=1 y reloj controlado. Avanza el tiempo
    hasta la hora de ejecución. Mientras la pasada está en curso, el scheduler
    intenta disparar otra: se verifica que solo se ejecuta una.
    """
    limitador = LimitadorPeticiones(delay_segundos=0.0)
    cliente = ClientePortalMock(fixtures_dir)
    coordinador = _crear_coordinador(config_test, cliente, limitador)

    pasadas_ejecutadas: list[ResultadoPasada] = []
    lock_pasadas = threading.Lock()

    # Decorar el coordinador para contar pasadas
    ejecutar_pasada_original = coordinador.ejecutar_pasada

    def contar_pasada(historical_codes=None):
        resultado = ejecutar_pasada_original(historical_codes)
        with lock_pasadas:
            pasadas_ejecutadas.append(resultado)
        return resultado

    coordinador.ejecutar_pasada = contar_pasada  # type: ignore[assignment]

    # Reloj del scheduler: empezar a las 00:59:50
    hora_inicio = datetime(2026, 11, 19, 0, 59, 50)
    reloj_scheduler = RelojControladoScheduler(hora_inicio)

    scheduler = Scheduler(
        coordinador=coordinador,
        config=config_test,
        reloj=reloj_scheduler,
    )

    # Avanzar hasta 01:00:00 (la hora de ejecución)
    reloj_scheduler.avanzar(seconds=10)

    # Ejecutar el método interno directamente para simular el disparo
    scheduler._ejecutar_pasada_si_posible()

    # Verificar que se ejecutó exactamente una pasada
    assert len(pasadas_ejecutadas) == 1, (
        f"Se esperaba 1 pasada, se ejecutaron {len(pasadas_ejecutadas)}"
    )

    # Ahora marcar manualmente la pasada como en curso (simulando que
    # una pasada está en ejecución cuando el scheduler intenta disparar otra)
    coordinador._pasada_en_curso = True

    # Intentar disparar otra pasada desde el scheduler
    scheduler._ejecutar_pasada_si_posible()

    # Verificar que sigue habiendo solo 1 pasada
    assert len(pasadas_ejecutadas) == 1, (
        f"Con pasada en curso, el scheduler no debería ejecutar otra. "
        f"Se ejecutaron {len(pasadas_ejecutadas)}"
    )

    # Liberar el flag
    coordinador._pasada_en_curso = False


# ---------------------------------------------------------------------------
# Test 4: rate-limiting con reintentos
# ---------------------------------------------------------------------------


def test_rate_limiting_con_reintentos(
    config_test: ConfigBuscador,
    fixtures_dir: Path,
    data_dir: Path,
) -> None:
    """El reintento de una ficha también respeta el rate-limiting (≥10 s).

    Simula una ficha que falla en el primer intento y tiene éxito en el
    reintento. Verifica que ambos intentos pasan por el limitador y que
    el intervalo entre ellos es ≥10 s.
    """
    reloj = RelojControlado(tiempo_inicial=2000.0)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        user_agent=config_test.user_agent,
        reloj=reloj,
        dormir=reloj.dormir,
    )

    cliente = ClientePortalMock(fixtures_dir)
    # Marcar la ficha 062026003633 como fallida una vez (éxito en reintento)
    cliente.marcar_ficha_fallida_una_vez("062026003633")

    coordinador = _crear_coordinador(config_test, cliente, limitador)

    # Ejecutar pasada
    resultado = coordinador.ejecutar_pasada()

    # Verificar que hubo reintentos: la ficha 062026003633 se pidió 2 veces
    # (una fallida + una exitosa) además de las demás fichas
    intentos_3633 = cliente._intentos_ficha.get("062026003633", 0)
    assert intentos_3633 >= 2, (
        f"Se esperaban al menos 2 intentos para 062026003633, "
        f"hubo {intentos_3633}"
    )

    # Verificar que los intervalos de espera cumplen ≥10 s
    for sueno in reloj.suennos:
        assert sueno >= 9.99, (
            f"El intervalo de espera del reintento ({sueno:.2f}s) "
            f"es menor que 10s"
        )

    # La ficha 062026003633 debería haber sido procesada correctamente
    # (porque el reintento tuvo éxito)
    codigos_exitosos = [
        o.numero_oferta for o in resultado.ofertas_nuevas
    ]
    assert "062026003633" in codigos_exitosos, (
        "La ficha 062026003633 debería haber tenido éxito tras el reintento"
    )


# ---------------------------------------------------------------------------
# Test 5: pasada completa sin errores
# ---------------------------------------------------------------------------


def test_pasada_completa_sin_errores(
    config_test: ConfigBuscador,
    fixtures_dir: Path,
    data_dir: Path,
) -> None:
    """Una pasada completa con portal mock termina sin errores.

    Verifica:
    - seen_codes.json se actualiza correctamente con los códigos parseados.
    - No hay ficheros HTML fallidos (todos los parseos fueron exitosos).
    - El resultado tiene ofertas nuevas y no tiene error global.
    """
    limitador = LimitadorPeticiones(delay_segundos=0.0)
    cliente = ClientePortalMock(fixtures_dir)
    coordinador = _crear_coordinador(config_test, cliente, limitador)

    # Ejecutar pasada completa
    resultado = coordinador.ejecutar_pasada()

    # Verificar que no hay error global
    assert resultado.error_global == "", (
        f"Se esperaba sin error global, se obtuvo: {resultado.error_global!r}"
    )

    # Verificar que hay ofertas nuevas
    assert len(resultado.ofertas_nuevas) > 0, (
        "Se esperaban ofertas nuevas"
    )

    # Verificar que seen_codes.json se actualizó
    seen_codes_path = Path(config_test.ruta_seen_codes)
    assert seen_codes_path.exists(), (
        "seen_codes.json debería existir tras la pasada"
    )
    seen_codes = json.loads(seen_codes_path.read_text(encoding="utf-8"))
    assert len(seen_codes) > 0, (
        "seen_codes.json debería tener códigos tras la pasada"
    )

    # Los códigos en seen_codes.json coinciden con las ofertas parseadas
    codigos_ofertas = {o.numero_oferta for o in resultado.ofertas_nuevas}
    codigos_vistos = set(seen_codes)
    assert codigos_ofertas.issubset(codigos_vistos), (
        "Los códigos de ofertas nuevas deberían estar en seen_codes.json"
    )

    # Verificar que no hay ficheros HTML fallidos
    failed_htmls_dir = Path(config_test.ruta_failed_htmls)
    if failed_htmls_dir.exists():
        html_files = list(failed_htmls_dir.glob("*.html"))
        assert len(html_files) == 0, (
            f"No debería haber HTML fallidos, pero hay {len(html_files)}: "
            f"{[f.name for f in html_files]}"
        )

    # Verificar que no hay errores por oferta
    assert len(resultado.errores_por_oferta) == 0, (
        f"Se esperaban 0 errores por oferta, "
        f"hay {len(resultado.errores_por_oferta)}"
    )

    # Verificar el total del listado
    assert resultado.total_listado == 93

    # Verificar la comunidad
    assert resultado.comunidad == "Cantabria"
