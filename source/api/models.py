"""Entidades de dominio de la API, sin persistencia."""

from dataclasses import dataclass, field


@dataclass
class ComunidadConfigurada:
    """Comunidad incluida en el mapa de PDFs de difusión."""

    identificador: str = ""
    url_pdf: str = ""


@dataclass
class SectorProfesional:
    """Sector profesional tal como aparece en el PDF."""

    nombre: str = ""


@dataclass
class Oferta:
    """Oferta extraída de un PDF de difusión."""

    denominacion: str = ""
    municipio: str = ""
    codigo_oferta: str = ""
    fecha_publicacion: str = ""
    oficina: str = ""
    descripcion: str = ""
    sector_profesional: SectorProfesional = field(default_factory=SectorProfesional)
    comunidad: str = ""


@dataclass
class ResultadoPorComunidad:
    """Resultado del procesamiento de una comunidad."""

    comunidad: str = ""
    estado: str = ""
    ofertas: list[Oferta] = field(default_factory=list)
    mensaje_error: str = ""
