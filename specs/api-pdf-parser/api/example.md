# Ejemplos de uso: api-service

## `api-service`

El paquete `source.api` es el punto de partida del servicio API. Sus entidades
de dominio representan una comunidad configurada, el sector y la oferta
extraída, además del resultado de procesar una comunidad.

```python
from source.api.models import (
    ComunidadConfigurada,
    Oferta,
    ResultadoPorComunidad,
    SectorProfesional,
)


comunidad = ComunidadConfigurada(
    identificador="cantabria",
    url_pdf="https://ejemplo.test/ofertas.pdf",
)
sector = SectorProfesional(nombre="Hostelería")
oferta = Oferta(
    denominacion="Cocinero/a",
    sector_profesional=sector,
    comunidad=comunidad.identificador,
)
resultado = ResultadoPorComunidad(
    comunidad=comunidad.identificador,
    estado="ok",
    ofertas=[oferta],
)
```

## `config-map`

El componente carga el mapa YAML de comunidades y devuelve entidades
`ComunidadConfigurada`.

```python
from source.api.config import cargar_comunidades


for comunidad in cargar_comunidades():
    print(comunidad.identificador, comunidad.url_pdf)
```

## `pdf-parser`

El parser recibe los bytes de un PDF y devuelve el texto de todas las páginas
sin los pies de página de difusión.

```python
from source.api.parser import extraer_ofertas_desde_pdf, extraer_texto_pdf, segmentar_ofertas


with open("ofertas.pdf", "rb") as fichero:
    texto = extraer_texto_pdf(fichero.read())

print(texto)

for oferta in segmentar_ofertas(texto):
    print(oferta.sector_profesional, oferta.lineas[0])

ofertas = extraer_ofertas_desde_pdf(
    open("ofertas.pdf", "rb").read(),
    comunidad="cantabria",
)
for oferta in ofertas:
    print(oferta.denominacion, oferta.municipio)
```

## `pdf-downloader`

El downloader descarga el PDF de una comunidad con un timeout explícito y
devuelve los bytes o un error controlado.

```python
from source.api.downloader import ErrorDescarga, descargar_pdf


resultado = descargar_pdf("https://ejemplo.test/ofertas.pdf")
if isinstance(resultado, ErrorDescarga):
    print(resultado.mensaje)
else:
    print(resultado[:4])  # b"%PDF"
```

## `response-assembler`

El assembler reúne los resultados por comunidad y genera los metadatos de la
respuesta.

```python
from source.api.assembler import ensamblar_respuesta
from source.api.models import ResultadoPorComunidad


respuesta = ensamblar_respuesta(
    [ResultadoPorComunidad(comunidad="cantabria", estado="ok")]
)
print(respuesta["metadatos"]["total_ofertas"])

respuesta_error = ensamblar_respuesta(
    [
        ResultadoPorComunidad(
            comunidad="asturias",
            estado="error",
            mensaje_error="Error de descarga: HTTP 503.",
        )
    ]
)
print(respuesta_error["resultados"][0]["error"])
```

### `GET /parse`

La aplicación expone el endpoint sin parámetros ni cuerpo de petición.

```python
import httpx


respuesta = httpx.get("http://127.0.0.1:8000/parse")
respuesta.raise_for_status()
print(respuesta.json()["resultados"])
```

## `model-file`

El `Modelfile` es una plantilla inerte para una futura integración local con
Ollama. La API actual no lo carga ni invoca ningún modelo.

```python
from pathlib import Path


modelfile = Path("Modelfile")
referencia = modelfile.read_text(encoding="utf-8")
print(referencia.splitlines()[4])  # Modelo base documentado.
```

## `docker-compose`

El contenedor único de la API se construye y se publica en el puerto local
8000 sin volúmenes ni servicios auxiliares.

```python
import subprocess


subprocess.run(
    ["docker", "compose", "up", "--build"],
    check=True,
)
```
