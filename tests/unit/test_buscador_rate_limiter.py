"""Pruebas del limitador global de peticiones."""

from source.api.buscador.rate_limiter import LimitadorPeticiones


class RelojControlado:
    """Reloj falso para controlar el tiempo en tests."""
    
    def __init__(self, tiempo_inicial: float = 0.0) -> None:
        self._tiempo = tiempo_inicial
    
    def __call__(self) -> float:
        return self._tiempo
    
    def avanzar(self, segundos: float) -> None:
        self._tiempo += segundos


class DormirControlado:
    """Función de sleep falsa para controlar el tiempo en tests."""
    
    def __init__(self, reloj: RelojControlado) -> None:
        self.reloj = reloj
        self.tiempos_espera = []
    
    def __call__(self, segundos: float) -> None:
        self.tiempos_espera.append(segundos)
        self.reloj.avanzar(segundos)


def test_primera_peticion_no_espera() -> None:
    """La primera petición no debe esperar ningún intervalo."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    limitador.esperar()
    
    # La primera llamada no debe haber esperado
    assert len(dormir.tiempos_espera) == 0


def test_dos_peticiones_consecutivas_separadas_por_10s() -> None:
    """Dos peticiones consecutivas deben estar separadas por al menos 10s."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Primera petición
    limitador.esperar()
    
    # Avanzar solo 5 segundos (insuficiente)
    reloj.avanzar(5.0)
    
    # Segunda petición
    limitador.esperar()
    
    # Debió esperar 5 segundos para completar los 10s
    assert len(dormir.tiempos_espera) == 1
    assert abs(dormir.tiempos_espera[0] - 5.0) < 0.01


def test_tres_peticiones_consecutivas() -> None:
    """Tres peticiones deben respetar el intervalo entre cada par."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Primera petición (no espera)
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 0
    
    # Segunda petición inmediatamente después
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 1
    assert abs(dormir.tiempos_espera[0] - 10.0) < 0.01
    
    # Tercera petición inmediatamente después
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 2
    assert abs(dormir.tiempos_espera[1] - 10.0) < 0.01


def test_limitador_compartido_entre_listado_y_ficha() -> None:
    """El limitador es compartido: tras listado, ficha espera el intervalo."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Petición del listado
    limitador.esperar()
    
    # Avanzar 3 segundos
    reloj.avanzar(3.0)
    
    # Petición de ficha (debería esperar 7s)
    limitador.esperar()
    
    assert len(dormir.tiempos_espera) == 1
    assert abs(dormir.tiempos_espera[0] - 7.0) < 0.01


def test_user_agent_se_preserva() -> None:
    """El User-Agent configurado se preserva en el limitador."""
    user_agent = "JobEmcanTracking/1.0 (+contacto@example.com)"
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        user_agent=user_agent
    )
    
    assert limitador.user_agent == user_agent


def test_delay_configurable() -> None:
    """El delay es configurable."""
    limitador = LimitadorPeticiones(delay_segundos=15.0)
    
    assert limitador.delay_segundos == 15.0


def test_peticion_despues_de_intervalo_completo_no_espera() -> None:
    """Si ha pasado el intervalo completo, no hay espera adicional."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Primera petición
    limitador.esperar()
    
    # Avanzar 15 segundos (más que el intervalo)
    reloj.avanzar(15.0)
    
    # Segunda petición (no debería esperar)
    limitador.esperar()
    
    assert len(dormir.tiempos_espera) == 0


def test_limitador_con_delay_menor() -> None:
    """El limitador funciona con delays menores a 10 segundos."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=5.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Primera petición
    limitador.esperar()
    
    # Avanzar 2 segundos
    reloj.avanzar(2.0)
    
    # Segunda petición (debería esperar 3s)
    limitador.esperar()
    
    assert len(dormir.tiempos_espera) == 1
    assert abs(dormir.tiempos_espera[0] - 3.0) < 0.01


def test_multiples_peticiones_con_intervalos_parciales() -> None:
    """Múltiples peticiones con intervalos parciales entre ellas."""
    reloj = RelojControlado(0.0)
    dormir = DormirControlado(reloj)
    limitador = LimitadorPeticiones(
        delay_segundos=10.0,
        reloj=reloj,
        dormir=dormir
    )
    
    # Primera petición (t=0)
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 0
    
    # Avanzar 4s, segunda petición (espera 6s, t=10)
    reloj.avanzar(4.0)
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 1
    assert abs(dormir.tiempos_espera[0] - 6.0) < 0.01
    
    # Avanzar 7s, tercera petición (espera 3s, t=20)
    reloj.avanzar(7.0)
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 2
    assert abs(dormir.tiempos_espera[1] - 3.0) < 0.01
    
    # Avanzar 12s, cuarta petición (no espera, t=32)
    reloj.avanzar(12.0)
    limitador.esperar()
    assert len(dormir.tiempos_espera) == 2  # No aumentó
