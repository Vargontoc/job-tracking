# Job Emcan Tracking

<!-- sdd:start -->
<!-- Bloque generado por el agente docs. Se reescribe entero: escribe fuera de las marcas. -->

## Qué es

Job Emcan Tracking es una aplicación local y de uso personal para seguir las ofertas de empleo que el Portal de Empleo de Cantabria publica en difusión. Convierte el listado diario en una base propia, filtrable y con memoria: detecta qué ofertas son nuevas y cuáles se han cerrado, avisa por Telegram de lo nuevo que encaja con un perfil y lleva el seguimiento de las candidaturas. Sustituye la relectura manual del PDF de difusión y del buscador.

## Qué incluye y qué no

**Incluye:**

- La descarga diaria del buscador de ofertas de Cantabria, con el listado completo y la ficha de cada oferta nueva, y la del PDF de difusión como comprobación de integridad.
- El histórico de las ofertas nuevas y de las que se han cerrado.
- Un perfil de interés versionado, con el encaje de cada oferta puntuado por un modelo local.
- El aviso diario por Telegram con lo nuevo que encaja con el perfil.
- La ficha de cada oferta, con el texto completo y los datos de contacto.
- El seguimiento de las candidaturas, ocultando del listado las ofertas descartadas y las ya cerradas.

**No incluye:**

- Más comunidades que Cantabria.
- Exportar el listado a un fichero CSV.
- Estadísticas.
- Búsqueda por significado.
- Cualquier uso compartido, publicado o comercial.

## Con qué está hecho

- Python: el lenguaje en el que está escrito el proyecto.
- FastAPI: la base con la que se construyen los servicios web que usará la aplicación.
- SQLite: la base de datos, un único fichero donde se guardará el histórico, sin servidor que instalar.
- Ollama: un modelo que se ejecuta en el propio ordenador y que puntúa el encaje de cada oferta con el perfil.
- httpx y selectolax: para descargar y leer el buscador de ofertas del portal.
- pdfplumber: para leer el texto del PDF de difusión.
- Telegram: el canal por el que llegan los avisos.
- El programador de tareas del sistema: lanza la pasada diaria.

## Cómo está organizada

- La API: descarga el PDF de difusión de las comunidades configuradas, lee sus ofertas y las devuelve ya separadas por comunidad y por sector profesional. La acompaña un fichero de configuración con el mapa de comunidades, un contenedor que la levanta en el puerto 8000 y un archivo de definición de modelo local que hoy no se usa.
- La aplicación: la parte que todavía está por construir. Será la que muestre el listado filtrable, el perfil de interés, el aviso diario y el seguimiento de las candidaturas.

## Qué puede hacer hoy

Todavía no hay funcionalidades terminadas.

La parte que lee el PDF de difusión ya está construida y está pendiente de validación; en cuanto se valide, se describirá aquí con detalle.

## Documentación

- [Contrato de la API (OpenAPI)](docs/contracts/openapi/api-pdf-parser.yaml)
- [Muestra de texto del PDF de difusión](docs/contracts/pdf/ofertas_cantabria.txt)
- [Contrato HTML del buscador de Cantabria](docs/contracts/html/empleacantabria/README.md)
- [Mapa de comunidades](config/comunidades.yaml)
- [Documento de producto](docs/product/producto.md)
- [Plan de trabajo de la API](docs/sprints/api/api-pdf-parser.md)
- Especificación: [requisitos](specs/api-pdf-parser/requirements.md) · [diseño](specs/api-pdf-parser/design.md) · [tareas](specs/api-pdf-parser/tasks.md)

<!-- sdd:end -->
