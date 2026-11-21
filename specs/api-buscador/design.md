# Diseño: api-buscador

Estado: aprobado
Revisión: 2
Basado en: requirements@5
Verificación: correcta

## Resumen

Se añade a la API FastAPI existente un rastreador del buscador HTML de Emplea Cantabria: un scheduler interno dispara una pasada diaria a la hora configurada, recorre el listado paginado a 75 ofertas, pide la ficha solo de los códigos no vistos, extrae sus campos con `selectolax`, guarda los HTML de las fichas fallidas y devuelve un resultado JSON. Un endpoint manual y un endpoint de estado comparten con el scheduler el mismo mecanismo de exclusión mutua y el mismo fichero de códigos vistos.

## Supuestos sobre el sistema actual

- La API de `api-pdf-parser` vive en `source/api/` según `.sdd/architecture.md`; `api-buscador` convive en el mismo paquete/módulo `source/api/` respetando las convenciones de respuesta JSON, códigos de oferta como texto y fechas en formato `dd/mm/aaaa`.
- No existe un scheduler previo; hay que crear uno en proceso.
- El contrato HTML con muestras reducidas del buscador y de la ficha está en `docs/contracts/html/empleacantabria/`; los fixtures de `tests/fixtures/buscador/` se derivarán de él.
- `api-persistencia`, SQLite, Ollama y Telegram están fuera del alcance de esta feature.
- El portal de Emplea Cantabria publica el listado paginado con un tamaño configurable y una ficha por código de oferta, ambos sin autenticación.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que arranca/para el scheduler y expone los endpoints manual y de estado. | existente (se extiende) |
| config-buscador | Fichero de configuración con URL del listado y de la ficha, hora por defecto, User-Agent, delay, tamaño de página y rutas de estado. | nuevo |
| scheduler | Tarea en proceso que programa la pasada automática al inicio de la hora configurada y la cancela al apagar la API. | nuevo |
| run-coordinator | Mantiene el estado "pasada en curso" compartido entre scheduler y endpoint manual; inicia y finaliza una pasada. | nuevo |
| rate-limiter | Regula todas las peticiones salientes al portal para garantizar al menos 10 s entre peticiones consecutivas. | nuevo |
| state-store | Lee y escribe `data/seen_codes.json`, el único estado persistente de la feature. | nuevo |
| list-scraper | Recorre el listado paginado a 75 ofertas siguiendo la estructura real del contrato HTML: tabla `table.table` → `tbody.table-data` → filas con código en `a[href*="/ofertas-cantabria/-/oferta/"]`, total/rango en `small.search-results`, paginación en `ul.lfr-pagination-buttons` con `_..._delta=75` y `_..._cur=N`, y vacío mediante `.lfr-search-container.hide` y el mensaje `#..._dtosSearchContainerEmptyResultsMessage`. | nuevo |
| detail-parser | Descarga el HTML de una ficha y extrae número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto siguiendo el contrato HTML; `sector`, `nivel` y `contrato` se reservan en el modelo pero se devuelven vacíos. | nuevo |
| html-archive | Guarda el HTML original de las fichas cuyo parseo falla en `data/failed_htmls/<codigo>_<yyyy-mm-dd>.html`. | nuevo |
| archive-purger | Elimina los HTML fallidos con más de 7 días de antigüedad. | nuevo |
| response-assembler | Construye el JSON de resultado de la pasada con metadatos, errores globales, errores por oferta y ofertas nuevas. | nuevo |
| manual-trigger | Endpoint que dispara una pasada manual y acepta opcionalmente una lista de códigos históricos. | nuevo |
| status-endpoint | Endpoint que devuelve si hay pasada en curso, progreso y resumen de la última pasada finalizada. | nuevo |

## Flujo principal

1. Al arrancar `api-service`, carga `config-buscador`, lee `data/seen_codes.json` mediante `state-store` y arranca el `scheduler` con la hora configurada.
2. Cuando llega la hora configurada, el `scheduler` solicita a `run-coordinator` iniciar una pasada automática.
3. `run-coordinator` verifica que no haya otra pasada en curso, marca el inicio y carga la lista de códigos vistos desde `state-store`.
4. `list-scraper` solicita páginas del buscador a través del `rate-limiter` con tamaño 75 hasta cubrir el total de ofertas.
5. `list-scraper` entrega el conjunto de códigos del listado; se descartan los que ya estén en `state-store`.
6. Para cada código nuevo, `run-coordinator` pide a `detail-parser` la ficha, que transita por `rate-limiter`.
7. Si `detail-parser` extrae los campos correctamente, la oferta pasa a `response-assembler` y su código se anota para añadir a `state-store` al finalizar.
8. Si `detail-parser` falla, `html-archive` guarda el HTML recibido, se reintenta una sola vez tras esperar la pausa de cortesía, y solo si sigue fallando se registra el error por oferta.
9. Al terminar todas las fichas, `archive-purger` elimina los HTML fallidos con más de 7 días.
10. `state-store` persiste los nuevos códigos correctamente parseados.
11. `response-assembler` entrega el JSON final a `run-coordinator`, que lo conserva como último resultado y libera el flag "en curso".
12. El `scheduler` vuelve a esperar la siguiente hora configurada del día siguiente.

## Flujos alternativos y de fallo

### ALT-001 Portal no responde o el listado cambia de estructura

- **Condición:** El buscador devuelve error HTTP, no responde, el HTML no contiene el marcador esperado o una página intermedia falla.
- **Comportamiento:** `list-scraper` detiene el recorrido, informa del fallo global y no se marcan ofertas como nuevas. `response-assembler` devuelve el resultado con error global y lista de ofertas vacía.
- **Responsable:** list-scraper
- **Resultado:** JSON de resultado con error global; HTTP 200 de la API.
- **Cubre:** REQ-012

### ALT-002 Listado vacío

- **Condición:** El buscador devuelve una respuesta válida sin ofertas.
- **Comportamiento:** `list-scraper` detecta el total cero, no solicita fichas y `response-assembler` devuelve un resultado vacío.
- **Responsable:** list-scraper
- **Resultado:** JSON de resultado con total 0, sin errores y sin ofertas nuevas.
- **Cubre:** REQ-006, REQ-012

### ALT-003 Ficha fallida persistente

- **Condición:** Una ficha falla en la descarga o en el parseo, y vuelve a fallar tras el reintento.
- **Comportamiento:** `html-archive` guarda el HTML del intento que tuvo cuerpo. `response-assembler` registra el código como error por oferta y no se añade a `state-store`.
- **Responsable:** detail-parser
- **Resultado:** La oferta no se marca como vista; en la siguiente pasada se volverá a intentar si sigue en el listado.
- **Cubre:** REQ-009, REQ-010

### ALT-004 Solapamiento de pasadas

- **Condición:** El scheduler o el endpoint manual intentan iniciar una pasada mientras otra está en curso.
- **Comportamiento:** `run-coordinator` rechaza la segunda solicitud, registra la omisión y devuelve el estado "ya en curso".
- **Responsable:** run-coordinator
- **Resultado:** La pasada en curso continúa; cuando termina queda registrado que la ejecución programada o manual fue omitida.
- **Cubre:** REQ-003, REQ-014

### ALT-005 Configuración de hora inválida

- **Condición:** Se intenta configurar una lista de horas, minutos, fracciones de hora o una expresión cron completa.
- **Comportamiento:** `api-service` rechaza el valor y mantiene la hora anterior (o la por defecto 01:00 si es el primer arranque).
- **Responsable:** api-service
- **Resultado:** Error de validación visible sin cambiar la programación.
- **Cubre:** REQ-001

### ALT-006 Directorio de HTML fallidos no disponible

- **Condición:** `html-archive` no puede escribir en `data/failed_htmls/`.
- **Comportamiento:** Se registra el error de escritura junto al error de parseo, pero la pasada continúa con el resto de fichas.
- **Responsable:** html-archive
- **Resultado:** El error por oferta indica que no se pudo guardar el HTML; el código no se marca como visto.
- **Cubre:** REQ-010

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| Cliente | api-service | Petición de pasada manual (opcional lista de códigos históricos) | HTTP (OpenAPI) |
| Cliente | api-service | Petición de estado de la última pasada | HTTP (OpenAPI) |
| api-service | config-buscador | Horario, URLs, User-Agent, delay, tamaño de página, rutas | lectura de fichero de configuración |
| api-service | scheduler | Hora configurada y acción a ejecutar | llamada interna |
| scheduler | run-coordinator | Solicitud de inicio de pasada automática | llamada interna |
| manual-trigger | run-coordinator | Solicitud de inicio de pasada manual (con lista histórica opcional) | llamada interna |
| run-coordinator | state-store | Lista de códigos vistos para filtrar y para persistir | lectura/escritura de fichero JSON |
| run-coordinator | list-scraper | Petición de recorrido del listado paginado | llamada interna |
| list-scraper | rate-limiter | Permiso para realizar petición HTTP al portal | llamada interna |
| detail-parser | rate-limiter | Permiso para realizar petición HTTP al portal | llamada interna |
| rate-limiter | Portal Emplea Cantabria | Peticiones GET al listado y a fichas, con User-Agent identificable | HTTPS |
| list-scraper | run-coordinator | Conjunto de códigos del listado y error global si lo hay | llamada interna |
| run-coordinator | detail-parser | Código de oferta nueva a procesar | llamada interna |
| detail-parser | html-archive | HTML recibido cuando el parseo falla | llamada interna |
| detail-parser | response-assembler | Oferta parseada o error por oferta | llamada interna |
| run-coordinator | archive-purger | Orden de limpieza diaria de HTML fallidos | llamada interna |
| run-coordinator | response-assembler | Errores y ofertas para construir el resultado | llamada interna |
| response-assembler | run-coordinator | JSON final de la pasada | llamada interna |
| run-coordinator | status-endpoint | Estado "en curso", progreso y último resultado | lectura de memoria compartida |

## Contrato de API

### Endpoint de pasada manual

- **Método y ruta propuestos:** `POST /buscador/run` (o equivalente bajo el prefijo adoptado por `api-pdf-parser`).
- **Petición:** cuerpo JSON opcional con una lista de códigos históricos (`historical_codes`). Si no se envía, se usa `data/seen_codes.json`.
- **Respuesta exitosa (HTTP 200):** JSON con metadatos de la ejecución (timestamp, comunidad, total del listado, ofertas nuevas, errores global y por oferta) y la lista de ofertas parseadas.
- **Respuesta de solapamiento (HTTP 200):** JSON que indica que ya existe una pasada en curso, sin iniciar una nueva.

### Endpoint de estado

- **Método y ruta propuestos:** `GET /buscador/status`.
- **Petición:** sin cuerpo.
- **Respuesta exitosa (HTTP 200):** JSON con `in_progress` (booleano), hora de inicio de la pasada en curso, progreso disponible (página actual, códigos procesados) y resumen de la última pasada finalizada (timestamp, total, nuevas, errores).

## Modelo de datos lógico

- **ConfigBuscador:** hora de pasada, URL del listado, URL de la ficha, User-Agent, delay entre peticiones, tamaño de página, rutas de `seen_codes.json` y `failed_htmls/`, días de purga. Relación: es leída por `api-service` y usada por `scheduler`, `rate-limiter`, `list-scraper` y `detail-parser`.
- **CodigoVisto:** código de oferta cuya ficha se parseó correctamente. Relación: se almacena en `state-store` y se usa para filtrar novedades.
- **ResultadoPasada:** timestamp, comunidad, total de ofertas en listado, errores globales, errores por oferta y ofertas nuevas. Relación: se genera por `response-assembler` y se expone por los endpoints.
- **OfertaBuscador:** número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre, contacto y comunidad/provincia; `sector`, `nivel` y `contrato` se mantienen en el modelo pero siempre se devuelven vacíos. Relación: es producida por `detail-parser` y devuelta en el `ResultadoPasada`.
- **HtmlFallido:** HTML original de una ficha cuyo parseo falló, con nombre `<codigo>_<yyyy-mm-dd>.html`. Relación: es escrito por `html-archive` y purgado por `archive-purger`.

## Decisiones

### DEC-001 Scheduler en proceso

- **Decisión:** La programación diaria se implementa con un scheduler dentro del proceso de la API, no con una tarea externa del sistema operativo.
- **Alternativas descartadas:** Cron del sistema (contradice el requisito de programación interna y dificulta compartir el estado "en curso" con los endpoints).
- **Cubre:** REQ-001, REQ-002, REQ-003

### DEC-002 Fichero JSON como único estado

- **Decisión:** Los códigos vistos se guardan en `data/seen_codes.json` y no se consulta ni se escribe SQLite ni `api-persistencia`.
- **Alternativas descartadas:** Base de datos SQLite (requisitos la excluyen) y consulta a `api-persistencia` (fuera de alcance).
- **Cubre:** REQ-004, REQ-005, REQ-013

### DEC-003 Rate limiter compartido global

- **Decisión:** Un único componente regula el intervalo mínimo entre todas las peticiones al portal (listado y fichas), compartido entre pasada automática, manual y reintentos.
- **Alternativas descartadas:** Limitadores separados por componente (podrían solaparse y violar los 10 s) y límite solo entre fichas (omitiría las peticiones del listado).
- **Cubre:** NFR-002

### DEC-004 Parser HTML con selectolax

- **Decisión:** Tanto el listado como la ficha se parsean con `selectolax`, siguiendo la línea tecnológica de `.sdd/project.md`.
- **Alternativas descartadas:** BeautifulSoup (más lento y no aporta valor para HTML fijo) y modelos de lenguaje (excluidos por los requisitos y por PDEC-006).
- **Cubre:** REQ-006, REQ-008

### DEC-005 HTML de fichas fallidas con fecha ISO en el nombre

- **Decisión:** El nombre del fichero es `<codigo_oferta>_<yyyy-mm-dd>.html` dentro de `data/failed_htmls/`.
- **Alternativas descartadas:** Hash aleatorio (impide localizar rápidamente un código) y carpeta por fecha (más profundidad sin beneficio para la purga).
- **Cubre:** REQ-010, REQ-011

### DEC-006 Ficha solo de códigos no vistos

- **Decisión:** Se piden fichas únicamente de los códigos que no están en `data/seen_codes.json` (o en la lista histórica manual), de acuerdo con PDEC-016.
- **Alternativas descartadas:** Descargar todas las fichas cada día (contradice PDEC-016 y ralentiza innecesariamente el rastreo).
- **Cubre:** REQ-005, REQ-007, NFR-005

### DEC-007 Un único reintento por ficha en la misma pasada

- **Decisión:** Si una ficha falla, se reintenta una sola vez dentro de la misma pasada, respetando siempre la pausa de cortesía.
- **Alternativas descartadas:** Reintentos múltiples o backoff exponencial (no definidos en los requisitos y aumentarían el tiempo de pasada) y reintentar en pasadas posteriores sin política (ya ocurre de hecho al no marcar el código como visto).
- **Cubre:** REQ-009

### DEC-008 Endpoint manual con lista histórica opcional

- **Decisión:** El endpoint manual acepta un cuerpo opcional con códigos históricos; si no llega, usa `data/seen_codes.json`.
- **Alternativas descartadas:** Endpoint manual que siempre use el fichero (limitaría pruebas) y endpoint que guarde la lista manual como nuevo estado (podría corromper el fichero real).
- **Cubre:** REQ-014

### DEC-009 Campos sin fuente se devuelven vacíos

- **Decisión:** `sector`, `nivel` y `contrato` se mantienen en `OfertaBuscador` y en la respuesta JSON, pero se devuelven como cadena vacía porque la ficha del portal no los publica y no hay otra fuente en el alcance.
- **Alternativas descartadas:** Omitirlos del modelo (rompería el contrato y el histórico) e inferirlos del texto libre (inventaría datos).
- **Cubre:** REQ-008

## Riesgos

- **Cambio en el HTML del buscador o de la ficha:** Si el portal modifica sus plantillas, `selectolax` dejará de extraer los campos. Mitigación: tests que usan las muestras reales de `docs/contracts/html/empleacantabria/` como contrato de referencia y guardado de HTML fallidos para diagnóstico rápido.
- **Acumulación de HTML fallidos:** Aunque hay purga a 7 días, un fallo masivo podría llenar el directorio. Mitigación: la purga se ejecuta al final de cada pasada, no solo una vez al día.
- **Solapamiento no detectado en reinicios:** Si el proceso se reinicia durante una pasada, el flag "en curso" se pierde. Mitigación: el flag vive solo en memoria; tras un reinicio la API arranca limpia y el scheduler espera la siguiente hora.
- **Bloqueo por cortesía de 10 s con muchas ofertas nuevas:** Una pasada con muchas fichas nuevas puede durar decenas de minutos. Mitigación: es el comportamiento esperado y acordado; el scheduler solo lanza una pasada al día.
- **Discrepancia con la muestra de PDF:** Si el buscador y el PDF divergen, `api-buscador` no tiene lógica de integridad; se delega a `api-integridad` en el futuro.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | api-service, config-buscador, scheduler | DEC-001 |
| REQ-002 | scheduler | DEC-001 |
| REQ-003 | run-coordinator, scheduler, manual-trigger | DEC-001 |
| REQ-004 | state-store | DEC-002 |
| REQ-005 | state-store, list-scraper, manual-trigger | DEC-002, DEC-008 |
| REQ-006 | list-scraper, config-buscador | DEC-004 |
| REQ-007 | list-scraper, state-store | DEC-006 |
| REQ-008 | detail-parser | DEC-004, DEC-009 |
| REQ-009 | detail-parser, rate-limiter | DEC-003, DEC-007 |
| REQ-010 | detail-parser, html-archive | DEC-005 |
| REQ-011 | archive-purger | DEC-005 |
| REQ-012 | list-scraper, response-assembler | - |
| REQ-013 | response-assembler | DEC-002 |
| REQ-014 | manual-trigger, run-coordinator | DEC-001, DEC-008 |
| REQ-015 | status-endpoint, run-coordinator | - |
| NFR-001 | config-buscador, rate-limiter | - |
| NFR-002 | rate-limiter | DEC-003 |
| NFR-003 | api-service | - |
| NFR-004 | list-scraper, config-buscador | - |
| NFR-005 | scheduler, config-buscador | DEC-001, DEC-006 |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-buscador.yaml` (nuevo) | Define el endpoint de pasada manual (`/buscador/run`) y el endpoint de estado (`/buscador/status`), incluyendo la respuesta JSON de resultado y el modelo de error por oferta. |
| Configuración | `config/buscador.yaml` (nuevo) | Configuración del buscador: URL de listado, URL de ficha, hora, User-Agent, delay, tamaño de página y rutas de datos. |
| Configuración | `config/comunidades.yaml` (modificación sugerida) | Añadir al mapa de Cantabria las URLs del buscador HTML y de la ficha, si se prefiere un único fichero de configuración por comunidad. |

## Cambios sugeridos al mapa

- `+ Módulo: api-buscador | source/api/buscador | Rastreador del buscador HTML de Cantabria | API`
- `+ Módulo: config-buscador | config/buscador.yaml | Configuración del buscador y horario | -`
- `+ Módulo: scheduler | source/api/buscador/scheduler | Dispara la pasada automática diaria | api-buscador`
- `+ Módulo: run-coordinator | source/api/buscador/coordinator | Exclusión mutua y ciclo de una pasada | api-buscador`
- `+ Módulo: rate-limiter | source/api/buscador/rate_limiter | Pausa de 10 s entre peticiones al portal | api-buscador`
- `+ Módulo: state-store | source/api/buscador/state | Lectura/escritura de seen_codes.json | api-buscador`
- `+ Módulo: list-scraper | source/api/buscador/scraper | Recorrido paginado del listado | api-buscador, rate-limiter`
- `+ Módulo: detail-parser | source/api/buscador/parser | Descarga y parseo de fichas con selectolax | api-buscador, rate-limiter`
- `+ Módulo: html-archive | source/api/buscador/archive | Guarda HTML de fichas fallidas | api-buscador`
- `+ Módulo: archive-purger | source/api/buscador/purger | Elimina HTML fallidos de más de 7 días | api-buscador`
- `+ Módulo: response-assembler | source/api/buscador/assembler | Construye el JSON de resultado de pasada | api-buscador`
- `+ Contrato: openapi | docs/contracts/openapi/api-buscador.yaml | cliente -> api-buscador`
- `+ Convención: rastreo-user-agent: identifica el proyecto y proporciona medio de contacto`
- `+ Convención: rastreo-delay: 10 s entre peticiones consecutivas al portal`
- `+ Convención: rastreo-page-size: 75 ofertas por página`
- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs y rastreo del buscador | -`

## Estrategia de tests

- **Tests del listado con contrato real:** Usar como referencia las muestras `docs/contracts/html/empleacantabria/listado_pagina_1.html`, `listado_pagina_2.html` y `listado_vacio.html`; copiarlas o referenciarlas en `tests/fixtures/buscador/` para validar que `list-scraper` extrae el total, el rango, los códigos de 12 dígitos como texto y la condición de vacío.
- **Tests de ficha con contrato real:** Usar como referencia `docs/contracts/html/empleacantabria/ficha_062026003633.html`; copiarla o referenciarla en `tests/fixtures/buscador/` y variarla para validar que `detail-parser` extrae los inputs por sufijo de `id`, el texto libre y el contacto, y que `sector`, `nivel` y `contrato` quedan vacíos.
- **Tests del rate-limiter:** Medir los timestamps de las peticiones salientes y comprobar que nunca hay menos de 10 s entre dos consecutivas, incluyendo listado, fichas y reintentos.
- **Tests del state-store:** Verificar lectura/escritura de `data/seen_codes.json`, creación vacía si no existe y no añadir códigos de fichas fallidas.
- **Tests del scheduler:** Simular el paso del tiempo para comprobar que se dispara exactamente una pasada por día a la hora configurada y que se omite si la anterior sigue en curso.
- **Tests de solapamiento:** Invocar el endpoint manual mientras una pasada automática simulada está en curso y comprobar que se rechaza.
- **Tests del endpoint de estado:** Comprobar que refleja "en curso" con progreso y el resumen de la última pasada finalizada.
- **Tests de purga:** Crear HTML fallidos con fechas antiguas y comprobar que se eliminan los de más de 7 días mientras se conservan los recientes.
- **Tests de contrato:** Validar el fichero OpenAPI contra las rutas de la API con `TestClient`.

## Avisos

- Las muestras HTML reducidas del buscador y de la ficha en `docs/contracts/html/empleacantabria/` son el contrato de referencia para `list-scraper` y `detail-parser`; los tests deben usarlas directamente o copiarlas a `tests/fixtures/buscador/`.
- `.sdd/architecture.md` apunta a `source/api/`, mientras que el diseño aprobado de `api-pdf-parser` usaba `src/api_pdf_parser/`. Se asume que `source/api/` es la convención vigente y se propone actualizar la descripción del módulo API en el mapa para incluir también el buscador.
- La lógica de integridad entre buscador y PDF no forma parte de esta feature; queda reservada para `api-integridad` según `docs/product/producto.md`.
