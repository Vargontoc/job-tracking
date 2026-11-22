"""Cliente de la API de persistencia para el histórico de altas y cierres.

Expone las tres operaciones que ``api-historico`` consume de
``persistencia-api``: listar ofertas vigentes, consultar una oferta por su
clave natural ``(comunidad, codigo)`` y cerrar una oferta existente. No crea
ofertas nuevas ni expone operaciones de listado de códigos vistos ni de
lectura por rango de fechas (SUP-003).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Dataclasses de dominio
# ---------------------------------------------------------------------------

@dataclass
class Oferta:
    """Representación de una oferta devuelta por ``persistencia-api``.

    Contiene los campos mínimos que el histórico necesita para evaluar el
    cierre (estado, fechas y clave natural) junto con los campos que deben
    preservarse al cerrar una oferta (texto_libre, contacto, embedding y
    metadatos del modelo).

    Atributos:
        comunidad: Comunidad autónoma de la oferta.
        codigo: Código de la oferta (texto de 12 dígitos, NFR-003).
        estado: Estado de la oferta (``vigente``, ``cerrada``, ``sin_ficha``).
        fecha_alta: Marca ISO 8601 de creación del registro.
        fecha_cierre: Marca ISO 8601 de cierre, o ``None`` si no está cerrada.
        provincia: Provincia de la oferta.
        ocupacion: Denominación del puesto.
        municipio: Municipio de la oferta.
        sector: Sector profesional (siempre vacío, DEC-009).
        nivel: Nivel de estudios (siempre vacío, DEC-009).
        contrato: Tipo de contrato (siempre vacío, DEC-009).
        fecha_inicio_difusion: Fecha de inicio de difusión en ``dd/mm/aaaa``.
        fecha_fin_difusion: Fecha de fin de difusión en ``dd/mm/aaaa``.
        texto_libre: Texto libre de la oferta.
        contacto: Información de contacto.
        embedding: Embedding en base64 (string) si lo tiene.
        embedding_model_name: Nombre del modelo de embedding.
        embedding_model_version: Versión del modelo de embedding.
        embedding_dim: Dimensión del vector de embedding.
        interesada: Marca de interés para candidaturas.
        fecha_ultima_actualizacion: Marca ISO 8601 de la última escritura.
    """

    comunidad: str = ""
    codigo: str = ""
    estado: str = "vigente"
    fecha_alta: Optional[str] = None
    fecha_cierre: Optional[str] = None
    provincia: str = ""
    ocupacion: str = ""
    municipio: str = ""
    sector: str = ""
    nivel: str = ""
    contrato: str = ""
    fecha_inicio_difusion: Optional[str] = None
    fecha_fin_difusion: Optional[str] = None
    texto_libre: str = ""
    contacto: str = ""
    embedding: Optional[str] = None
    embedding_model_name: Optional[str] = None
    embedding_model_version: Optional[str] = None
    embedding_dim: Optional[int] = None
    interesada: bool = False
    fecha_ultima_actualizacion: Optional[str] = None


@dataclass
class ErrorPersistencia:
    """Error devuelto por el cliente de persistencia.

    Atributos:
        motivo: Descripción del error (HTTP, red o formato).
    """

    motivo: str = ""


@dataclass
class ResultadoConsulta:
    """Resultado de consultar una oferta por clave natural.

    Si la oferta existe, ``oferta`` contiene la :class:`Oferta` y ``error``
    está vacío. Si la clave no existe, ``oferta`` es ``None`` y ``error``
    está vacío. Si hubo un error HTTP o de red, ``oferta`` es ``None`` y
    ``error`` describe el problema.

    Atributos:
        oferta: Oferta encontrada, o ``None``.
        encontrada: ``True`` si la oferta existe.
        error: ``ErrorPersistencia`` si hubo un fallo de comunicación.
    """

    oferta: Optional[Oferta] = None
    encontrada: bool = False
    error: Optional[ErrorPersistencia] = None


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------

class ClientePersistencia:
    """Cliente HTTP de ``persistencia-api`` para el histórico.

    Expone exactamente las tres operaciones que consume ``api-historico``:

    - ``listar_vigentes()``: lista las ofertas con estado ``vigente``.
    - ``consultar_por_clave(comunidad, codigo)``: consulta una oferta por
      su clave natural.
    - ``cerrar_oferta(comunidad, codigo, fecha_cierre)``: actualiza el estado
      de una oferta existente a ``cerrada`` con su ``fecha_cierre``.

    Args:
        url_base: URL base de la API (por ejemplo, ``http://localhost:8000``).
        cliente_http: Cliente ``httpx.Client`` inyectable para pruebas. Si
            no se proporciona, se crea uno al hacer la primera consulta.
    """

    def __init__(
        self,
        url_base: str,
        cliente_http: httpx.Client | None = None,
    ) -> None:
        self._url_base = url_base.rstrip("/")
        self._cliente = cliente_http

    def listar_vigentes(self) -> list[Oferta] | ErrorPersistencia:
        """Lista las ofertas vigentes.

        Devuelve una lista de :class:`Oferta` si la petición tuvo éxito, o
        un :class:`ErrorPersistencia` si hubo un error HTTP, de red o de
        formato. Nunca lanza excepciones.

        Returns:
            Lista de ofertas vigentes o error de comunicación.
        """
        url = f"{self._url_base}/persistencia/ofertas/vigentes"
        respuesta = self._hacer_get(url)
        if isinstance(respuesta, ErrorPersistencia):
            return respuesta

        try:
            datos = respuesta.json()
        except Exception as error:
            return ErrorPersistencia(
                motivo=f"La respuesta de {url} no es JSON válido: {error}."
            )

        ofertas: list[Oferta] = []
        for item in datos:
            ofertas.append(_oferta_desde_json(item))
        return ofertas

    def consultar_por_clave(
        self, comunidad: str, codigo: str
    ) -> ResultadoConsulta:
        """Consulta una oferta por su clave natural ``(comunidad, codigo)``.

        Devuelve un :class:`ResultadoConsulta` con ``encontrada=True`` y la
        oferta si existe; con ``encontrada=False`` si la clave no existe
        (HTTP 404); o con ``error`` si hubo un fallo de comunicación.

        Args:
            comunidad: Comunidad de la oferta.
            codigo: Código de la oferta (texto de 12 dígitos).

        Returns:
            Resultado de la consulta.
        """
        url = f"{self._url_base}/persistencia/ofertas/{comunidad}/{codigo}"
        try:
            respuesta = self._obtener_cliente().get(url)
            if respuesta.status_code == 404:
                return ResultadoConsulta(encontrada=False, oferta=None)
            respuesta.raise_for_status()
        except httpx.HTTPStatusError as error:
            return ResultadoConsulta(
                error=ErrorPersistencia(
                    motivo=(
                        f"Error HTTP {error.response.status_code} "
                        f"al consultar la oferta ({comunidad}, {codigo}) "
                        f"en {url}."
                    )
                )
            )
        except httpx.RequestError as error:
            return ResultadoConsulta(
                error=ErrorPersistencia(
                    motivo=(
                        f"Error de red al consultar la oferta "
                        f"({comunidad}, {codigo}) en {url}: {error}."
                    )
                )
            )

        try:
            datos = respuesta.json()
        except Exception as error:
            return ResultadoConsulta(
                error=ErrorPersistencia(
                    motivo=f"La respuesta de {url} no es JSON válido: {error}."
                )
            )

        oferta = _oferta_desde_json(datos)
        return ResultadoConsulta(oferta=oferta, encontrada=True)

    def cerrar_oferta(
        self, comunidad: str, codigo: str, fecha_cierre: str
    ) -> bool | ErrorPersistencia:
        """Cierra una oferta existente, actualizando su estado y fecha de cierre.

        Consulta primero la oferta por su clave natural para verificar que
        existe y obtener sus campos actuales. Si la oferta no existe,
        devuelve ``False`` sin excepción. Si ya está cerrada, no modifica
        su ``fecha_cierre`` existente y devuelve ``True`` (idempotente).

        Construye el cuerpo completo de la oferta preservando texto_libre,
        contacto, embedding y metadatos del modelo (REQ-010, ALT-009),
        cambiando solo ``estado`` a ``cerrada`` y ``fecha_cierre``.

        Args:
            comunidad: Comunidad de la oferta.
            codigo: Código de la oferta (texto de 12 dígitos).
            fecha_cierre: Marca ISO 8601 del cierre.

        Returns:
            ``True`` si la oferta se cerró correctamente o ya estaba cerrada.
            ``False`` si la oferta no existe. :class:`ErrorPersistencia` si
            hubo un error de comunicación.
        """
        # Paso 1: consultar la oferta por clave natural.
        resultado = self.consultar_por_clave(comunidad, codigo)
        if resultado.error is not None:
            return resultado.error
        if not resultado.encontrada or resultado.oferta is None:
            return False

        oferta_actual = resultado.oferta

        # Si ya está cerrada, no modificar la fecha_cierre existente (idempotente).
        if oferta_actual.estado == "cerrada":
            return True

        # Paso 2: construir el cuerpo completo preservando todos los campos.
        cuerpo = _construir_cuerpo_cierre(oferta_actual, fecha_cierre)

        # Paso 3: enviar POST para actualizar.
        url = f"{self._url_base}/persistencia/ofertas"
        try:
            respuesta = self._obtener_cliente().post(url, json=cuerpo)
            respuesta.raise_for_status()
        except httpx.HTTPStatusError as error:
            return ErrorPersistencia(
                motivo=(
                    f"Error HTTP {error.response.status_code} "
                    f"al cerrar la oferta ({comunidad}, {codigo}) "
                    f"en {url}."
                )
            )
        except httpx.RequestError as error:
            return ErrorPersistencia(
                motivo=(
                    f"Error de red al cerrar la oferta "
                    f"({comunidad}, {codigo}) en {url}: {error}."
                )
            )

        return True

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _obtener_cliente(self) -> httpx.Client:
        """Devuelve el cliente HTTP, creándolo si es necesario."""
        if self._cliente is None:
            self._cliente = httpx.Client()
        return self._cliente

    def _hacer_get(
        self, url: str
    ) -> httpx.Response | ErrorPersistencia:
        """Realiza una petición GET y devuelve la respuesta o un error."""
        try:
            respuesta = self._obtener_cliente().get(url)
            respuesta.raise_for_status()
        except httpx.HTTPStatusError as error:
            return ErrorPersistencia(
                motivo=(
                    f"Error HTTP {error.response.status_code} "
                    f"al consultar {url}."
                )
            )
        except httpx.RequestError as error:
            return ErrorPersistencia(
                motivo=(
                    f"Error de red al consultar {url}: {error}."
                )
            )
        return respuesta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _oferta_desde_json(datos: dict) -> Oferta:
    """Convierte un diccionario JSON de ``OfertaSalida`` en una :class:`Oferta`."""
    return Oferta(
        comunidad=datos.get("comunidad", ""),
        codigo=datos.get("codigo", ""),
        estado=datos.get("estado", "vigente"),
        fecha_alta=datos.get("fecha_alta"),
        fecha_cierre=datos.get("fecha_cierre"),
        provincia=datos.get("provincia", ""),
        ocupacion=datos.get("ocupacion", ""),
        municipio=datos.get("municipio", ""),
        sector=datos.get("sector", ""),
        nivel=datos.get("nivel", ""),
        contrato=datos.get("contrato", ""),
        fecha_inicio_difusion=datos.get("fecha_inicio_difusion"),
        fecha_fin_difusion=datos.get("fecha_fin_difusion"),
        texto_libre=datos.get("texto_libre", ""),
        contacto=datos.get("contacto", ""),
        embedding=datos.get("embedding"),
        embedding_model_name=datos.get("embedding_model_name"),
        embedding_model_version=datos.get("embedding_model_version"),
        embedding_dim=datos.get("embedding_dim"),
        interesada=datos.get("interesada", False),
        fecha_ultima_actualizacion=datos.get("fecha_ultima_actualizacion"),
    )


def _construir_cuerpo_cierre(oferta: Oferta, fecha_cierre: str) -> dict:
    """Construye el cuerpo JSON para cerrar una oferta preservando todos sus campos.

    Copia todos los campos de la oferta actual al cuerpo de ``OfertaEntrada``,
    cambiando solo ``estado`` a ``cerrada`` y añadiendo ``fecha_cierre`` con
    la marca indicada. No vacía texto_libre, contacto ni embedding (REQ-010,
    ALT-009). ``fecha_cierre`` se envía en el cuerpo aunque el modelo de
    entrada actual de la API no lo incluya; la API lo ignorará si no lo
    acepta, pero el cliente lo envía conforme al sprint.
    """
    return {
        "comunidad": oferta.comunidad,
        "codigo": oferta.codigo,
        "provincia": oferta.provincia,
        "ocupacion": oferta.ocupacion,
        "municipio": oferta.municipio,
        "sector": oferta.sector,
        "nivel": oferta.nivel,
        "contrato": oferta.contrato,
        "fecha_inicio_difusion": oferta.fecha_inicio_difusion,
        "fecha_fin_difusion": oferta.fecha_fin_difusion,
        "estado": "cerrada",
        "fecha_cierre": fecha_cierre,
        "texto_libre": oferta.texto_libre,
        "contacto": oferta.contacto,
        "embedding": oferta.embedding,
        "embedding_model_name": oferta.embedding_model_name,
        "embedding_model_version": oferta.embedding_model_version,
        "embedding_dim": oferta.embedding_dim,
        "interesada": oferta.interesada,
    }
