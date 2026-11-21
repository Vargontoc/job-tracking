# Requisitos: api-pdf-parser

Estado: aprobado
Revisión: 2

## Contexto

La aplicación necesita una API que, de forma automática, recorra el mapa interno de comunidades configuradas (caso inicial: Cantabria), descargue el PDF de difusión de cada una, extraiga el listado de ofertas y lo devuelva directamente en la respuesta. En esta feature también se entregan un `Modelfile` de referencia para Ollama y un `docker-compose.yaml` para levantar la API, sin persistencia en base de datos ni inferencia con modelos locales.

## Fuera de alcance

- Integración con SQLite u otra base de datos.
- Puntuación, embeddings o procesamiento con modelos locales (Ollama). El `Modelfile` se entrega solo como definición de referencia para uso futuro; no se invoca ni se ejecuta inferencia en esta feature.
- Envío de notificaciones (Telegram).
- Descarga o parseo del buscador HTML.
- Servicio Ollama en `docker-compose.yaml`.
- Recepción de URL arbitraria o subida directa de PDF por parte del cliente.

## Requisitos funcionales

### REQ-001 Leer mapa interno de comunidades configuradas

- **Requisito:** Cuando se inicie el proceso de parseo, el sistema deberá leer el mapa interno de comunidades configuradas con sus URLs de PDF de difusión.
- **Criterios de aceptación:**
  - Dado un mapa interno con al menos una comunidad (por ejemplo, Cantabria asociada a una URL), cuando se solicita el parseo, entonces el sistema lee todas las comunidades configuradas.

### REQ-002 Descargar PDF de cada comunidad configurada

- **Requisito:** Para cada comunidad configurada, el sistema deberá descargar el PDF de difusión desde la URL asociada en el mapa interno.
- **Criterios de aceptación:**
  - Dado un mapa interno con una comunidad y una URL accesible, cuando se solicita el parseo, entonces el sistema descarga el PDF correspondiente.
  - Dado un mapa interno con varias comunidades, cuando se solicita el parseo, entonces el sistema intenta descargar el PDF de cada una.

### REQ-003 Extraer listado de ofertas del PDF

- **Requisito:** El sistema deberá extraer del PDF de difusión el listado completo de ofertas publicadas, organizadas por sector profesional.
- **Criterios de aceptación:**
  - Dado un PDF de difusión con ofertas agrupadas bajo secciones "Sector Profesional", cuando se parsea, entonces la respuesta incluye todas las ofertas identificadas y el sector profesional al que pertenece cada una.

### REQ-004 Extraer campos de cada oferta

- **Requisito:** Para cada oferta extraída, el sistema deberá identificar al menos la denominación del puesto, el municipio, el código de oferta, la fecha de publicación, la oficina de empleo y el texto descriptivo completo.
- **Criterios de aceptación:**
  - Dado un PDF cuyas ofertas incluyen denominación del puesto, municipio, código de oferta, fecha, oficina y descripción, cuando se parsea, entonces cada oferta de la respuesta contiene esos campos cuando están presentes en el documento.
  - Dado que el documento no contiene un campo separado "empresa", cuando se parsea, entonces el sistema no inventa dicho campo y la entidad contratante queda reflejada en el texto descriptivo.

### REQ-005 Asociar cada oferta a su comunidad

- **Requisito:** El sistema deberá asociar cada oferta extraída a la comunidad de la que procede.
- **Criterios de aceptación:**
  - Dado un proceso con varias comunidades configuradas, cuando se devuelve el resultado, entonces cada oferta incluye un identificador de comunidad que permite distinguir su origen.

### REQ-006 Devolver resultado directamente por la API

- **Requisito:** El sistema deberá devolver el listado de ofertas parseadas directamente en la respuesta de la API, sin almacenarlo en base de datos.
- **Criterios de aceptación:**
  - Dada una petición de parseo exitosa, cuando la API responde, entonces el cuerpo de la respuesta contiene el listado de ofertas con su comunidad de origen y no se registra persistencia en base de datos.

### REQ-007 Manejar fallo de descarga de una comunidad sin bloquear el resto

- **Requisito:** Si la descarga del PDF falla para una comunidad configurada, el sistema deberá continuar con el resto de comunidades e informar del fallo en el resultado.
- **Criterios de aceptación:**
  - Dado un mapa con varias comunidades donde una URL es inaccesible, cuando se solicita el parseo, entonces el sistema procesa las comunidades accesibles e incluye una indicación del error para la comunidad fallida.

### REQ-008 Manejar PDF sin ofertas o no parseable

- **Requisito:** Si el PDF descargado no contiene ofertas o no se puede parsear, el sistema deberá devolver una respuesta que indique que no se encontraron ofertas para esa comunidad.
- **Criterios de aceptación:**
  - Dado un PDF sin ofertas o con un formato no reconocido, cuando se parsea, entonces la respuesta para esa comunidad indica claramente que no se encontraron ofertas, sin generar una excepción no controlada.

### REQ-009 Entregar Modelfile de referencia para Ollama

- **Requisito:** El sistema deberá incluir un fichero `Modelfile` que defina un modelo para Ollama, sin que la API lo invoque ni realice inferencia.
- **Criterios de aceptación:**
  - Dado el repositorio de la feature, cuando se revisa su contenido, entonces existe un fichero `Modelfile` con la definición del modelo.
  - Dado el código de la API, cuando se revisa, entonces no contiene llamadas a Ollama ni ejecución de inferencia.

### REQ-010 Entregar docker-compose.yaml para la API

- **Requisito:** El sistema deberá incluir un fichero `docker-compose.yaml` que construya y levante el contenedor de la API, exponiéndola en el puerto `8000` del host.
- **Criterios de aceptación:**
  - Dado el repositorio con el `docker-compose.yaml`, cuando se ejecuta `docker-compose up`, entonces el contenedor de la API se levanta y responde en `http://localhost:8000`.
  - Dado el contenedor levantado, cuando se consulta el endpoint de parseo, entonces la API devuelve el resultado esperado según los requisitos anteriores.

## Requisitos no funcionales

Ninguno.

## Supuestos

### SUP-001 Sin autenticación en la API

- **Tipo:** contextual
- **Descripción:** La API de esta feature no requiere autenticación, ya que la aplicación es de uso local y personal.
- **Impacto:** REQ-006.
- **Estado:** pendiente

### SUP-002 Mapa interno comunidad => URL

- **Tipo:** decisional
- **Descripción:** El PDF se obtiene desde un mapa interno de comunidad/provincia => URL de PDF de difusión; el cliente no envía URL ni sube ficheros. El caso inicial es Cantabria y el diseño es escalable a futuras comunidades.
- **Impacto:** REQ-001, REQ-002, REQ-005, REQ-007.
- **Estado:** validado

### SUP-003 Estructura del PDF de difusión

- **Tipo:** decisional
- **Descripción:** El PDF de difusión del Portal de Empleo de Cantabria está organizado por sectores profesionales y cada oferta incluye denominación del puesto, municipio, código de oferta, fecha de publicación/inscripción, oficina de empleo y descripción textual corrida. No incluye un campo separado "empresa". Evidencia: `docs/contracts/ofertas_cantabria.txt`.
- **Impacto:** REQ-003, REQ-004, REQ-008.
- **Estado:** validado

## Preguntas abiertas

Ninguna.
