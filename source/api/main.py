"""Aplicación FastAPI para el parseo de ofertas de difusión."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

# Configurar logging para que los mensajes info/debug se muestren en consola
# con formato legible. Sin esto, solo WARNING+ se imprimen (handler por defecto).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

import httpx
from fastapi import FastAPI, HTTPException

from source.api.assembler import ensamblar_respuesta
from source.api.buscador.config import cargar_configuracion, ErrorConfiguracion as ErrorConfiguracionBuscador
from source.api.buscador.coordinator import CoordinadorPasada
from source.api.buscador.rate_limiter import LimitadorPeticiones
from source.api.buscador.routes import router as buscador_router
from source.api.buscador.scheduler import Scheduler
from source.api.config import cargar_comunidades, ErrorConfiguracion as ErrorConfiguracionPDF
from source.api.downloader import ErrorDescarga, descargar_pdf
from source.api.models import ResultadoPorComunidad
from source.api.parser import extraer_ofertas_desde_pdf

logger = logging.getLogger(__name__)


# Estado global de la aplicación (compartido entre endpoints)
app_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona el ciclo de vida de la aplicación.
    
    Al arrancar:
    - Lee configuración del buscador desde config/buscador.yaml
    - Crea/lee data/seen_codes.json si no existe
    - Instancia y arranca scheduler con hora configurada
    
    Al apagar:
    - Cancela scheduler gracefulmente
    - Limpia recursos
    """
    # === STARTUP ===
    try:
        # 1. Cargar configuración del buscador
        config = cargar_configuracion()
        logger.info(f"Configuración del buscador cargada: hora={config.hora_pasada:02d}:00")
        
        # 2. Asegurar que existe seen_codes.json
        seen_codes_path = Path(config.ruta_seen_codes) if config.ruta_seen_codes else Path("data/seen_codes.json")
        if not seen_codes_path.exists():
            seen_codes_path.parent.mkdir(parents=True, exist_ok=True)
            seen_codes_path.write_text("[]", encoding="utf-8")
            logger.info(f"Creado fichero vacío de códigos vistos: {seen_codes_path}")
        
        # 3. Crear cliente HTTP, limitador y coordinador real
        cliente_http = httpx.Client(
            headers={"User-Agent": config.user_agent},
            follow_redirects=True,
            timeout=config.delay_peticiones + 20.0,
        )
        limitador = LimitadorPeticiones(
            delay_segundos=config.delay_peticiones,
            user_agent=config.user_agent,
        )
        coordinador = CoordinadorPasada(
            config=config,
            cliente=cliente_http,
            limitador=limitador,
            ruta_seen_codes=Path(config.ruta_seen_codes) if config.ruta_seen_codes else Path("data/seen_codes.json"),
            ruta_failed_htmls=Path(config.ruta_failed_htmls) if config.ruta_failed_htmls else Path("data/failed_htmls"),
            dias_purga=config.dias_purga,
        )

        app_state["config"] = config
        app_state["coordinador"] = coordinador
        app_state["cliente_http"] = cliente_http
        
        # 4. Instanciar y arrancar scheduler
        scheduler = Scheduler(
            coordinador=coordinador,
            config=config,
        )
        scheduler.iniciar()
        app_state["scheduler"] = scheduler
        
        logger.info("API arrancada correctamente con coordinador real y scheduler iniciado")
        
    except ErrorConfiguracionBuscador as e:
        logger.error(f"Error al cargar configuración del buscador: {e}")
        logger.info("Continuando con configuración por defecto")
        # Usar configuración por defecto
        from source.api.buscador.models import ConfigBuscador
        app_state["config"] = ConfigBuscador()
        app_state["coordinador"] = None
        app_state["scheduler"] = None
    except Exception as e:
        logger.error(f"Error inesperado al arrancar: {e}")
        # No bloquear el arranque de la API
        app_state["config"] = None
        app_state["coordinador"] = None
        app_state["scheduler"] = None
    
    yield
    
    # === SHUTDOWN ===
    scheduler = app_state.get("scheduler")
    if scheduler is not None:
        try:
            logger.info("Deteniendo scheduler...")
            scheduler.detener()
            logger.info("Scheduler detenido correctamente")
        except Exception as e:
            logger.error(f"Error al detener scheduler: {e}")
    
    cliente_http = app_state.get("cliente_http")
    if cliente_http is not None:
        try:
            cliente_http.close()
            logger.info("Cliente HTTP cerrado correctamente")
        except Exception as e:
            logger.error(f"Error al cerrar cliente HTTP: {e}")
    
    # Limpiar estado
    app_state.clear()
    logger.info("API apagada correctamente")


app = FastAPI(title="Job Emcan Tracking API", lifespan=lifespan)

# Registrar rutas del buscador
app.include_router(buscador_router)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    """Healthcheck endpoint para monitoring externo."""
    return {"status": "healthy"}


@app.get("/parse")
def parsear_ofertas() -> dict[str, object]:
    """Procesa los PDFs de todas las comunidades configuradas."""
    try:
        comunidades = cargar_comunidades()
    except ErrorConfiguracionPDF as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    resultados = []
    for comunidad in comunidades:
        descarga = descargar_pdf(comunidad.url_pdf)
        if isinstance(descarga, ErrorDescarga):
            resultados.append(
                ResultadoPorComunidad(
                    comunidad=comunidad.identificador,
                    estado="error",
                    mensaje_error=descarga.mensaje,
                )
            )
            continue

        resultados.append(
            ResultadoPorComunidad(
                comunidad=comunidad.identificador,
                estado="ok",
                ofertas=extraer_ofertas_desde_pdf(
                    descarga,
                    comunidad=comunidad.identificador,
                ),
            )
        )

    return ensamblar_respuesta(resultados)
