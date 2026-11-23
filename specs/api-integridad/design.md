# Diseño: api-integridad

Estado: aprobado
Revisión: 3
Basado en: requirements@2
Verificación: correcta

## Resumen

`api-integridad` añade al módulo `API` una tarea diaria que descarga el PDF oficial de difusión por comunidad, conserva el último mes en el sistema de archivos, compara el recuento de ofertas extraídas con el `total_listado` de `api-buscador` y emite un veredicto informativo (`concordante`, `divergente` o `fallido`). El estado del día (veredicto, ejecuciones y avisos) vive principalmente en ficheros `<aaaa-mm-dd>.meta.json` junto a cada PDF, sin añadir un tercer fichero SQLite. Los componentes son detalle interno bajo `source/api/integridad/`; no se modifican `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`.

## Supuestos sobre el sistema actual

- La API FastAPI vive en `source/api/` y expone `GET /buscador/status` en el mismo proceso, con el último resultado solo en memoria (`source/api/buscador/coordinator.py`).
- `api-pdf-parser` (`source/api/downloader.py`, `source/api/parser.py`, `source/api/assembler.py`) puede ser invocado en proceso para descargar y parsear un PDF de difusión; devuelve una lista de ofertas por comunidad o un error controlado.
- El buscador publica en `ultima_pasada.total_listado` el recuento entero del listado; no expone la lista de códigos.
- `.sdd/project.md` declara SQLite (un solo fichero, WAL) como base de datos del producto, referido a la base de ofertas de `api-persistencia`.
- El módulo `API` ya alberga las tareas programadas del buscador, ingesta, purga e histórico; `api-integridad` convive en el mismo proceso sin modificarlas.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| integridad-task | Tarea programada diaria que orquesta la descarga, parseo, comparación, veredicto, avisos y purga para cada comunidad. | nuevo |
| config-integridad | Carga y validación de `config/integridad.yaml`: hora, zona, retención, tolerancias, umbral de cordura, margen de catch-up, rutas, comunidades y URL del buscador. | nuevo |
| pdf-store | Gestión del árbol `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf`, escritura atómica, cálculo de hash y lectura/escritura de `<aaaa-mm-dd>.meta.json`. | nuevo |
| downloader-adapter | Adaptador sobre `source/api/downloader.py` que descarga el PDF de una comunidad y normaliza el resultado para `pdf-store`. | nuevo |
| parser-adapter | Adaptador sobre `source/api/parser.py` que extrae ofertas del PDF descargado y devuelve el recuento o el error de parseo. | nuevo |
| buscador-status-adapter | Cliente HTTP de `GET /buscador/status` que obtiene `ultima_pasada.total_listado`, `error_global` y los errores por oferta. | nuevo |
| comparador-veredicto | Compara recuento PDF vs `total_listado`, aplica tolerancia absoluta/relativa y umbral de cordura, y emite el veredicto. | nuevo |
| pdf-purger | Elimina PDFs y metadatos con más días de los configurados, nunca el del día en curso. | nuevo |
| avisos-store | Registra avisos consultables de divergencia o fallo como entradas en el `.meta.json` del día y en un índice mensual de ejecuciones. | nuevo |
| integridad-api | Endpoints de consulta del último veredicto, ejecuciones del último mes y PDFs conservados. | nuevo |

## Flujo principal

1. Al arrancar `api-service`, `config-integridad` carga `config/integridad.yaml`; si falla, se registra el error y la feature no arranca, sin bloquear el resto de la API.
2. `integridad-task` se registra como tarea programada propia en el mismo proceso FastAPI, a la hora configurada y en la zona horaria configurada. Al arrancar, aplica la lógica de catch-up con el margen configurado (`margen_catchup`, por defecto 60 minutos):
   - Si la hora aún no ha llegado, espera a la ejecución programada normal.
   - Si se arranca dentro de la ventana entre `hora` y `hora + margen` y no existe `.meta.json` de hoy, programa una ejecución única para `hora + margen`; si al llegar ese instante sigue sin metadatos de hoy, ejecuta la comprobación del día.
   - Si se arranca después de `hora + margen` y no existe `.meta.json` de hoy, ejecuta la comprobación del día inmediatamente.
   - Si ya existe `.meta.json` de hoy (éxito o fallo), no ejecuta nada.
   - Nunca se procesan días anteriores.
3. Cuando llega la hora (o durante la recuperación de arranque), `integridad-task` determina el día actual según la zona horaria y, para cada comunidad configurada, consulta `pdf-store`.
4. Si ya existe un `.meta.json` válido para esa comunidad y fecha (estado `ok` o `fallido`), `integridad-task` no vuelve a descargar ni parsear (idempotencia diaria).
5. Si no existe, `integridad-task` pide a `downloader-adapter` el PDF de la comunidad.
6. Si la descarga falla, `pdf-store` escribe un `.meta.json` con estado `fallido` y el error; no se conserva PDF.
7. Si la descarga tiene éxito, `pdf-store` escribe el PDF de forma atómica (fichero temporal + rename) y calcula su hash.
8. `parser-adapter` extrae las ofertas del PDF y devuelve el recuento; si el parseo falla, `pdf-store` conserva el PDF pero marca el `.meta.json` con veredicto `fallido` y el error.
9. Si el parseo tiene éxito, `buscador-status-adapter` consulta `GET /buscador/status` y obtiene `ultima_pasada.total_listado`.
10. `comparador-veredicto` compara ambos recuentos, aplica la tolerancia más permisiva (absoluta o relativa) y el umbral de cordura, y emite `concordante` o `divergente`.
11. `pdf-store` completa el `.meta.json` con hash, recuentos, diferencia, umbrales aplicados, veredicto y timestamp.
12. Si el veredicto es `divergente` o `fallido`, `avisos-store` registra un aviso consultable con fecha, comunidad, recuentos, umbrales y motivo.
13. Al finalizar todas las comunidades, `integridad-task` registra la ejecución global (timestamp, resultado, errores por comunidad y veredicto agregado) en el índice de ejecuciones.
14. `pdf-purger` elimina los PDFs y metadatos anteriores al período de retención configurado, excepto el del día en curso.
15. Los endpoints de `integridad-api` leen los `.meta.json` y el índice de ejecuciones para responder consultas.

## Flujos alternativos y de fallo

### ALT-001 Hoy ya existe una descarga válida

- **Condición:** Para la comunidad y fecha actual ya existe un `.meta.json` con estado `ok`.
- **Comportamiento:** `integridad-task` omite la descarga, el parseo y la comparación para esa comunidad.
- **Responsable:** integridad-task
- **Resultado:** No se genera un segundo veredicto para esa comunidad y día.
- **Cubre:** REQ-001, REQ-005, NFR-003

### ALT-002 Hoy ya existe una ejecución previa fallida

- **Condición:** Para la comunidad y fecha actual existe un `.meta.json` con estado `fallido`.
- **Comportamiento:** `integridad-task` considera que ya se consumió la ejecución diaria de esa comunidad y no reintenta; el veredicto `fallido` permanece hasta el día siguiente.
- **Responsable:** integridad-task
- **Resultado:** Máximo una ejecución por día y comunidad, incluso si falla.
- **Cubre:** REQ-001, NFR-003

### ALT-003 Descarga del PDF fallida

- **Condición:** `downloader-adapter` devuelve `ErrorDescarga` (HTTP error, timeout o error de conexión).
- **Comportamiento:** `pdf-store` escribe un `.meta.json` con estado `fallido`, el mensaje de error y timestamp; no guarda PDF.
- **Responsable:** downloader-adapter
- **Resultado:** Veredicto `fallido` para esa comunidad; la ejecución global refleja el error parcial.
- **Cubre:** REQ-001, REQ-004, REQ-007

### ALT-004 Parseo devuelve 0 o muy pocas ofertas

- **Condición:** `parser-adapter` extrae cero ofertas o un recuento inferior al umbral de cordura configurado.
- **Comportamiento:** `comparador-veredicto` emite veredicto `divergente` independientemente del `total_listado` del buscador; el `.meta.json` registra el recuento PDF y el motivo.
- **Responsable:** comparador-veredicto
- **Resultado:** El veredicto es `divergente` porque el PDF no supera el umbral de cordura.
- **Cubre:** REQ-004, NFR-002

### ALT-005 Buscador no responde o no hay `ultima_pasada`

- **Condición:** `GET /buscador/status` devuelve error HTTP, `ultima_pasada` es nula o la respuesta no contiene `total_listado`.
- **Comportamiento:** `comparador-veredicto` no emite veredicto `concordante`; el `.meta.json` registra veredicto `divergente` con el motivo de ausencia de datos del buscador.
- **Responsable:** buscador-status-adapter
- **Resultado:** Veredicto `divergente`; se recomienda no cerrar ofertas.
- **Cubre:** REQ-003, REQ-006

### ALT-006 `ultima_pasada` contiene `error_global`

- **Condición:** `GET /buscador/status` devuelve `ultima_pasada` con `error_global` no vacío.
- **Comportamiento:** `comparador-veredicto` no emite veredicto `concordante`; el `.meta.json` registra veredicto `divergente` con el motivo.
- **Responsable:** buscador-status-adapter
- **Resultado:** Veredicto `divergente`; se recomienda no cerrar ofertas.
- **Cubre:** REQ-003, REQ-006

### ALT-007 PDF existe pero el `.meta.json` no

- **Condición:** Se encuentra un PDF del día pero no su `.meta.json` (por ejemplo, escritura interrumpida).
- **Comportamiento:** `integridad-task` trata el PDF como huérfano: lo parsea de nuevo, recalcula el hash, genera el `.meta.json` y emite el veredicto; si el parseo falla, genera un `.meta.json` con veredicto `fallido`.
- **Responsable:** pdf-store
- **Resultado:** El día queda con `.meta.json` completo; el PDF se conserva si es legible.
- **Cubre:** REQ-002, REQ-005

### ALT-008 Veredicto global con varias comunidades

- **Condición:** La configuración incluye más de una comunidad.
- **Comportamiento:** Cada comunidad tiene su propio `.meta.json` y veredicto. El veredicto global es `concordante` solo si todas las comunidades son `concordante`; si alguna es `divergente` o `fallido`, el global es el más grave (`fallido` > `divergente` > `concordante`).
- **Responsable:** integridad-task
- **Resultado:** La consulta del último veredicto devuelve tanto el veredicto global como el desglose por comunidad.
- **Cubre:** REQ-004, REQ-006

### ALT-009 Arranque o reinicio con respecto a la hora configurada y su margen

- **Condición:** La API se inicia o reinicia en cualquier momento del día.
- **Comportamiento:** `integridad-task` compara la hora actual con la hora configurada y el margen de catch-up (`hora + margen`). Si ya existe `.meta.json` de hoy, no hace nada. Si la hora aún no ha llegado, espera a la ejecución programada normal. Si se arranca dentro de la ventana `hora` a `hora + margen` y falta `.meta.json`, programa una ejecución única para `hora + margen` (si al llegar sigue sin metadatos, ejecuta). Si se arranca después de `hora + margen` y falta `.meta.json`, ejecuta inmediatamente. La recuperación nunca procesa días anteriores.
- **Responsable:** integridad-task
- **Resultado:** El día en curso se comprueba una sola vez, con un margen que evita competir con la pasada programada del buscador y con la propia ejecución a la hora configurada.
- **Cubre:** REQ-001, REQ-005, NFR-003

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| api-service | config-integridad | Solicitud de carga de configuración | llamada interna |
| api-service | integridad-task | Señal de arranque/parada | llamada interna |
| integridad-task | pdf-store | Ruta base, comunidad y fecha; petición de lectura/escritura de PDF y `.meta.json` | llamada interna |
| integridad-task | downloader-adapter | URL del PDF de una comunidad | llamada interna |
| downloader-adapter | PDF externo | GET del PDF | HTTPS |
| integridad-task | parser-adapter | Bytes del PDF y comunidad | llamada interna |
| integridad-task | buscador-status-adapter | URL base del buscador | llamada interna |
| buscador-status-adapter | GET /buscador/status | Petición de estado | HTTP (OpenAPI) |
| integridad-task | comparador-veredicto | Recuento PDF, `total_listado` y umbrales | llamada interna |
| integridad-task | avisos-store | Veredicto y motivo de aviso | llamada interna |
| integridad-task | pdf-purger | Retención configurada y día actual | llamada interna |
| Cliente | integridad-api | Consultas de veredicto, ejecuciones y PDFs | HTTP (OpenAPI) |
| integridad-api | pdf-store | Listado de PDFs y metadatos | llamada interna |
| integridad-api | avisos-store | Listado de ejecuciones y avisos | llamada interna |

## Modelo de datos lógico

- **PDFDia:** fichero binario del PDF oficial de una comunidad para una fecha concreta. Relación: pertenece a una ComunidadConfigurada y tiene un único MetaDia.
- **MetaDia:** metadatos del día en `<aaaa-mm-dd>.meta.json`: hash, recuento PDF, recuento buscador, diferencia, tolerancias, umbral de cordura, veredicto, errores, timestamp. Relación: uno por PDFDia.
- **EjecucionIntegridad:** registro del índice de ejecuciones con timestamp, resultado global, errores por comunidad y veredicto agregado. Relaciones: ninguna; se consulta por rango de fecha.
- **AvisoIntegridad:** aviso de divergencia o fallo derivado del `.meta.json`. Relación: asociado a un MetaDia.
- **ComunidadConfigurada:** identificador de comunidad y URL de PDF, leído desde `config/comunidades.yaml`. Relación: origen de cada PDFDia.

## Decisiones

### DEC-001 Registro primario en `.meta.json` con índice de ejecuciones en JSON

- **Decisión:** El veredicto, los recuentos, el hash, los umbrales y los errores de cada día viven en el fichero `<aaaa-mm-dd>.meta.json` junto al PDF. Las ejecuciones del último mes se indexan en un fichero JSON ligero (`data/pdfs/ejecuciones.json` o similar) que apunta a los `.meta.json` por fecha y comunidad. No se añade un tercer fichero SQLite.
- **Alternativas descartadas:**
  - (a) Tablas en `data/job_emcan.db`: obligaría a compartir el versionado de esquema con `api-persistencia`, que es feature aprobada y no se modifica.
  - (b) Fichero SQLite propio (`data/job_emcan_integridad.db`): añadiría un tercer fichero SQLite al proyecto, contradiciendo el espíritu de `.sdd/project.md` ("un solo fichero, WAL") y duplicando la fuente de verdad que ya pueden representar los metadatos por día.
  - (c) Solo `.meta.json` sin índice: dificultaría la consulta eficiente de ejecuciones del último mes y el veredicto global.
- **Cubre:** REQ-005, REQ-008, REQ-009, NFR-001, NFR-004

### DEC-002 PDF con parseo fallido se conserva con veredicto `fallido`

- **Decisión:** Si la descarga tiene éxito pero el parseo falla, el PDF se conserva en `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y el `.meta.json` se escribe con veredicto `fallido` y el error. Esto permite diagnóstico posterior sin perder la prueba de lo publicado; la purga lo eliminará con el mismo plazo de retención.
- **Alternativas descartadas:**
  - (a) Borrar el PDF si el parseo falla: pierde la trazabilidad del documento descargado y dificulta la depuración.
  - (b) Reintentar el parseo automáticamente: violaría la frecuencia máxima diaria (NFR-003) sin política de reintentos definida en los requisitos.
- **Cubre:** REQ-002, REQ-004, REQ-007

### DEC-003 Hash SHA-256 del PDF

- **Decisión:** Se calcula el hash SHA-256 del contenido del PDF y se guarda en el `.meta.json`.
- **Alternativas descartadas:**
  - (a) MD5: más rápido pero obsoleto para comprobaciones de integridad.
  - (b) SHA-1: también en desuso.
  - (c) Sin hash: el `.meta.json` no podría detectar cambios en el fichero almacenado.
- **Cubre:** REQ-005

### DEC-004 Purga por fecha del nombre, no por `mtime`

- **Decisión:** `pdf-purger` determina la antigüedad a partir de la fecha extraída del nombre `<aaaa-mm-dd>.pdf`, no del `mtime`. Esto evita que cambios de sistema de archivos o restauraciones desplacen incorrectamente la ventana de retención.
- **Alternativas descartadas:**
  - (a) Purga por `mtime`: más simple pero vulnerable a modificaciones accidentales del sistema de archivos.
  - (b) Purga por fecha del `.meta.json`: requiere leer cada metadato; el nombre ya codifica la fecha explícitamente.
- **Cubre:** REQ-002

### DEC-005 Tolerancia compuesta con el límite más permisivo

- **Decisión:** Dos recuentos se consideran concordantes si `|pdf - buscador| <= tolerancia_absoluta` **o** `|pdf - buscador| / buscador <= tolerancia_relativa`, aplicando la regla más permisiva. Además, el veredicto es siempre `divergente` si el recuento del PDF está por debajo del umbral de cordura.
- **Alternativas descartadas:**
  - (a) Igualdad estricta: provocaría veredictos `divergente` en condiciones normales.
  - (b) Tolerancia relativa única: menos explícita para diferencias pequeñas.
  - (c) Aplicar la regla más restrictiva (ambas a la vez): aumentaría los falsos divergentes.
- **Cubre:** REQ-003, REQ-004, NFR-002, SUP-001

### DEC-006 Convivencia con otras tareas programadas en el mismo proceso

- **Decisión:** `integridad-task` se ejecuta en su propio hilo/daemon dentro del proceso FastAPI, con su propio evento de parada. Arranca después del buscador, la persistencia y el histórico; se detiene antes de cerrar las conexiones SQLite y el scheduler del buscador.
- **Alternativas descartadas:**
  - (a) Modificar el scheduler del buscador para lanzar integridad: contradice la restricción de no tocar `api-buscador`.
  - (b) Proceso separado: añadiría complejidad de despliegue y no se justifica para una tarea diaria de segundos.
- **Cubre:** REQ-001, NFR-001, NFR-004

### DEC-007 Recuperación del día en curso al arrancar fuera de la hora, con margen configurable

- **Decisión:** `integridad-task` aplica una lógica de catch-up con un margen configurable (`margen_catchup`, entero ≥ 0, por defecto 60 minutos):
  - Arranque antes de `hora`: espera a la ejecución programada normal.
  - Arranque entre `hora` y `hora + margen` sin `.meta.json` de hoy: programa una ejecución única para `hora + margen`.
  - Arranque después de `hora + margen` sin `.meta.json` de hoy: ejecuta inmediatamente.
  - `.meta.json` de hoy ya existente: no se ejecuta nada.
  - No se procesan días anteriores (sin backfill).
- **Alternativas descartadas:**
  - (a) No recuperar y esperar al día siguiente: en un entorno de uso personal donde la API puede no estar levantada a las 02:00, esto provocaría la pérdida habitual del veredicto del día y del PDF mensual.
  - (b) Recuperar en cuanto pasa la hora, sin margen: el catch-up inmediato podría coincidir con la finalización de la pasada programada del buscador (01:00) o con la ejecución programada de `api-integridad` (02:00), compitiendo por recursos y leyendo un `total_listado` potencialmente aún no actualizado.
  - (c) Backfill de varios días perdidos: los requisitos piden una ejecución diaria y un máximo de una por día; además, el buscador solo conserva el resultado de la última pasada en memoria, por lo que no es posible comparar recuentos de días pasados.
  - (d) Recuperación siempre al arrancar, aunque exista `.meta.json`: violaría la idempotencia diaria y el máximo de una ejecución por día.
- **Cubre:** REQ-001, REQ-005, NFR-003

## Riesgos

- **PDF cambiado de formato:** si el portal modifica la estructura del PDF, `parser-adapter` puede devolver 0 ofertas y el veredicto será `divergente`. Mitigación: umbral de cordura, registro del aviso y conservación del PDF original para diagnóstico.
- **Hash distinto con mismo recuento:** el hash detecta cambios en el documento binario; si cambia el PDF pero el recuento coincide, el veredicto seguirá siendo `concordante` y el hash quedará actualizado en el `.meta.json`. Mitigación: el hash se recalcula y almacena siempre, permitiendo auditoría posterior.
- **Reinicio del buscador:** si `api-buscador` se reinicia y pierde `ultima_pasada`, `buscador-status-adapter` no obtendrá `total_listado` y el veredicto será `divergente`. Mitigación: la hora por defecto (02:00) se sitúa tras la pasada esperada del buscador; tras un reinicio, la siguiente pasada repoblará el estado.
- **Doble ejecución en el mismo día:** si la tarea se dispara dos veces (incluida una recuperación de arranque tras una ejecución programada previa), la idempotencia por `.meta.json` evita descargas y veredictos duplicados. Mitigación: `integridad-task` consulta la existencia del `.meta.json` antes de actuar, tanto en el ciclo programado como en la recuperación.
- **Reloj o zona horaria incorrecta:** todas las fechas se calculan con la zona horaria configurada (`Europe/Madrid` por defecto). Mitigación: validación de la zona al cargar la configuración y uso explícito de fecha local para el nombre del PDF y la comparación diaria.
- **API no levantada a la hora configurada:** en un entorno de uso personal la API puede estar apagada a las 02:00. Sin recuperación, se perdería el veredicto y el PDF del día. Mitigación: DEC-007 ejecuta una comprobación del día en curso al arrancar, respetando el margen configurado; si se arranca dentro del margen, la ejecución se retrasa hasta `hora + margen` para no competir con la pasada del buscador.
- **Margen de catch-up insuficiente o 0:** un margen de 0 minutos (o muy pequeño) hace que el catch-up se dispare en cuanto pasa la hora, pudiendo coincidir con la ejecución programada o con la finalización de la pasada del buscador. Mitigación: valor por defecto de 60 minutos; validación de que el margen es un entero ≥ 0; el usuario puede ajustarlo según la duración real de la pasada del buscador.
- **Disco lleno:** la escritura atómica puede fallar si no hay espacio. Mitigación: captura del error, `.meta.json` con veredicto `fallido` y aviso; la purga limita el crecimiento a la ventana de retención.
- **Metadatos corruptos:** si un `.meta.json` no es legible, `integridad-api` lo omite en las consultas; si la tarea lo encuentra al inicio, lo regenera a partir del PDF (ALT-007) o lo trata como inexistente si no hay PDF asociado.
- **Orden temporal con `api-historico`:** por defecto tanto `api-historico` como `api-integridad` se programan a las 02:00. Hoy el veredicto es informativo y `api-historico` no lo consume, por lo que la concurrencia no afecta la corrección. Si en el futuro un consumidor necesita el veredicto antes de evaluar cierres, se deberá configurar `api-integridad` a una hora anterior a `api-historico` (la configuración solo admite horas enteras, por lo que esto puede requerir ajustar también la hora de `api-historico` si se desea orden estricto).

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | integridad-task, downloader-adapter, pdf-store | DEC-006, DEC-007 |
| REQ-002 | pdf-store, pdf-purger | DEC-002, DEC-004 |
| REQ-003 | buscador-status-adapter, comparador-veredicto | DEC-005 |
| REQ-004 | comparador-veredicto, pdf-store | DEC-005 |
| REQ-005 | pdf-store | DEC-001, DEC-003, DEC-007 |
| REQ-006 | comparador-veredicto, integridad-api | DEC-005 |
| REQ-007 | comparador-veredicto, avisos-store | DEC-002 |
| REQ-008 | integridad-task, avisos-store | DEC-001 |
| REQ-009 | integridad-api, pdf-store, avisos-store | DEC-001 |
| NFR-001 | config-integridad, integridad-task | DEC-006 |
| NFR-002 | config-integridad, comparador-veredicto | DEC-005 |
| NFR-003 | integridad-task, pdf-store | DEC-001, DEC-007 |
| NFR-004 | config-integridad, integridad-task | DEC-001, DEC-006 |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-integridad.yaml` (nuevo) | Define los endpoints de consulta del último veredicto, ejecuciones del último mes y PDFs conservados. Siguiendo la estrategia `implementation-first` de `.sdd/team.md`, se derivará de la implementación. |
| Configuración | `config/integridad.yaml` (nuevo) | Configuración de `api-integridad`: zona horaria, hora de ejecución, margen de catch-up (minutos), días de retención, tolerancia absoluta, tolerancia relativa, umbral de cordura, ruta base de PDFs, URL base del buscador y comunidades. |
| HTTP/OpenAPI | `docs/contracts/openapi/api-buscador.yaml` (existente) | `api-integridad` consume `GET /buscador/status`; no se modifica el contrato. |
| Llamada interna | Uso de `source/api/downloader.py`, `source/api/parser.py` y `source/api/assembler.py` (existentes) | `api-integridad` invoca en proceso los módulos de descarga y parseo; no se modifica el contrato de uso. |

## Cambios sugeridos al mapa

Los componentes descritos en este diseño (`integridad-task`, `pdf-store`, `comparador-veredicto`, etc.) son detalle interno de implementación dentro del módulo `API` y no reciben identificador propio en el mapa de arquitectura.

- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador, persistencia, histórico e integridad de ofertas | -`
- `+ Contrato: openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad`
- `+ Contrato: configuracion | config/integridad.yaml | api-integridad -> config-integridad`

## Estrategia de tests

- **Tests unitarios del comparador/veredicto:** igualdad, diferencia dentro de tolerancia absoluta, dentro de tolerancia relativa, umbral de cordura, combinaciones y elección del veredicto más grave entre comunidades.
- **Tests del almacenamiento y purga:** escritura atómica de PDF, cálculo de hash SHA-256, lectura/escritura de `.meta.json`, listado de PDFs conservados, purga por antigüedad, omisión del día en curso y manejo de PDFs huérfanos sin metadatos, todo sobre directorios temporales.
- **Tests de adaptadores:** `downloader-adapter` con cliente HTTP mockeado (PDF válido, error HTTP, timeout); `parser-adapter` con bytes de PDF de prueba; `buscador-status-adapter` con respuestas simuladas de `GET /buscador/status` (con y sin `ultima_pasada`, con `error_global`).
- **Tests de la tarea programada:** disparo a la hora configurada, idempotencia diaria, omisión cuando ya existe `.meta.json`, veredicto `fallido` ante descarga o parseo erróneo, veredicto `divergente` cuando el buscador no responde o el recuento difiere.
- **Tests de endpoints:** `GET /integridad/ultimo`, `/integridad/ejecuciones` y `/integridad/pdfs` con directorio temporal de metadatos y PDFs; comprobación de códigos de error cuando no hay datos.
- **Tests de arranque/apagado:** carga de configuración, registro de la tarea en `lifespan`, detención limpia sin dejar hilos huérfanos y orden de cierre respecto a persistencia, histórico y scheduler del buscador. Incluir casos de arranque antes de la hora configurada (espera a la ejecución normal), arranque dentro del margen de catch-up sin `.meta.json` del día (programa ejecución única para `hora + margen`), arranque después del margen sin `.meta.json` (recuperación inmediata), arranque con `.meta.json` existente (sin recuperación), reinicio con estado parcial y margen configurado a 0 (recuperación inmediata tras la hora).

## Avisos

- `api-integridad` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`; la integración se realiza a través de `GET /buscador/status` y de la llamada en proceso a los módulos de descarga y parseo existentes.
- El veredicto es informativo y consultable: indica si los cierres están recomendados, pero no impide por sí mismo que `api-historico` marque cierres. El cumplimiento completo de FUN-014 («si divergen, no se marcan cierres y se avisa») queda a expensas de que un consumidor futuro actúe sobre el veredicto.
- No se propone un tercer fichero SQLite: el registro primario del día es el `.meta.json` junto al PDF, y el índice de ejecuciones es un fichero JSON ligero. Esto respeta el principio de `.sdd/project.md` de un único fichero SQLite para la base de datos de ofertas.
- Con la configuración por defecto, `api-buscador` se ejecuta a las 01:00, `api-historico` a las 02:00 y `api-integridad` a las 02:00. Hoy `api-historico` no consume el veredicto, por lo que ambas tareas pueden ejecutarse concurrentemente sin afectar la corrección. Si en el futuro se requiere que el veredicto exista antes de los cierres, se deberá ajustar la hora de `api-integridad` a un valor anterior al de `api-historico` (teniendo en cuenta que la configuración admite solo horas enteras).
