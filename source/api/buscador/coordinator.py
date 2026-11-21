"""Coordinador de una pasada completa del rastreador del buscador.

Orquesta el flujo completo: carga de códigos vistos, recorrido del listado,
parseo de fichas nuevas, archivado de errores, purga y ensamblado del resultado.
Implementa exclusión mutua para evitar pasadas concurrentes.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from source.api.buscador.archive import ErrorArchivado, archivar_html_fallido
from source.api.buscador.assembler import ensamblar_resultado_pasada
from source.api.buscador.models import (
    ConfigBuscador,
    ErrorOferta,
    OfertaBuscador,
    ResultadoPasada,
)
from source.api.buscador.parser import ResultadoFicha, parsear_ficha
from source.api.buscador.purger import purgar_html_caducados
from source.api.buscador.scraper import ResultadoListado, recorrer_listado
from source.api.buscador.state import guardar_codigos_vistos, leer_codigos_vistos

logger = logging.getLogger(__name__)


@dataclass
class ProgresoPasada:
    """Progreso de una pasada en curso.

    Atributos:
        hora_inicio: Timestamp ISO del inicio de la pasada.
        codigos_procesados: Número de códigos procesados hasta ahora.
        total_codigos: Total de códigos a procesar.
    """

    hora_inicio: str = ""
    codigos_procesados: int = 0
    total_codigos: int = 0


@dataclass
class CoordinadorPasada:
    """Coordinador que orquesta una pasada completa del rastreador.

    Mantiene el estado compartido entre scheduler y endpoints: flag de
    pasada en curso, último resultado y progreso. Implementa exclusión
    mutua para evitar pasadas concurrentes.

    Atributos:
        config: Configuración del buscador.
        cliente: Cliente HTTP (compatible con httpx.Client).
        limitador: Limitador de peticiones compartido.
        ruta_seen_codes: Ruta al fichero de códigos vistos.
        ruta_failed_htmls: Ruta al directorio de HTML fallidos.
        dias_purga: Días para purgar HTML fallidos.
    """

    config: ConfigBuscador
    cliente: object  # ClienteHTTP protocol
    limitador: object  # LimitadorPeticiones
    ruta_seen_codes: Path
    ruta_failed_htmls: Path
    dias_purga: int = 7

    # Estado compartido (protegido por lock)
    _pasada_en_curso: bool = field(default=False, init=False)
    _ultimo_resultado: ResultadoPasada | None = field(default=None, init=False)
    _progreso: ProgresoPasada = field(default_factory=ProgresoPasada, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def pasada_en_curso(self) -> bool:
        """Indica si hay una pasada en curso."""
        with self._lock:
            return self._pasada_en_curso

    @property
    def ultimo_resultado(self) -> ResultadoPasada | None:
        """Devuelve el último resultado de pasada."""
        with self._lock:
            return self._ultimo_resultado

    @property
    def progreso(self) -> ProgresoPasada:
        """Devuelve el progreso de la pasada en curso."""
        with self._lock:
            return self._progreso

    def ejecutar_pasada(self, historical_codes: list[str] | None = None) -> ResultadoPasada:
        """Ejecuta una pasada completa del rastreador.

        Si ya hay una pasada en curso, devuelve un resultado con error_global
        indicando la omisión. En caso contrario, ejecuta el flujo completo:
        1. Carga códigos vistos (del fichero o de historical_codes)
        2. Recorre el listado
        3. Parsea fichas de códigos nuevos
        4. Guarda códigos vistos actualizados (solo si no se usó historical_codes)
        5. Purga HTML fallidos antiguos
        6. Ensambla y devuelve el resultado

        Args:
            historical_codes: Lista opcional de códigos históricos para filtrar.
                Si es None, se lee del fichero data/seen_codes.json.
                Si se proporciona, se usa esa lista para filtrar y NO se modifica el fichero.

        Returns:
            ResultadoPasada con el resultado de la ejecución.
        """
        logger.info("INICIO ejecutar_pasada")
        
        # Exclusión mutua: verificar si hay otra pasada en curso
        logger.debug("Adquiriendo lock...")
        with self._lock:
            if self._pasada_en_curso:
                logger.warning("Pasada en curso detectada, retornando inmediatamente")
                return ResultadoPasada(
                    timestamp=datetime.now().isoformat(timespec="seconds"),
                    comunidad="Cantabria",
                    total_listado=0,
                    error_global="Ya hay una pasada en curso",
                    errores_por_oferta=[],
                    ofertas_nuevas=[],
                )
            self._pasada_en_curso = True
            hora_inicio = datetime.now().isoformat(timespec="seconds")
            self._progreso = ProgresoPasada(hora_inicio=hora_inicio)
            logger.info(f"Lock adquirido, pasada iniciada a las {hora_inicio}")

        try:
            resultado = self._ejecutar_pasada_interna(hora_inicio, historical_codes)
            logger.info(f"FIN ejecutar_pasada exitosa")
            return resultado
        except Exception as e:
            logger.error(f"ERROR en ejecutar_pasada: {e}", exc_info=True)
            raise
        finally:
            with self._lock:
                self._pasada_en_curso = False
                logger.debug("Lock liberado, pasada marcada como completada")

    def _ejecutar_pasada_interna(
        self, hora_inicio: str, historical_codes: list[str] | None = None
    ) -> ResultadoPasada:
        """Implementación interna de la pasada (sin verificación de exclusión mutua)."""
        # 1. Cargar códigos vistos
        logger.debug("Paso 1: Leyendo códigos vistos")
        # Si se proporcionó historical_codes, usarlo; si no, leer del fichero
        if historical_codes is not None:
            codigos_vistos = set(historical_codes)
            usar_historical = True
            logger.info(f"Usando historical_codes proporcionados: {len(codigos_vistos)} códigos")
        else:
            codigos_vistos = leer_codigos_vistos(self.ruta_seen_codes)
            usar_historical = False
            logger.info(f"Códigos vistos leídos del fichero: {len(codigos_vistos)} códigos")

        # 2. Recorrer el listado
        logger.debug("Paso 2: Recorriendo listado del buscador")
        resultado_listado = recorrer_listado(
            cliente=self.cliente,
            url_listado=self.config.url_listado,
            limitador=self.limitador,
            tamano_pagina=self.config.tamano_pagina,
            timeout=30.0,
            codigos_vistos=codigos_vistos,
        )
        logger.info(f"Listado recorrido: total={resultado_listado.total}, códigos nuevos={len(resultado_listado.codigos)}, páginas={resultado_listado.paginas_solicitadas}")

        # Si hubo error global en el listado, devolver resultado con error
        if resultado_listado.error_global:
            logger.error(f"Error global en listado: {resultado_listado.error_global}")
            resultado = ResultadoPasada(
                timestamp=hora_inicio,
                comunidad="Cantabria",
                total_listado=resultado_listado.total,
                error_global=resultado_listado.error_global,
                errores_por_oferta=[],
                ofertas_nuevas=[],
            )
            with self._lock:
                self._ultimo_resultado = resultado
            return resultado

        # 3. Actualizar progreso con total de códigos a procesar
        codigos_nuevos = resultado_listado.codigos
        with self._lock:
            self._progreso.total_codigos = len(codigos_nuevos)
            self._progreso.codigos_procesados = 0

        # 4. Parsear fichas de códigos nuevos
        logger.debug(f"Paso 3: Parseando {len(codigos_nuevos)} fichas nuevas")
        ofertas_nuevas: list[OfertaBuscador] = []
        errores_por_oferta: list[ErrorOferta] = []
        codigos_parseados_correctamente: set[str] = set()

        for idx, codigo in enumerate(codigos_nuevos, 1):
            logger.debug(f"Parseando ficha {idx}/{len(codigos_nuevos)}: {codigo}")
            # Parsear ficha
            resultado_ficha = parsear_ficha(
                cliente=self.cliente,
                url_base=self.config.url_ficha,
                codigo=codigo,
                limitador=self.limitador,
                timeout=30.0,
            )

            if resultado_ficha.oferta is not None:
                # Éxito: agregar a ofertas nuevas
                logger.debug(f"Ficha {codigo} parseada correctamente")
                ofertas_nuevas.append(resultado_ficha.oferta)
                codigos_parseados_correctamente.add(codigo)
            else:
                # Error: archivar HTML y agregar a errores
                logger.warning(f"Error al parsear ficha {codigo}: {resultado_ficha.error}")
                if resultado_ficha.html:
                    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                    try:
                        archivar_html_fallido(
                            codigo=codigo,
                            html=resultado_ficha.html,
                            fecha=fecha_hoy,
                            directorio=self.ruta_failed_htmls,
                        )
                    except ErrorArchivado:
                        # Error de archivado no detiene la pasada
                        pass

                errores_por_oferta.append(
                    ErrorOferta(
                        codigo=codigo,
                        mensaje=resultado_ficha.error,
                    )
                )

            # Actualizar progreso
            with self._lock:
                self._progreso.codigos_procesados += 1

        # 5. Guardar códigos vistos actualizados (solo si NO se usó historical_codes)
        logger.debug("Paso 4: Guardando códigos vistos actualizados")
        if codigos_parseados_correctamente and not usar_historical:
            guardar_codigos_vistos(self.ruta_seen_codes, codigos_parseados_correctamente)
            logger.info(f"Códigos vistos guardados: {len(codigos_parseados_correctamente)} nuevos")
        else:
            logger.debug("No se guardaron códigos (usando historical_codes o sin códigos nuevos)")

        # 6. Purgar HTML fallidos antiguos
        logger.debug("Paso 5: Purgando HTML fallidos antiguos")
        purgar_html_caducados(self.ruta_failed_htmls, self.dias_purga)

        # 7. Ensamblar resultado final
        logger.debug("Paso 6: Ensamblando resultado final")
        hora_fin = datetime.now().isoformat(timespec="seconds")
        resultado = ensamblar_resultado_pasada(
            timestamp_inicio=hora_inicio,
            timestamp_fin=hora_fin,
            ofertas_nuevas=ofertas_nuevas,
            errores_por_oferta=errores_por_oferta,
            error_global="",
            total_listado=resultado_listado.total,
            comunidad="Cantabria",
        )

        with self._lock:
            self._ultimo_resultado = resultado

        logger.info(f"Resultado ensamblado: {len(ofertas_nuevas)} ofertas nuevas, {len(errores_por_oferta)} errores")
        return resultado
