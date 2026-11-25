"""Normalización de texto del listado insensible a mayúsculas y tildes.

Normaliza cadenas con ``lower()`` y descomposición Unicode NFD sin diacríticos,
de modo que el término buscado y los campos ``ocupacion``, ``municipio`` y
``texto_libre`` se comparen en la misma forma normalizada.
"""

from __future__ import annotations

import unicodedata


def normalizar(texto: str | None) -> str:
    """Devuelve el texto en minúsculas y sin diacríticos.

    Args:
        texto: Cadena a normalizar. Un valor vacío o ``None`` (campo purgado o
            no informado) devuelve la cadena vacía.

    Returns:
        El texto en minúsculas, descompuesto en NFD y sin caracteres
        combinantes, de modo que ``"Técnico"`` y ``"tecnico"`` coinciden.
    """
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(
        caracter for caracter in descompuesto if not unicodedata.combining(caracter)
    )


def contiene(campo: str | None, termino: str | None) -> bool:
    """Indica si el campo contiene el término, sin distinguir tildes.

    La comparación es parcial: basta con que el término normalizado aparezca en
    el campo normalizado.

    Args:
        campo: Campo donde buscar (``ocupacion``, ``municipio`` o ``texto_libre``).
        termino: Término buscado.

    Returns:
        ``True`` si hay coincidencia. Un campo o un término vacío no aporta
        coincidencias, porque un campo purgado no tiene valor que comparar y un
        término vacío no filtra.
    """
    campo_normalizado = normalizar(campo)
    termino_normalizado = normalizar(termino)
    if not campo_normalizado or not termino_normalizado:
        return False
    return termino_normalizado in campo_normalizado


def coincide(campo: str | None, valor: str | None) -> bool:
    """Indica si el campo es igual al valor, sin distinguir tildes.

    La comparación es por igualdad de las cadenas normalizadas, que es la regla
    del filtro de municipio. Un campo vacío no coincide con nada.

    Args:
        campo: Valor almacenado (por ejemplo, el municipio de la oferta).
        valor: Valor buscado (por ejemplo, el municipio del filtro).

    Returns:
        ``True`` si ambas cadenas normalizadas son iguales.
    """
    campo_normalizado = normalizar(campo)
    if not campo_normalizado:
        return False
    return campo_normalizado == normalizar(valor)
