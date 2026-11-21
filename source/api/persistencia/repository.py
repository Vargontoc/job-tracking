"""Repositorio de ofertas: upsert y consulta por clave natural (comunidad, codigo)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from source.api.persistencia.connection import transaccion


# ---------------------------------------------------------------------------
# Constantes de estado
# ---------------------------------------------------------------------------

class EstadoOferta:
    """Estados válidos de una oferta."""

    SIN_FICHA = "sin_ficha"
    VIGENTE = "vigente"
    CERRADA = "cerrada"


# ---------------------------------------------------------------------------
# Dataclass Oferta
# ---------------------------------------------------------------------------

@dataclass
class Oferta:
    """Representa una oferta de empleo persistible."""

    comunidad: str
    codigo: str
    estado: str = EstadoOferta.VIGENTE
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
    embedding: Optional[np.ndarray] = None
    embedding_model_name: Optional[str] = None
    embedding_model_version: Optional[str] = None
    embedding_dim: Optional[int] = None
    interesada: bool = False
    fecha_alta: Optional[str] = None
    fecha_cierre: Optional[str] = None
    fecha_ultima_actualizacion: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers de embedding (numpy float32)
# ---------------------------------------------------------------------------

def serializar_embedding(vector: np.ndarray) -> bytes:
    """Serializa un array numpy float32 a bytes contiguos."""
    return np.asarray(vector, dtype=np.float32).tobytes()


def reconstruir_embedding(blob: bytes, dimension: int) -> np.ndarray:
    """Reconstruye un array numpy float32 a partir de bytes y dimensión."""
    return np.frombuffer(blob, dtype=np.float32).reshape(dimension).copy()


# ---------------------------------------------------------------------------
# Resultado de consulta
# ---------------------------------------------------------------------------

@dataclass
class ResultadoConsulta:
    """Resultado de consultar una oferta por clave natural.

    Si `encontrada` es False, `oferta` es None.
    """

    encontrada: bool
    oferta: Optional[Oferta] = None


# ---------------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------------

class RepositorioOfertas:
    """Abstracción de escritura y lectura de ofertas sobre (comunidad, codigo)."""

    def __init__(self, conexion: sqlite3.Connection) -> None:
        """Inicializa el repositorio con una conexión SQLite.

        Args:
            conexion: Conexión SQLite abierta (no se abre internamente).
        """
        self._conexion = conexion

    def crear_o_actualizar(self, oferta: Oferta) -> None:
        """Crea o actualiza una oferta sin duplicar la fila (upsert).

        - Si la oferta no existe, crea un registro con todos los campos recibidos
          y estado vigente (o el que traiga la oferta).
        - Si la oferta existe, actualiza los campos modificables sin duplicar
          la fila y actualiza fecha_ultima_actualizacion sin tocar fecha_alta.
        - sector, nivel y contrato se almacenan siempre vacíos (DEC-009).

        Args:
            oferta: Oferta a persistir.
        """
        ahora = datetime.now(timezone.utc).isoformat()

        # Serializar embedding si existe
        embedding_blob = None
        embedding_dim = oferta.embedding_dim
        if oferta.embedding is not None:
            embedding_blob = serializar_embedding(oferta.embedding)
            if embedding_dim is None:
                embedding_dim = len(oferta.embedding)

        # Forzar sector, nivel, contrato vacíos (DEC-009)
        sector = ""
        nivel = ""
        contrato = ""

        with transaccion(self._conexion):
            # Comprobar si ya existe
            fila = self._conexion.execute(
                "SELECT fecha_alta FROM ofertas WHERE comunidad = ? AND codigo = ?",
                (oferta.comunidad, oferta.codigo),
            ).fetchone()

            if fila is None:
                # Insertar nueva oferta
                fecha_alta = oferta.fecha_alta or ahora
                self._conexion.execute(
                    """INSERT INTO ofertas
                       (comunidad, provincia, codigo, ocupacion, municipio,
                        sector, nivel, contrato, fecha_inicio_difusion,
                        fecha_fin_difusion, estado, texto_libre, contacto,
                        embedding, embedding_model_name, embedding_model_version,
                        embedding_dim, interesada, fecha_alta, fecha_cierre,
                        fecha_ultima_actualizacion)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        oferta.comunidad,
                        oferta.provincia,
                        oferta.codigo,
                        oferta.ocupacion,
                        oferta.municipio,
                        sector,
                        nivel,
                        contrato,
                        oferta.fecha_inicio_difusion,
                        oferta.fecha_fin_difusion,
                        oferta.estado,
                        oferta.texto_libre,
                        oferta.contacto,
                        embedding_blob,
                        oferta.embedding_model_name,
                        oferta.embedding_model_version,
                        embedding_dim,
                        1 if oferta.interesada else 0,
                        fecha_alta,
                        oferta.fecha_cierre,
                        ahora,
                    ),
                )
            else:
                # Actualizar oferta existente sin tocar fecha_alta
                self._conexion.execute(
                    """UPDATE ofertas SET
                        provincia = ?, ocupacion = ?, municipio = ?,
                        sector = ?, nivel = ?, contrato = ?,
                        fecha_inicio_difusion = ?, fecha_fin_difusion = ?,
                        estado = ?, texto_libre = ?, contacto = ?,
                        embedding = ?, embedding_model_name = ?,
                        embedding_model_version = ?, embedding_dim = ?,
                        interesada = ?, fecha_cierre = ?,
                        fecha_ultima_actualizacion = ?
                       WHERE comunidad = ? AND codigo = ?""",
                    (
                        oferta.provincia,
                        oferta.ocupacion,
                        oferta.municipio,
                        sector,
                        nivel,
                        contrato,
                        oferta.fecha_inicio_difusion,
                        oferta.fecha_fin_difusion,
                        oferta.estado,
                        oferta.texto_libre,
                        oferta.contacto,
                        embedding_blob,
                        oferta.embedding_model_name,
                        oferta.embedding_model_version,
                        embedding_dim,
                        1 if oferta.interesada else 0,
                        oferta.fecha_cierre,
                        ahora,
                        oferta.comunidad,
                        oferta.codigo,
                    ),
                )
                # Asegurar que fecha_alta no cambia (ya está preservada en el UPDATE)

    def consultar_por_clave(
        self, comunidad: str, codigo: str
    ) -> ResultadoConsulta:
        """Consulta una oferta por su comunidad y código.

        Devuelve un ResultadoConsulta con encontrada=True y la Oferta si existe,
        o encontrada=False y oferta=None si no se encuentra.

        Args:
            comunidad: Comunidad de la oferta.
            codigo: Código de la oferta (texto de 12 dígitos).

        Returns:
            ResultadoConsulta con la oferta o indicando que no se encontró.
        """
        fila = self._conexion.execute(
            """SELECT comunidad, provincia, codigo, ocupacion, municipio,
                      sector, nivel, contrato, fecha_inicio_difusion,
                      fecha_fin_difusion, estado, texto_libre, contacto,
                      embedding, embedding_model_name, embedding_model_version,
                      embedding_dim, interesada, fecha_alta, fecha_cierre,
                      fecha_ultima_actualizacion
               FROM ofertas
               WHERE comunidad = ? AND codigo = ?""",
            (comunidad, codigo),
        ).fetchone()

        if fila is None:
            return ResultadoConsulta(encontrada=False, oferta=None)

        # Reconstruir embedding si existe
        embedding = None
        embedding_blob = fila[13]
        embedding_dim = fila[16]
        if embedding_blob is not None and embedding_dim is not None:
            embedding = reconstruir_embedding(embedding_blob, embedding_dim)

        oferta = Oferta(
            comunidad=fila[0],
            provincia=fila[1] or "",
            codigo=fila[2],
            ocupacion=fila[3] or "",
            municipio=fila[4] or "",
            sector=fila[5] or "",
            nivel=fila[6] or "",
            contrato=fila[7] or "",
            fecha_inicio_difusion=fila[8],
            fecha_fin_difusion=fila[9],
            estado=fila[10],
            texto_libre=fila[11] or "",
            contacto=fila[12] or "",
            embedding=embedding,
            embedding_model_name=fila[14],
            embedding_model_version=fila[15],
            embedding_dim=embedding_dim,
            interesada=bool(fila[17]),
            fecha_alta=fila[18],
            fecha_cierre=fila[19],
            fecha_ultima_actualizacion=fila[20],
        )
        return ResultadoConsulta(encontrada=True, oferta=oferta)

    def listar_vigentes(self) -> list[Oferta]:
        """Lista las ofertas con estado 'vigente' ordenadas por fecha_fin_difusion.

        Utiliza el índice (estado, fecha_fin_difusion) creado en la migración
        inicial, por lo que no escanea la tabla completa.

        Returns:
            Lista de Oferta en estado vigente, ordenada por fecha de fin de difusión.
        """
        filas = self._conexion.execute(
            """SELECT comunidad, provincia, codigo, ocupacion, municipio,
                      sector, nivel, contrato, fecha_inicio_difusion,
                      fecha_fin_difusion, estado, texto_libre, contacto,
                      embedding, embedding_model_name, embedding_model_version,
                      embedding_dim, interesada, fecha_alta, fecha_cierre,
                      fecha_ultima_actualizacion
               FROM ofertas
               WHERE estado = ?
               ORDER BY fecha_fin_difusion""",
            (EstadoOferta.VIGENTE,),
        ).fetchall()

        ofertas: list[Oferta] = []
        for fila in filas:
            embedding = None
            embedding_blob = fila[13]
            embedding_dim = fila[16]
            if embedding_blob is not None and embedding_dim is not None:
                embedding = reconstruir_embedding(embedding_blob, embedding_dim)

            ofertas.append(Oferta(
                comunidad=fila[0],
                provincia=fila[1] or "",
                codigo=fila[2],
                ocupacion=fila[3] or "",
                municipio=fila[4] or "",
                sector=fila[5] or "",
                nivel=fila[6] or "",
                contrato=fila[7] or "",
                fecha_inicio_difusion=fila[8],
                fecha_fin_difusion=fila[9],
                estado=fila[10],
                texto_libre=fila[11] or "",
                contacto=fila[12] or "",
                embedding=embedding,
                embedding_model_name=fila[14],
                embedding_model_version=fila[15],
                embedding_dim=embedding_dim,
                interesada=bool(fila[17]),
                fecha_alta=fila[18],
                fecha_cierre=fila[19],
                fecha_ultima_actualizacion=fila[20],
            ))
        return ofertas

    def reducir_a_registro_minimo(self, comunidad: str, codigo: str) -> None:
        """Reduce una oferta al registro mínimo: vacía texto_libre y contacto.

        Conserva todos los demás campos, incluido el embedding con su nombre,
        versión y dimensión. No toca interesada, fecha_alta, fecha_cierre
        ni fecha_ultima_actualizacion. La operación es idempotente.

        Args:
            comunidad: Comunidad de la oferta.
            codigo: Código de la oferta (texto de 12 dígitos).
        """
        with transaccion(self._conexion):
            self._conexion.execute(
                "UPDATE ofertas SET texto_libre = NULL, contacto = NULL "
                "WHERE comunidad = ? AND codigo = ?",
                (comunidad, codigo),
            )

    def listar_codigos_vistos(self, comunidad: str) -> list[str]:
        """Lista los códigos vistos de una comunidad, sin duplicados.

        Devuelve la unión de los códigos importados sin ficha (estado 'sin_ficha')
        y los procedentes de fichas ingeridas (cualquier otro estado), sin duplicados.

        Args:
            comunidad: Comunidad de la que se quieren los códigos vistos.

        Returns:
            Lista de códigos (texto de 12 dígitos) sin duplicados.
        """
        filas = self._conexion.execute(
            "SELECT DISTINCT codigo FROM ofertas WHERE comunidad = ?",
            (comunidad,),
        ).fetchall()
        return [fila[0] for fila in filas]
