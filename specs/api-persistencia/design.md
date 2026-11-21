# Diseño: api-persistencia

Estado: aprobado
Revisión: 2
Basado en: requirements@5
Verificación: correcta

## Resumen

Se añade a la API FastAPI existente una capa de persistencia en SQLite único con WAL que almacena las ofertas, conserva el histórico de altas y cierres, prepara el esquema para embeddings y se sincroniza con `api-buscador` sin modificarlo: importa idempotentemente `data/seen_codes.json` e ingiere periódicamente las fichas completas consultando `GET /buscador/status`. La base de datos se convierte en la fuente de verdad para el resto de módulos.

## Supuestos sobre el sistema actual

- La API FastAPI vive en `source/api/` y expone `GET /buscador/status` en el mismo proceso, con `_ultimo_resultado` solo en memoria (`source/api/buscador/coordinator.py`).
- `api-buscador` sigue escribiendo `data/seen_codes.json` como lista plana de códigos de texto y no se modifica.
- El buscador interno se localiza mediante una URL base configurable (por ejemplo, `http://localhost:8000`), ya que la ingesta usa HTTP contra el endpoint ya desplegado.
- La decisión DEC-009 del contrato HTML mantiene `sector`, `nivel` y `contrato` vacíos en la ficha.
- El flag de "interesada" pertenece a `api-candidaturas`, que aún no existe; se resuelve añadiendo la columna reservada en este esquema con valor por defecto `false`.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que arranca la persistencia, ejecuta migraciones, dispara el importador de códigos vistos e inicia las tareas periódicas de ingesta y purga. | existente (se extiende) |
| config-persistencia | Fichero YAML con ruta de la BD, URL base del buscador, cadencia de ingesta y días de retención de la purga. | nuevo |
| db-connection | Gestiona la conexión única a SQLite, activa WAL, configura `busy_timeout` y expone transacciones. | nuevo |
| schema-migrator | Aplica migraciones secuenciales de forma transaccional y detecta versiones futuras o ficheros corruptos. | nuevo |
| ofertas-repository | Abstracción de lectura/escritura de ofertas: upsert por `(comunidad, codigo)`, consulta por clave natural, listado por estado y reducción a registro mínimo. | nuevo |
| seen-codes-importer | Lee `data/seen_codes.json` y crea registros `sin_ficha` de forma idempotente, sin modificar el fichero origen. | nuevo |
| buscador-client | Cliente HTTP que consulta `GET /buscador/status` y devuelve el resultado publicado en memoria. | nuevo |
| ingestion-task | Tarea periódica que detecta un `timestamp` nuevo de `ultima_pasada` e importa `ofertas_nuevas` una sola vez por pasada. | nuevo |
| purge-task | Tarea periódica que reduce a registro mínimo las ofertas cerradas no interesadas tras el plazo de retención. | nuevo |
| persistencia-api | Endpoints que exponen al resto de módulos las operaciones de lectura y escritura de ofertas. | nuevo |

## Flujo principal

1. Al arrancar `api-service`, `db-connection` crea o abre el fichero SQLite único, activa WAL y configura `busy_timeout`.
2. `schema-migrator` consulta la versión actual y aplica las migraciones pendientes de forma secuencial y transaccional.
3. `seen-codes-importer` lee `data/seen_codes.json` e inserta o ignora cada código como registro `sin_ficha` para Cantabria.
4. `api-service` arranca `ingestion-task` con la cadencia configurada y `purge-task` con su propia frecuencia.
5. En cada ciclo, `ingestion-task` pide a `buscador-client` el estado del buscador (`GET /buscador/status`).
6. Si `ultima_pasada` existe, no hay `error_global` y su `timestamp` difiere del último importado, `ingestion-task` envía cada oferta de `ofertas_nuevas` a `ofertas-repository`.
7. `ofertas-repository` resuelve el conflicto por `(comunidad, codigo)` mediante upsert: crea la oferta como `vigente` si no existe; si existe como `sin_ficha`, la completa y cambia el estado a `vigente`; si ya es `vigente`, no duplica y no sobrescribe campos completos con valores vacíos.
8. Tras persistir todas las ofertas de la pasada, `ingestion-task` registra el `timestamp` como último importado.
9. `purge-task` consulta periódicamente las ofertas `cerrada` cuya fecha de cierre supere el plazo de retención y cuyo flag `interesada` sea `false`, y reduce esos registros a los campos mínimos conservando el embedding.

## Flujos alternativos y de fallo

### ALT-001 Buscador no responde o `ultima_pasada` reporta `error_global`

- **Condición:** `GET /buscador/status` devuelve error HTTP, el cuerpo indica `error_global` no vacío o la petición falla por red.
- **Comportamiento:** `ingestion-task` omite la importación, no registra ningún `timestamp` como importado y deja constancia del estado consultado en el log.
- **Responsable:** ingestion-task
- **Resultado:** La base de datos no cambia; en el siguiente ciclo se vuelve a intentar.
- **Cubre:** REQ-017

### ALT-002 `ultima_pasada` es nula por reinicio del buscador

- **Condición:** `api-buscador` se ha reiniciado y `_ultimo_resultado` ha desaparecido de memoria, por lo que `GET /buscador/status` devuelve `ultima_pasada = null`.
- **Comportamiento:** `ingestion-task` no marca ningún resultado anterior como importado y espera a que una nueva pasada complete y publique un `timestamp`.
- **Responsable:** ingestion-task
- **Resultado:** No se persisten ofertas ni se avanza el último `timestamp` importado.
- **Cubre:** REQ-017

### ALT-003 `data/seen_codes.json` no existe o está corrupto

- **Condición:** El fichero de códigos vistos no existe, no es JSON válido o no es una lista.
- **Comportamiento:** Si no existe, `seen-codes-importer` lo registra y continúa sin importar nada. Si está corrupto, registra el error y continúa para no bloquear el arranque de la API.
- **Responsable:** seen-codes-importer
- **Resultado:** El arranque de la API no se interrumpe; los códigos se importarán en la siguiente ejecución si el fichero se corrige.
- **Cubre:** REQ-013, REQ-014

### ALT-004 Base de datos en versión futura o fichero corrupto

- **Condición:** `schema-migrator` encuentra una versión mayor que la esperada o el fichero SQLite no se puede abrir.
- **Comportamiento:** Se aborta el arranque de la API con un error explícito; no se aplican migraciones parciales ni se sobrescribe el fichero.
- **Responsable:** schema-migrator
- **Resultado:** La API no arranca hasta que se resuelva la discrepancia manualmente.
- **Cubre:** REQ-010

### ALT-005 Escritura concurrente sobre la misma oferta

- **Condición:** Dos operaciones intentan crear o actualizar la misma fila al mismo tiempo.
- **Comportamiento:** SQLite serializa las escrituras gracias a WAL y `busy_timeout`; el upsert por `(comunidad, codigo)` garantiza que no se generan duplicados.
- **Responsable:** db-connection
- **Resultado:** El resultado es equivalente a una ejecución tras otra; queda un único registro.
- **Cubre:** NFR-006

### ALT-006 Oferta cerrada marcada como interesada alcanza el plazo de purga

- **Condición:** Una oferta `cerrada` cumple el plazo de retención pero su flag `interesada` es `true`.
- **Comportamiento:** `purge-task` omite el registro y conserva `texto_libre` y `contacto`.
- **Responsable:** purge-task
- **Resultado:** El registro permanece completo mientras esté marcado como interesada.
- **Cubre:** REQ-006

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| api-service | db-connection | Solicitud de conexión y transacción | llamada interna |
| api-service | schema-migrator | Orden de migrar al arranque | llamada interna |
| api-service | seen-codes-importer | Orden de importar códigos al arranque y bajo demanda | llamada interna |
| api-service | ingestion-task | Configuración y señal de arranque/parada | llamada interna |
| api-service | purge-task | Configuración y señal de arranque/parada | llamada interna |
| ingestion-task | buscador-client | Petición de estado del buscador | HTTP (OpenAPI) |
| ingestion-task | ofertas-repository | Ofertas a crear/actualizar | llamada interna |
| persistencia-api | ofertas-repository | Operaciones de lectura/escritura de ofertas | llamada interna |
| Cliente | persistencia-api | Crear, consultar, listar ofertas y códigos vistos | HTTP (OpenAPI) |

## Modelo de datos lógico

- **Oferta:** oferta de empleo identificada por la pareja `(comunidad, codigo)`. Relaciones: ninguna.
- **SchemaVersion:** versión actual del esquema de la base de datos. Relaciones: ninguna.
- **IngestaLog:** registro del último `timestamp` importado desde `GET /buscador/status`. Relaciones: ninguna.

## Esquema conceptual SQLite

### Tabla `schema_version`

| Columna | Tipo SQLite | Restricciones |
|---|---|---|
| version | INTEGER | PRIMARY KEY |
| applied_at | TEXT | not null |

### Tabla `ofertas`

| Columna | Tipo SQLite | Restricciones / Notas |
|---|---|---|
| rowid | INTEGER | clave técnica autoincremental (implícita) |
| comunidad | TEXT | not null, parte de la clave natural |
| provincia | TEXT | |
| codigo | TEXT | not null, parte de la clave natural |
| ocupacion | TEXT | |
| municipio | TEXT | |
| sector | TEXT | vacío según DEC-009 |
| nivel | TEXT | vacío según DEC-009 |
| contrato | TEXT | vacío según DEC-009 |
| fecha_inicio_difusion | TEXT | formato `dd/mm/aaaa` |
| fecha_fin_difusion | TEXT | formato `dd/mm/aaaa` |
| estado | TEXT | not null: `sin_ficha`, `vigente` o `cerrada` |
| texto_libre | TEXT | |
| contacto | TEXT | |
| embedding | BLOB | bytes del vector; nulo si aún no se ha generado |
| embedding_model_name | TEXT | |
| embedding_model_version | TEXT | |
| embedding_dim | INTEGER | dimensión del vector (por ejemplo, 768); nula si `embedding` es nulo |
| interesada | INTEGER | `0`/`1`; reservada para `api-candidaturas`, por defecto `0` |
| fecha_alta | TEXT | ISO 8601, momento en que el registro se creó |
| fecha_cierre | TEXT | ISO 8601, momento en que pasó a `cerrada` |
| fecha_ultima_actualizacion | TEXT | ISO 8601, actualizado en cada escritura |

**Restricciones e índices:**

- UNIQUE `(comunidad, codigo)`
- INDEX `(estado, fecha_fin_difusion)`
- INDEX `(embedding_model_name, embedding_model_version)`

### Tabla `ingesta_log`

| Columna | Tipo SQLite | Restricciones / Notas |
|---|---|---|
| id | INTEGER | PRIMARY KEY |
| ultimo_timestamp | TEXT | ISO 8601 del último `timestamp` importado |
| actualizado_en | TEXT | ISO 8601 |

### Serialización del embedding

- **dtype:** `float32`.
- **forma/dimensión:** la dimensión del vector se almacena explícitamente en la columna `embedding_dim` (por ejemplo, `768` para `nomic-embed-text`).
- **versión:** el par `embedding_model_name` + `embedding_model_version` identifica el modelo que generó el vector.
- **contenido del BLOB:** bytes contiguos del array de `float32`, obtenidos directamente del vector de numpy. La reconstrucción usa `dtype=float32`, la dimensión de `embedding_dim` y los bytes del BLOB, sin depender de inferir la forma a partir del modelo.

### Representación de estados

- `sin_ficha`: código importado solo desde `data/seen_codes.json`; no se dispone de datos de ficha.
- `vigente`: oferta con ficha ingerida y activa.
- `cerrada`: oferta marcada como cerrada por un módulo externo; se conserva la fecha/hora del cierre.

## Migraciones

- Las migraciones se numeran secuencialmente (por ejemplo, `001`, `002`) y se ejecutan en orden estricto.
- Cada migración corre dentro de una transacción SQLite; si falla, se deshace y se aborta el arranque.
- Se ejecutan al arrancar la API, antes de que cualquier otro componente acceda a la base de datos.
- Si el fichero ya está en la versión esperada, no se reejecutan migraciones.
- Si el fichero está en una versión futura o el fichero está corrupto, `schema-migrator` aborta el arranque y notifica el error.
- Las migraciones incluyen la creación inicial de tablas, índices y la inserción de la versión en `schema_version`.

## Concurrencia

- Se usa un único fichero SQLite con WAL activado (`PRAGMA journal_mode = WAL`).
- Se configura `busy_timeout` para que los escritores esperen en lugar de fallar con `SQLITE_BUSY`.
- Aunque SQLite serializa las escrituras, `ingestion-task` y `purge-task` actúan como escritores lógicos coordinados: la ingesta no se solapa con la purga sobre el mismo conjunto de ofertas mediante la programación de tareas.
- Los lectores (endpoints de la API) pueden operar concurrentemente gracias a WAL.
- Si la API se reinicia, el estado de la última ingesta se recupera desde `ingesta_log`; no se pierde la trazabilidad de qué pasada ya fue importada.

## Ingesta desde `GET /buscador/status`

- `buscador-client` realiza una petición HTTP añadiendo `/buscador/status` a la URL base configurada.
- `ingestion-task` se ejecuta periódicamente (por defecto cada 5 minutos).
- La detección de pasada nueva se hace comparando el `timestamp` de `ultima_pasada` con el valor almacenado en `ingesta_log`.
- Solo se importa una vez por `timestamp`; si el `timestamp` ya fue importado, la tarea no hace nada.
- La idempotencia por código se garantiza mediante el upsert por `(comunidad, codigo)`.
- Al actualizar, no se sobrescriben datos completos con valores vacíos: si la ficha entrante trae un campo vacío pero el registro ya tiene un valor no vacío, se conserva el existente.
- Si el buscador no responde, si `error_global` no está vacío o si `ultima_pasada` es nula, la ingesta omite la importación y espera al siguiente ciclo.

## Importación de `data/seen_codes.json`

- Se ejecuta al arrancar la API y puede repetirse bajo demanda o periódicamente según configuración.
- El fichero se lee como lista plana de códigos de texto; cada código se importa con comunidad `Cantabria`, estado `sin_ficha` y el resto de campos vacíos.
- La idempotencia se resuelve mediante upsert por `(comunidad, codigo)`: los códigos ya existentes no se duplican y los nuevos se añaden.
- Si el fichero no existe, se registra y se continúa sin fallar.
- Si el fichero está corrupto, se registra el error y se continúa sin modificar la base de datos.
- `api-buscador` sigue siendo el único escritor de `data/seen_codes.json`; `api-persistencia` nunca lo modifica.

## Purga

- **Criterio de disparo:** ofertas en estado `cerrada` cuya `fecha_cierre` supere los 7 días naturales configurados y cuyo flag `interesada` sea `false`.
- **Frecuencia:** periódica, configurable (por defecto una vez al día).
- **Campos que se vacían:** `texto_libre` y `contacto` pasan a nulos.
- **Campos que se conservan:** comunidad, provincia, código, ocupación, municipio, sector, nivel, contrato (mantenidos vacíos según DEC-009), fechas de difusión, estado, embedding, `embedding_model_name`, `embedding_model_version`, `embedding_dim`, fechas de alta/cierre/actualización.
- **Resolución del flag "interesada":** se añade a la tabla `ofertas` la columna `interesada` con valor por defecto `0` (`false`), reservada para que `api-candidaturas` la gestione en el futuro. Hasta entonces, todas las ofertas cerradas se consideran no interesadas y se purgan tras el plazo.

## Configuración

El fichero `config/persistencia.yaml` (o equivalente) contendrá:

- `base_de_datos.ruta`: ruta al fichero SQLite (por defecto `data/job_emcan.db`).
- `buscador.url_base`: URL base para consultar `GET /buscador/status` (por defecto `http://localhost:8000`).
- `ingesta.cadencia_segundos`: intervalo entre consultas al buscador (por defecto `300`).
- `purga.dias_retencion`: días que se conservan `texto_libre` y `contacto` tras el cierre (por defecto `7`).
- `purga.frecuencia_segundos`: intervalo entre ejecuciones de la purga (por defecto `86400`).

## Decisiones

### DEC-001 SQLite único con WAL

- **Decisión:** Un único fichero SQLite (`data/job_emcan.db`) con WAL activado.
- **Alternativas descartadas:** Servidor de base de datos (contradice NFR-001 y el alcance personal/local); múltiples ficheros SQLite (aumenta la complejidad sin beneficio).
- **Cubre:** REQ-011, NFR-001, NFR-002

### DEC-002 Embeddings como BLOB por fila con dimensión explícita

- **Decisión:** Cada embedding se guarda en la misma fila de la oferta como BLOB, junto con nombre, versión y dimensión del modelo (`embedding_dim`). La dimensión explícita permite reconstruir el array `float32` sin ambigüedad.
- **Alternativas descartadas:** Tabla separada de embeddings (añade joins innecesarios para este volumen); base vectorial o extensión de SQLite (contradice NFR-005); inferir la dimensión del modelo (rompe la reconstrucción si cambia la versión o hay múltiples configuraciones).
- **Cubre:** REQ-004, REQ-005, NFR-005

### DEC-003 Estados `sin_ficha`, `vigente` y `cerrada`

- **Decisión:** Se usa el campo `estado` para distinguir códigos importados sin ficha, ofertas con ficha y ofertas cerradas; no se añade un booleano adicional.
- **Alternativas descartadas:** Campo booleano `ficha_descargada` (mantendría dos fuentes de verdad sobre el mismo concepto, ya descartado en SUP-012).
- **Cubre:** REQ-003, REQ-015

### DEC-004 Migraciones secuenciales transaccionales

- **Decisión:** Control de versiones con tabla `schema_version` y migraciones numeradas secuencialmente, cada una en transacción.
- **Alternativas descartadas:** Esquema fijo sin versionado (imposibilita la evolución); migraciones no transaccionales (riesgo de esquema a medias).
- **Cubre:** REQ-010

### DEC-005 Ingesta periódica consultando `/buscador/status`

- **Decisión:** `api-persistencia` consulta periódicamente el endpoint de estado de `api-buscador` e importa las ofertas nuevas publicadas en memoria.
- **Alternativas descartadas:** Modificar `api-buscador` para que escriba directamente en SQLite (contradice SUP-013); descargar fichas del portal desde `api-persistencia` (fuera de alcance).
- **Cubre:** REQ-017, REQ-018

### DEC-006 Importación idempotente desde `data/seen_codes.json`

- **Decisión:** `api-persistencia` lee el fichero JSON que escribe `api-buscador` y realiza upserts idempotentes en la tabla de ofertas.
- **Alternativas descartadas:** Convertir `api-buscador` en cliente de la base de datos (contradice su alcance y SUP-013); duplicar el fichero como estado propio.
- **Cubre:** REQ-013, REQ-014

### DEC-007 Columna `interesada` reservada para `api-candidaturas`

- **Decisión:** Se añade la columna `interesada` a `ofertas` con valor por defecto `false`, documentada como reservada para `api-candidaturas`.
- **Alternativas descartadas:** Aplazar la purga (incumple REQ-006); suponer siempre no interesada sin columna (dificulta la integración futura y contradice PDEC-016).
- **Cubre:** REQ-006

### DEC-008 Escritor único lógico con WAL

- **Decisión:** Se configura WAL y `busy_timeout` para lectores concurrentes, y se coordinan `ingestion-task` y `purge-task` como escritores lógicos para evitar contención.
- **Alternativas descartadas:** Conexiones de escritura simultáneas sin coordinación (puede aumentar la contención); base de datos servidor para concurrencia (contradice el stack).
- **Cubre:** NFR-006

## Riesgos

- **Pérdida del resultado en memoria del buscador:** si `api-buscador` se reinicia, `ultima_pasada` desaparece. Mitigación: la ingesta no avanza el `timestamp` hasta recibir uno nuevo; no se requiere persistencia en `api-buscador`.
- **Contención en SQLite:** con WAL y `busy_timeout` se minimiza; la ingesta y la purga se programan para no solaparse sobre el mismo conjunto.
- **Esquema en versión futura:** `schema-migrator` aborta el arranque. Mitigación: las migraciones siempre avanzan hacia adelante y no se rebaja manualmente la versión sin coordinación.
- **Flag `interesada` no gestionado aún:** hasta que exista `api-candidaturas`, todas las ofertas cerradas se consideran no interesadas. Mitigación: la columna está reservada y documentada para que la feature futura active el comportamiento completo sin migración de esquema.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | ofertas-repository, persistencia-api | DEC-008 |
| REQ-002 | ofertas-repository | - |
| REQ-003 | ofertas-repository, ingestion-task | DEC-003 |
| REQ-004 | ofertas-repository | DEC-002 |
| REQ-005 | purge-task, ofertas-repository | DEC-002 |
| REQ-006 | purge-task, ofertas-repository | DEC-007 |
| REQ-007 | ofertas-repository, schema-migrator | - |
| REQ-008 | ofertas-repository, persistencia-api | - |
| REQ-009 | ofertas-repository, persistencia-api | - |
| REQ-010 | schema-migrator, db-connection | DEC-004 |
| REQ-011 | db-connection | DEC-001 |
| REQ-012 | persistencia-api, ofertas-repository | - |
| REQ-013 | seen-codes-importer, ofertas-repository | DEC-006 |
| REQ-014 | seen-codes-importer, ofertas-repository | DEC-006 |
| REQ-015 | seen-codes-importer, ofertas-repository, ingestion-task | DEC-003 |
| REQ-016 | persistencia-api, ofertas-repository | - |
| REQ-017 | ingestion-task, buscador-client, ofertas-repository | DEC-005 |
| REQ-018 | seen-codes-importer, ingestion-task, buscador-client | DEC-005, DEC-006 |
| NFR-001 | db-connection | DEC-001 |
| NFR-002 | db-connection | DEC-001 |
| NFR-003 | ofertas-repository | - |
| NFR-004 | ofertas-repository | - |
| NFR-005 | ofertas-repository | DEC-002 |
| NFR-006 | db-connection, ingestion-task, purge-task | DEC-008 |
| NFR-007 | ofertas-repository | - |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-persistencia.yaml` (nuevo) | Define las operaciones de persistencia expuestas al resto de módulos: crear/actualizar oferta, consultar por comunidad y código, listar vigentes y listar códigos vistos. Siguiendo la estrategia `implementation-first` de `.sdd/team.md`, el contrato se derivará de la implementación. |
| Configuración | `config/persistencia.yaml` (nuevo) | Configuración de la capa de persistencia: ruta de la BD, URL base del buscador, cadencia de ingesta y retención de purga. |

## Cambios sugeridos al mapa

- `+ Módulo: api-persistencia | source/api/persistencia | Capa de persistencia SQLite de ofertas | API`
- `+ Módulo: config-persistencia | config/persistencia.yaml | Configuración de BD, buscador e ingesta | -`
- `+ Módulo: db-connection | source/api/persistencia/connection.py | Conexión única SQLite con WAL y transacciones | config-persistencia`
- `+ Módulo: schema-migrator | source/api/persistencia/migrations.py | Migraciones secuenciales del esquema SQLite | db-connection`
- `+ Módulo: ofertas-repository | source/api/persistencia/repository.py | Lectura/escritura de ofertas por clave natural | db-connection`
- `+ Módulo: seen-codes-importer | source/api/persistencia/importer.py | Importación idempotente de data/seen_codes.json | ofertas-repository`
- `+ Módulo: buscador-client | source/api/persistencia/client.py | Cliente HTTP de consulta a /buscador/status | config-persistencia`
- `+ Módulo: ingestion-task | source/api/persistencia/ingestion.py | Ingesta periódica de ofertas desde el buscador | buscador-client, ofertas-repository`
- `+ Módulo: purge-task | source/api/persistencia/purge.py | Reducción periódica a registro mínimo | ofertas-repository`
- `+ Módulo: persistencia-api | source/api/persistencia/routes.py | Endpoints de persistencia para otros módulos | ofertas-repository`
- `+ Contrato: openapi | docs/contracts/openapi/api-persistencia.yaml | cliente -> api-persistencia`
- `+ Contrato: configuracion | config/persistencia.yaml | api-persistencia -> config-persistencia`
- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador y persistencia de ofertas | -`

## Estrategia de tests

- **Tests del repositorio:** operaciones de creación, actualización, consulta por clave natural, listado por estado y unicidad por `(comunidad, codigo)` sobre una base de datos SQLite temporal.
- **Tests de migraciones:** aplicación desde cero, idempotencia al arrancar sobre BD ya migrada, detección de versión futura y migración fallida.
- **Tests del importador:** lectura de `data/seen_codes.json`, idempotencia al repetir la importación, manejo de fichero ausente y JSON corrupto.
- **Tests del ingestor:** cliente HTTP mockeado con `httpx`, detección de `timestamp` nuevo, idempotencia por `timestamp`, actualización de registros `sin_ficha` a `vigente`, no sobrescritura con valores vacíos, y manejo de buscador caído, `error_global` y `ultima_pasada` nula.
- **Tests de purga:** ofertas cerradas que superan el plazo se reducen a registro mínimo conservando embedding; ofertas marcadas como interesadas no se purgan; ofertas dentro del plazo no se purgan.
- **Tests de idempotencia:** importación repetida de `seen_codes.json` e ingesta repetida del mismo `timestamp` no generan duplicados.
- **Fixtures:** base de datos temporal por test, ficheros JSON temporales y muestras del contrato HTML cuando sea necesario.

## Avisos

- SUP-002 define los campos de la tabla `ofertas` como "al menos"; las columnas `embedding_dim` e `interesada` son concreciones del diseño para la reconstrucción del embedding y la condición de purga, respectivamente.
- El flag `interesada` es un booleano reservado para `api-candidaturas` con valor por defecto `false`; no debe confundirse con los estados de candidatura (`me interesa`, `inscrito`, `entrevista`, `descartada`) que gestionará esa feature y que no se almacenan en este esquema.
- `api-buscador` no se modifica; la sincronización se resuelve exclusivamente desde `api-persistencia` leyendo `data/seen_codes.json` y consultando `GET /buscador/status`.
- El contrato HTML y `specs/api-buscador` mantienen `sector`, `nivel` y `contrato` vacíos (DEC-009); el esquema los conserva para no romper el histórico.
- La estrategia de contratos del equipo es `implementation-first`, por lo que el OpenAPI de `api-persistencia` se actualizará a partir del código una vez implementado.
