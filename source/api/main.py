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

# Persistencia (TASK-013)
from source.api.persistencia.config import (
    cargar_configuracion as cargar_configuracion_persistencia,
    ErrorConfiguracion as ErrorConfiguracionPersistencia,
)
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar, ErrorMigracion
from source.api.persistencia.importer import importar_codigos_vistos
from source.api.persistencia.repository import RepositorioOfertas
from source.api.persistencia.client import ClienteBuscador
from source.api.persistencia.ingestion import TareaIngesta
from source.api.persistencia.purge import TareaPurga
from source.api.persistencia.routes import router as persistencia_router

# Histórico (TASK-016)
from source.api.historico.config import (
    cargar_configuracion as cargar_configuracion_historico,
    ErrorConfiguracion as ErrorConfiguracionHistorico,
)
from source.api.historico.connection import (
    abrir_conexion as abrir_conexion_historico,
)
from source.api.historico.migrations import (
    migrar as migrar_historico,
    ErrorMigracion as ErrorMigracionHistorico,
)
from source.api.historico.presencia_repository import RepositorioPresencia
from source.api.historico.abstenciones_repository import RepositorioAbstenciones
from source.api.historico.ejecucion_repository import RepositorioEjecucion
from source.api.historico.buscador_client import ClienteEstadoBuscador
from source.api.historico.persistencia_client import ClientePersistencia
from source.api.historico.read_adapter import AdaptadorLecturaHistorica
from source.api.historico.pdf_adapter import AdaptadorListadoPDF
from source.api.historico.task import TareaHistorico
from source.api.historico.routes import router as historico_router

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
    # Parte 1: Buscador (existente)
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
        
    except ErrorConfiguracionBuscador as e:
        logger.error(f"Error al cargar configuración del buscador: {e}")
        logger.info("Continuando con configuración por defecto")
        # Usar configuración por defecto
        from source.api.buscador.models import ConfigBuscador
        config = ConfigBuscador()
        app_state["config"] = config
        app_state["coordinador"] = None
        app_state["scheduler"] = None
    except Exception as e:
        logger.error(f"Error inesperado al arrancar el buscador: {e}")
        from source.api.buscador.models import ConfigBuscador
        config = ConfigBuscador()
        app_state["config"] = None
        app_state["coordinador"] = None
        app_state["scheduler"] = None

    # Parte 2: Persistencia (TASK-013) — independiente del buscador
    try:
        # 5.1 Cargar configuración de persistencia
        config_persistencia = cargar_configuracion_persistencia()
        logger.info(
            "Configuración de persistencia cargada: ruta_bd=%s, cadencia=%ds",
            config_persistencia.ruta_bd,
            config_persistencia.cadencia_segundos,
        )

        # 5.2 Abrir conexión SQLite con WAL
        conexion_persistencia = abrir_conexion(config_persistencia.ruta_bd)
        logger.info(
            "Conexión SQLite abierta: %s (WAL activado)",
            config_persistencia.ruta_bd,
        )

        # 5.3 Aplicar migraciones
        version_esquema = migrar(conexion_persistencia)
        logger.info("Migraciones aplicadas: versión %d", version_esquema)

        # 5.4 Importar códigos vistos (no bloquea si falla - ALT-003)
        ruta_seen_codes_import = (
            Path(config.ruta_seen_codes)
            if getattr(config, "ruta_seen_codes", None)
            else Path("data/seen_codes.json")
        )
        try:
            resultado_importacion = importar_codigos_vistos(
                conexion_persistencia, ruta_seen_codes_import
            )
            logger.info(
                "Importación de códigos vistos: %d importados, %d existentes",
                resultado_importacion.importados,
                resultado_importacion.existentes,
            )
        except Exception as exc:
            logger.warning(
                "Error importando códigos vistos desde %s: %s. Continuando.",
                ruta_seen_codes_import,
                exc,
            )

        # 5.5 Crear repositorio y cliente buscador
        repositorio = RepositorioOfertas(conexion_persistencia)
        cliente_buscador = ClienteBuscador(
            url_base=config_persistencia.url_base_buscador
        )

        # 5.6 Arrancar TareaIngesta
        tarea_ingesta = TareaIngesta(
            cliente_buscador=cliente_buscador,
            repositorio=repositorio,
            conexion=conexion_persistencia,
            cadencia_segundos=config_persistencia.cadencia_segundos,
        )
        tarea_ingesta.iniciar()
        logger.info("Tarea de ingesta arrancada")

        # 5.7 Arrancar TareaPurga
        tarea_purga = TareaPurga(
            repositorio=repositorio,
            conexion=conexion_persistencia,
            dias_retencion=config_persistencia.dias_retencion,
            frecuencia_segundos=config_persistencia.frecuencia_segundos,
        )
        tarea_purga.iniciar()
        logger.info("Tarea de purga arrancada")

        # 5.8 Guardar referencias en app_state
        app_state["config_persistencia"] = config_persistencia
        app_state["conexion_persistencia"] = conexion_persistencia
        app_state["repositorio"] = repositorio
        app_state["cliente_buscador"] = cliente_buscador
        app_state["tarea_ingesta"] = tarea_ingesta
        app_state["tarea_purga"] = tarea_purga

        logger.info("API arrancada correctamente con coordinador real y scheduler iniciado")

    except (ErrorConfiguracionPersistencia, ErrorMigracion) as exc:
        logger.error("Error crítico en persistencia: %s", exc)
        raise

    # Parte 3: Histórico (TASK-016) — independiente de buscador y persistencia
    try:
        # 6.1 Cargar configuración del histórico
        config_historico = cargar_configuracion_historico()
        logger.info(
            "Configuración del histórico cargada: zona=%s, hora=%02d:00",
            config_historico.zona_horaria,
            config_historico.hora_ejecucion,
        )

        # 6.2 Abrir conexión SQLite propia con WAL
        conexion_historico = abrir_conexion_historico(
            config_historico.ruta_sqlite_historico
        )
        logger.info(
            "Conexión SQLite del histórico abierta: %s (WAL activado)",
            config_historico.ruta_sqlite_historico,
        )

        # 6.3 Aplicar migraciones propias
        version_historico = migrar_historico(conexion_historico)
        logger.info(
            "Migraciones del histórico aplicadas: versión %d", version_historico
        )

        # 6.4 Instanciar repositorios
        repositorio_presencia = RepositorioPresencia(conexion_historico)
        repositorio_abstenciones = RepositorioAbstenciones(conexion_historico)
        repositorio_ejecucion = RepositorioEjecucion(conexion_historico)

        # 6.5 Instanciar adaptadores y clientes
        cliente_estado_buscador = ClienteEstadoBuscador(
            url_base=config_historico.url_base_buscador
        )
        cliente_persistencia_historico = ClientePersistencia(
            url_base=config_historico.url_base_persistencia
        )
        adaptador_lectura = AdaptadorLecturaHistorica(
            ruta_bd=config_historico.ruta_sqlite_persistencia
        )

        # Resolver la URL del PDF a partir del identificador configurado
        comunidades_pdf = cargar_comunidades()
        url_pdf = None
        for comunidad_pdf in comunidades_pdf:
            if comunidad_pdf.identificador == config_historico.pdf_identificador:
                url_pdf = comunidad_pdf.url_pdf
                break
        if url_pdf is None:
            raise ErrorConfiguracionHistorico(
                f"No se encontró la URL del PDF para el identificador "
                f"'{config_historico.pdf_identificador}' en config/comunidades.yaml."
            )

        adaptador_pdf = AdaptadorListadoPDF(
            url_pdf=url_pdf,
            comunidad=config_historico.pdf_comunidad,
        )

        # 6.6 Instanciar y arrancar tarea programada
        tarea_historico = TareaHistorico(
            config=config_historico,
            cliente_buscador=cliente_estado_buscador,
            cliente_persistencia=cliente_persistencia_historico,
            repositorio_presencia=repositorio_presencia,
            repositorio_abstenciones=repositorio_abstenciones,
            repositorio_ejecucion=repositorio_ejecucion,
            adaptador_pdf=adaptador_pdf,
        )
        tarea_historico.iniciar()
        logger.info("Tarea del histórico arrancada")

        # 6.7 Guardar referencias en app_state
        app_state["config_historico"] = config_historico
        app_state["conexion_historico"] = conexion_historico
        app_state["repositorio_presencia"] = repositorio_presencia
        app_state["repositorio_abstenciones"] = repositorio_abstenciones
        app_state["repositorio_ejecucion"] = repositorio_ejecucion
        app_state["cliente_estado_buscador"] = cliente_estado_buscador
        app_state["cliente_persistencia_historico"] = cliente_persistencia_historico
        app_state["adaptador_lectura_historica"] = adaptador_lectura
        app_state["adaptador_pdf"] = adaptador_pdf
        app_state["tarea_historico"] = tarea_historico

        logger.info("Histórico inicializado correctamente")

    except (ErrorConfiguracionHistorico, ErrorMigracionHistorico) as exc:
        logger.error(
            "Error en la configuración o migración del histórico: %s. "
            "La app continúa sin el histórico.",
            exc,
        )
    except Exception as exc:
        logger.error(
            "Error inesperado al inicializar el histórico: %s. "
            "La app continúa sin el histórico.",
            exc,
        )
    
    yield
    
    # === SHUTDOWN ===
    # 1. Detener tareas de persistencia PRIMERO (antes de cerrar conexión)
    tarea_ingesta = app_state.get("tarea_ingesta")
    if tarea_ingesta is not None:
        try:
            tarea_ingesta.detener()
        except Exception as e:
            logger.error(f"Error al detener tarea de ingesta: {e}")

    tarea_purga = app_state.get("tarea_purga")
    if tarea_purga is not None:
        try:
            tarea_purga.detener()
        except Exception as e:
            logger.error(f"Error al detener tarea de purga: {e}")

    # 2. Detener tarea del histórico (antes del scheduler y de cerrar su conexión)
    tarea_historico = app_state.get("tarea_historico")
    if tarea_historico is not None:
        try:
            tarea_historico.detener()
        except Exception as e:
            logger.error(f"Error al detener tarea del histórico: {e}")

    # 3. Cerrar conexión SQLite del histórico
    conexion_historico = app_state.get("conexion_historico")
    if conexion_historico is not None:
        try:
            conexion_historico.close()
            logger.info("Conexión SQLite del histórico cerrada correctamente")
        except Exception as e:
            logger.error(f"Error al cerrar conexión del histórico: {e}")

    # 4. Cerrar conexión SQLite de persistencia
    conexion_persistencia = app_state.get("conexion_persistencia")
    if conexion_persistencia is not None:
        try:
            conexion_persistencia.close()
            logger.info("Conexión SQLite cerrada correctamente")
        except Exception as e:
            logger.error(f"Error al cerrar conexión SQLite: {e}")

    # 5. Detener scheduler del buscador
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

# Registrar rutas de persistencia (TASK-013)
app.include_router(persistencia_router)

# Registrar rutas del histórico (TASK-016)
app.include_router(historico_router)


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
