"""Endpoints de la API de persistencia: CRUD de ofertas y códigos vistos."""

from __future__ import annotations

import base64
import logging
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from source.api.persistencia.repository import (
    EstadoOferta,
    Oferta,
    RepositorioOfertas,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persistencia", tags=["persistencia"])


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------

class OfertaEntrada(BaseModel):
    """Datos para crear o actualizar una oferta.

    El embedding se envía como base64 (string, format byte) y se convierte
    a bytes en el borde de la API.
    """

    comunidad: str
    codigo: str
    provincia: str = ""
    ocupacion: str = ""
    municipio: str = ""
    sector: str = ""
    nivel: str = ""
    contrato: str = ""
    fecha_inicio_difusion: Optional[str] = None
    fecha_fin_difusion: Optional[str] = None
    estado: str = EstadoOferta.VIGENTE
    texto_libre: str = ""
    contacto: str = ""
    embedding: Optional[str] = Field(
        default=None,
        description="Embedding en base64 (type: string, format: byte)",
    )
    embedding_model_name: Optional[str] = None
    embedding_model_version: Optional[str] = None
    embedding_dim: Optional[int] = None
    interesada: bool = False


class OfertaSalida(BaseModel):
    """Datos completos de una oferta (salida JSON).

    El embedding se expone como base64 (string, format byte).
    """

    comunidad: str
    provincia: str
    codigo: str
    ocupacion: str
    municipio: str
    sector: str
    nivel: str
    contrato: str
    fecha_inicio_difusion: Optional[str] = None
    fecha_fin_difusion: Optional[str] = None
    estado: str
    texto_libre: str
    contacto: str
    embedding: Optional[str] = Field(
        default=None,
        description="Embedding en base64 (type: string, format: byte)",
    )
    embedding_model_name: Optional[str] = None
    embedding_model_version: Optional[str] = None
    embedding_dim: Optional[int] = None
    interesada: bool = False
    fecha_alta: Optional[str] = None
    fecha_cierre: Optional[str] = None
    fecha_ultima_actualizacion: Optional[str] = None


class CodigoVistoSalida(BaseModel):
    """Lista de códigos vistos de una comunidad."""

    comunidad: str
    codigos: list[str]


class OfertaCreadaSalida(BaseModel):
    """Confirmación de creación o actualización de una oferta."""

    comunidad: str
    codigo: str
    estado: str
    mensaje: str = "oferta persistida correctamente"


# ---------------------------------------------------------------------------
# Helpers de conversión de embedding
# ---------------------------------------------------------------------------

def _embedding_a_base64(vector: Optional[np.ndarray]) -> Optional[str]:
    """Convierte un array numpy float32 a base64."""
    if vector is None:
        return None
    blob = np.asarray(vector, dtype=np.float32).tobytes()
    return base64.b64encode(blob).decode("ascii")


def _base64_a_embedding(b64: Optional[str]) -> Optional[np.ndarray]:
    """Convierte un string base64 a array numpy float32."""
    if b64 is None:
        return None
    blob = base64.b64decode(b64)
    return np.frombuffer(blob, dtype=np.float32).copy()


def _oferta_a_salida(oferta: Oferta) -> OfertaSalida:
    """Convierte una Oferta del repositorio a OfertaSalida Pydantic."""
    return OfertaSalida(
        comunidad=oferta.comunidad,
        provincia=oferta.provincia,
        codigo=oferta.codigo,
        ocupacion=oferta.ocupacion,
        municipio=oferta.municipio,
        sector=oferta.sector,
        nivel=oferta.nivel,
        contrato=oferta.contrato,
        fecha_inicio_difusion=oferta.fecha_inicio_difusion,
        fecha_fin_difusion=oferta.fecha_fin_difusion,
        estado=oferta.estado,
        texto_libre=oferta.texto_libre,
        contacto=oferta.contacto,
        embedding=_embedding_a_base64(oferta.embedding),
        embedding_model_name=oferta.embedding_model_name,
        embedding_model_version=oferta.embedding_model_version,
        embedding_dim=oferta.embedding_dim,
        interesada=oferta.interesada,
        fecha_alta=oferta.fecha_alta,
        fecha_cierre=oferta.fecha_cierre,
        fecha_ultima_actualizacion=oferta.fecha_ultima_actualizacion,
    )


def _obtener_repositorio() -> RepositorioOfertas:
    """Obtiene el RepositorioOfertas del app_state.

    Importación perezosa para evitar import circular con source.api.main.
    """
    from source.api.main import app_state

    repo = app_state.get("repositorio")
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail="El repositorio de persistencia no está disponible",
        )
    return repo


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/ofertas",
    response_model=OfertaCreadaSalida,
    summary="Crear o actualizar una oferta",
)
def crear_o_actualizar_oferta(datos: OfertaEntrada) -> OfertaCreadaSalida:
    """Crea o actualiza una oferta sin duplicar la fila (upsert).

    Si la oferta no existe se crea con estado vigente (o el indicado);
    si ya existe se actualizan los campos modificables. El embedding se
    recibe en base64 y se convierte a bytes antes de persistir.
    """
    repo = _obtener_repositorio()

    embedding = _base64_a_embedding(datos.embedding)

    oferta = Oferta(
        comunidad=datos.comunidad,
        codigo=datos.codigo,
        provincia=datos.provincia,
        ocupacion=datos.ocupacion,
        municipio=datos.municipio,
        sector=datos.sector,
        nivel=datos.nivel,
        contrato=datos.contrato,
        fecha_inicio_difusion=datos.fecha_inicio_difusion,
        fecha_fin_difusion=datos.fecha_fin_difusion,
        estado=datos.estado,
        texto_libre=datos.texto_libre,
        contacto=datos.contacto,
        embedding=embedding,
        embedding_model_name=datos.embedding_model_name,
        embedding_model_version=datos.embedding_model_version,
        embedding_dim=datos.embedding_dim,
        interesada=datos.interesada,
    )
    repo.crear_o_actualizar(oferta)

    return OfertaCreadaSalida(
        comunidad=datos.comunidad,
        codigo=datos.codigo,
        estado=datos.estado,
    )


@router.get(
    "/ofertas/vigentes",
    response_model=list[OfertaSalida],
    summary="Listar ofertas vigentes",
)
def listar_ofertas_vigentes() -> list[OfertaSalida]:
    """Devuelve las ofertas con estado 'vigente' ordenadas por fecha de fin."""
    repo = _obtener_repositorio()
    ofertas = repo.listar_vigentes()
    return [_oferta_a_salida(o) for o in ofertas]


@router.get(
    "/ofertas/{comunidad}/{codigo}",
    response_model=OfertaSalida,
    summary="Consultar oferta por clave natural",
)
def consultar_oferta(comunidad: str, codigo: str) -> OfertaSalida:
    """Consulta una oferta por (comunidad, codigo).

    Devuelve todos los campos de la oferta incluyendo estado, embedding
    en base64 y metadatos del modelo. Si no se encuentra, devuelve 404.
    """
    repo = _obtener_repositorio()
    resultado = repo.consultar_por_clave(comunidad, codigo)
    if not resultado.encontrada or resultado.oferta is None:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró la oferta ({comunidad}, {codigo})",
        )
    return _oferta_a_salida(resultado.oferta)


@router.get(
    "/codigos-vistos/{comunidad}",
    response_model=CodigoVistoSalida,
    summary="Listar códigos vistos de una comunidad",
)
def listar_codigos_vistos(comunidad: str) -> CodigoVistoSalida:
    """Devuelve los códigos vistos de una comunidad (importados + ingeridos)."""
    repo = _obtener_repositorio()
    codigos = repo.listar_codigos_vistos(comunidad)
    return CodigoVistoSalida(comunidad=comunidad, codigos=codigos)
