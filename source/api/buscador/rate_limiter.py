"""Limitador global de peticiones al portal de Emplea Cantabria."""

import logging
import time
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class SleepFn(Protocol):
    """Protocolo para función de sleep."""
    def __call__(self, segundos: float) -> None:
        ...


class LimitadorPeticiones:
    """Regula el intervalo mínimo entre peticiones HTTP al portal.
    
    Garantiza que entre dos peticiones consecutivas transcurra al menos
    el intervalo configurado. La primera petición no espera.
    """
    
    def __init__(
        self,
        delay_segundos: float = 10.0,
        user_agent: str = "",
        reloj: Callable[[], float] = time.time,
        dormir: SleepFn = time.sleep,
    ) -> None:
        """Inicializa el limitador.
        
        Args:
            delay_segundos: Intervalo mínimo en segundos entre peticiones.
            user_agent: Cabecera User-Agent para identificar el proyecto.
            reloj: Función que devuelve el tiempo actual (inyectable para tests).
            dormir: Función para dormir (inyectable para tests).
        """
        self._delay = delay_segundos
        self._user_agent = user_agent
        self._reloj = reloj
        self._dormir = dormir
        self._ultima_peticion: float | None = None
    
    def esperar(self) -> None:
        """Espera si es necesario antes de hacer una petición.
        
        Si es la primera petición, no espera. Si ha habido peticiones anteriores,
        calcula el tiempo transcurrido y duerme si no ha pasado el intervalo mínimo.
        """
        ahora = self._reloj()
        
        if self._ultima_peticion is not None:
            transcurrido = ahora - self._ultima_peticion
            if transcurrido < self._delay:
                tiempo_espera = self._delay - transcurrido
                logger.debug(f"Limitador: esperando {tiempo_espera:.2f}s antes de petición")
                self._dormir(tiempo_espera)
            else:
                logger.debug(f"Limitador: sin espera necesaria (transcurrido {transcurrido:.2f}s)")
        else:
            logger.debug("Limitador: primera petición, sin espera")
        
        self._ultima_peticion = self._reloj()
        logger.debug("Limitador: petición liberada")
    
    @property
    def user_agent(self) -> str:
        """Devuelve el User-Agent configurado."""
        return self._user_agent
    
    @property
    def delay_segundos(self) -> float:
        """Devuelve el intervalo mínimo configurado."""
        return self._delay
