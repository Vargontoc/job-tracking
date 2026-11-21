"""Pruebas unitarias del planificador diario."""

import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from source.api.buscador.models import ConfigBuscador
from source.api.buscador.scheduler import Scheduler


class RelojControlado:
    """Reloj controlable para tests."""

    def __init__(self, ahora: datetime | None = None) -> None:
        self._ahora = ahora or datetime(2026, 11, 18, 0, 59, 0)
        self._bloqueado = False

    def now(self) -> datetime:
        return self._ahora

    def sleep(self, segundos: float) -> None:
        # Simular el paso del tiempo
        self._ahora += timedelta(seconds=segundos)

    def avanzar(self, segundos: float) -> None:
        """Avanza el tiempo manualmente."""
        self._ahora += timedelta(seconds=segundos)


def crear_config(hora: int = 1) -> ConfigBuscador:
    """Crea una configuración de prueba."""
    return ConfigBuscador(hora_pasada=hora)


def crear_coordinador_mock() -> MagicMock:
    """Crea un coordinador mock."""
    mock = MagicMock()
    mock.pasada_en_curso = False
    mock.ejecutar_pasada.return_value = None
    return mock


def test_scheduler_ejecuta_a_hora_configurada():
    """El scheduler ejecuta una pasada al llegar la hora configurada."""
    reloj = RelojControlado(datetime(2026, 11, 18, 0, 59, 59))
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # Ejecutar en un hilo para no bloquear
    def ejecutar():
        scheduler._ejecutar_pasada_si_posible()

    hilo = threading.Thread(target=ejecutar)
    hilo.start()
    hilo.join(timeout=1.0)

    # Verificar que se llamó a ejecutar_pasada
    coordinador.ejecutar_pasada.assert_called_once()


def test_scheduler_omite_si_pasada_en_curso():
    """El scheduler omite la ejecución si hay una pasada en curso."""
    reloj = RelojControlado(datetime(2026, 11, 18, 1, 0, 0))
    coordinador = crear_coordinador_mock()
    coordinador.pasada_en_curso = True  # Simular pasada en curso
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # Ejecutar directamente
    scheduler._ejecutar_pasada_si_posible()

    # Verificar que NO se llamó a ejecutar_pasada
    coordinador.ejecutar_pasada.assert_not_called()


def test_scheduler_calcula_siguiente_ejecucion():
    """El scheduler calcula correctamente la siguiente ejecución."""
    reloj = RelojControlado(datetime(2026, 11, 18, 0, 30, 0))
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # Antes de la hora: siguiente ejecución hoy a las 01:00
    siguiente = scheduler._calcular_siguiente_ejecucion(reloj.now())
    assert siguiente == datetime(2026, 11, 18, 1, 0, 0)

    # Después de la hora: siguiente ejecución mañana a las 01:00
    reloj.avanzar(7200)  # Avanzar 2 horas (ahora son las 02:30)
    siguiente = scheduler._calcular_siguiente_ejecucion(reloj.now())
    assert siguiente == datetime(2026, 11, 19, 1, 0, 0)


def test_scheduler_detiene_gracefully():
    """El scheduler se detiene gracefulmente."""
    reloj = RelojControlado(datetime(2026, 11, 18, 0, 59, 0))
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # Iniciar scheduler
    scheduler.iniciar()
    assert scheduler._hilo is not None
    assert scheduler._hilo.is_alive()

    # Detener scheduler
    scheduler.detener()

    # Verificar que el hilo se detuvo
    assert not scheduler._hilo.is_alive()


def test_scheduler_maneja_errores_del_coordinador():
    """El scheduler maneja errores del coordinador sin detenerse."""
    reloj = RelojControlado(datetime(2026, 11, 18, 1, 0, 0))
    coordinador = crear_coordinador_mock()
    coordinador.ejecutar_pasada.side_effect = Exception("Error de prueba")
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # Ejecutar pasada (debería manejar el error sin lanzar excepción)
    scheduler._ejecutar_pasada_si_posible()

    # Verificar que se intentó ejecutar
    coordinador.ejecutar_pasada.assert_called_once()


def test_scheduler_no_ejecuta_antes_de_hora():
    """El scheduler no ejecuta antes de la hora configurada."""
    reloj = RelojControlado(datetime(2026, 11, 18, 0, 30, 0))
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # No debería ejecutar todavía
    # (en la implementación real, _esperar_hora_configurada bloquea)
    siguiente = scheduler._calcular_siguiente_ejecucion(reloj.now())
    assert siguiente > reloj.now()


def test_scheduler_ejecuta_hora_23():
    """El scheduler ejecuta correctamente a las 23:00."""
    reloj = RelojControlado(datetime(2026, 11, 18, 23, 0, 0))
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=23)

    scheduler = Scheduler(coordinador, config, reloj)

    scheduler._ejecutar_pasada_si_posible()

    coordinador.ejecutar_pasada.assert_called_once()


def test_scheduler_iniciar_dos_veces():
    """Iniciar el scheduler dos veces no crea múltiples hilos."""
    reloj = RelojControlado()
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    scheduler.iniciar()
    primer_hilo = scheduler._hilo

    scheduler.iniciar()  # Segunda vez

    # Debería ser el mismo hilo
    assert scheduler._hilo is primer_hilo

    scheduler.detener()


def test_scheduler_detiene_sin_iniciar():
    """Detener el scheduler sin iniciarlo no falla."""
    reloj = RelojControlado()
    coordinador = crear_coordinador_mock()
    config = crear_config(hora=1)

    scheduler = Scheduler(coordinador, config, reloj)

    # No debería fallar
    scheduler.detener()

    assert scheduler._hilo is None
