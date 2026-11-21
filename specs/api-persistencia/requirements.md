# Requisitos: api-persistencia

Estado: aprobado
Revisión: 5
Verificación: correcta

## Contexto

Esta feature entrega la capa de persistencia del proyecto: un esquema SQLite que guarda las ofertas extraídas por `api-buscador`, conserva el histórico de altas y cierres, prepara el almacenamiento de embeddings para el encaje futuro y garantiza que, tras la purga, sobreviva un registro mínimo útil para deduplicación y búsqueda semántica. Proporciona una API de persistencia que los demás módulos usarán para crear, consultar y actualizar ofertas, sin calcular embeddings, encaje ni digest. El alcance indicado por el usuario vincula esta feature con **FUN-003** (histórico), **FUN-006** (base del encaje con embeddings) y **FUN-011** (registro tras purga).

Dado que `api-buscador` ya está funcionando en producción local, está aprobado e implementado, y mantiene los códigos vistos en `data/seen_codes.json` (103 códigos de 12 dígitos como texto, sin más campos), `api-persistencia` debe leer e importar ese fichero de forma no invasiva: `api-buscador` sigue escribiéndolo exactamente como hace hoy, y la sincronización de códigos nuevos se resuelve desde la propia persistencia mediante importaciones repetibles e idempotentes.

Además, `api-buscador` expone `GET /buscador/status`, cuya respuesta incluye `ultima_pasada` con los campos `timestamp`, `comunidad`, `total_listado`, `error_global`, `errores_por_oferta` y `ofertas_nuevas`. Ese resultado vive solo en memoria del proceso, por lo que `api-persistencia` debe ingerir esas ofertas completas periódicamente y persistirlas, sin modificar `api-buscador`, sin lanzar pasadas nuevas y sin volver a descargar fichas del portal. La base de datos se convierte así en la fuente de verdad para el resto de módulos.

## Referencias

- `.sdd/project.md`: stack con SQLite en un único fichero y WAL, embeddings como BLOB sin base vectorial, similitud por fuerza bruta con numpy.
- `docs/product/producto.md`:
  - **FUN-003**: histórico de altas y cierres.
  - **FUN-006**: base del encaje con embeddings; esta feature solo prepara el esquema que almacenará los embeddings, sin calcularlos ni puntuar el encaje.
  - **FUN-011**: búsqueda semántica sobre el histórico; el embedding se guarda desde el origen y sobrevive a la purga.
  - **PDEC-016**: la ficha solo se pide una vez; el texto y el contacto se conservan mientras la oferta esté vigente y una semana más si no está marcada como interesada, reduciéndose después a un registro mínimo.
  - **PDEC-017**: comunidad y provincia forman parte del dato desde el principio.
  - **PDEC-019**: embeddings en SQLite como BLOB con nombre y versión del modelo; se conservan en el registro mínimo.
- `.sdd/architecture.md`: módulo `API` en `source/api/`, convenciones de códigos de oferta como texto y fechas en `dd/mm/aaaa`.
- `specs/api-buscador/requirements.md` (Revisión 5): campos reales de la ficha (número de oferta, ocupación, municipio, provincia, fechas de difusión, texto libre, contacto), decisión DEC-009 de mantener `sector`, `nivel` y `contrato` vacíos, y `data/seen_codes.json` como único estado de la feature y filtro de ofertas nuevas.
- `docs/contracts/html/empleacantabria/README.md`: estructura real de la ficha y formato de fechas.
- `data/seen_codes.json`: lista plana de 103 códigos de oferta de 12 dígitos como texto; es el estado vigente de `api-buscador` que debe migrarse.
- Código de `api-buscador`: `source/api/buscador/routes.py` expone `GET /buscador/status` con `ultima_pasada.ofertas_nuevas`; `source/api/buscador/coordinator.py` mantiene `_ultimo_resultado` solo en memoria del proceso.

## Decisiones de esquema propuestas

Las siguientes decisiones se toman como propuesta por defecto. Las que requieren validación explícita del usuario están recogidas como supuestos decisionales `pendientes` en la sección correspondiente.

- **Fichero SQLite único con WAL**: `data/job_emcan.db`.
- **Tabla principal `ofertas`** con, al menos, los campos necesarios para identificar la oferta, su procedencia, su estado, su contenido textual, su contacto y su embedding.
- **Clave natural**: la pareja `(comunidad, codigo)` debe ser única; `codigo` se almacena como texto de 12 dígitos.
- **Campos obligatorios en el registro mínimo**: comunidad, provincia, código, ocupación, municipio, sector, nivel, contrato (mantenidos en el modelo pero vacíos según DEC-009), fechas de difusión, estado y embedding (con modelo y versión). Tras la purga, `texto_libre` y `contacto` quedarán vacíos.
- **Embeddings**: se almacenan como BLOB junto con el nombre y la versión del modelo que los generó, por fila.
- **Versionado del esquema**: tabla `schema_version` con número de versión entero y marcas de tiempo; migraciones secuenciales aplicadas de forma transaccional.
- **Índices propuestos**: restricción única sobre `(comunidad, codigo)`, e índices sobre `(estado, fecha_fin_difusion)` y sobre los metadatos del modelo de embeddings.
- **Distinguir ficha descargada**: se usa el campo `estado` (`sin_ficha` para códigos importados solo desde `data/seen_codes.json`, `vigente` para ofertas con ficha ingerida, `cerrada` para ofertas cerradas); no se añade un campo booleano `ficha_descargada`.
- **Ingesta de fichas completas**: lectura periódica de `GET /buscador/status` e importación de `ultima_pasada.ofertas_nuevas`, sin lanzar pasadas ni descargar fichas.
- **Política de purga por defecto**: una vez cerrada la oferta, si transcurridos 7 días no ha sido marcada como interesada, el sistema reducirá el registro a los campos mínimos, manteniendo el embedding.

## Fuera de alcance

- Descarga, parseo o reintento de fichas del buscador HTML (cubierto por `api-buscador`).
- Descarga o parseo del PDF de difusión (cubierto por `api-pdf-parser`).
- Detección de ofertas nuevas o cerradas, ni lógica de histórico (cubierto por `api-historico`).
- Cálculo de embeddings, puntuación de encaje, inferencia con modelos locales o generación de digest (cubiertos por `api-encaje` y `api-digest`).
- Estados de candidatura (`me interesa`, `inscrito`, `entrevista`, `descartada`), notas y recordatorios (cubierto por `api-candidaturas`).
- Autenticación en la API.
- Ampliación del comportamiento a comunidades distintas de Cantabria; el esquema sí admite otros valores de comunidad/provincia para no rehacer datos en el futuro.
- Uso de una base de datos servidor, de una base vectorial o de cualquier extensión de SQLite para vectores.
- Modificación del código, los requisitos o el comportamiento de `api-buscador`; la compatibilidad se resuelve exclusivamente desde `api-persistencia`.
- Lanzar nuevas pasadas del buscador o descargar fichas del portal desde `api-persistencia`; la ingesta se realiza consultando el estado ya publicado por `api-buscador`.

## Requisitos funcionales

### REQ-001 Crear o actualizar una oferta

- **Requisito:** Cuando un módulo externo entrega los datos de una oferta, el sistema deberá crear el registro si no existe o actualizarlo si ya existe, identificándolo por su comunidad y su código.
- **Criterios de aceptación:**
  - Dada una oferta cuya combinación `(comunidad, codigo)` no existe, cuando se pide persistir, entonces se crea un nuevo registro con todos los campos recibidos.
  - Dada una oferta cuya combinación `(comunidad, codigo)` ya existe, cuando se pide persistir, entonces se actualizan los campos modificables sin duplicar la fila.
  - Dada una actualización, cuando finaliza la operación, entonces queda registrada la fecha y hora de última modificación.

### REQ-002 Almacenar los campos estructurales de la ficha

- **Requisito:** El sistema deberá almacenar, como mínimo, los campos que publica la ficha del buscador: comunidad, provincia, código de oferta, ocupación, municipio, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto. Los campos `sector`, `nivel` y `contrato` se mantendrán en el modelo pero se almacenarán vacíos, conforme a DEC-009.
- **Criterios de aceptación:**
  - Dada una oferta parseada por `api-buscador`, cuando se persiste, entonces se guardan comunidad, provincia, código, ocupación, municipio, fechas de difusión, texto libre y contacto.
  - Dado que la ficha no publica `sector`, `nivel` ni `contrato`, cuando se persiste la oferta, entonces esos campos se almacenan vacíos y no se inferen de otro campo.

### REQ-003 Almacenar el estado de vigencia

- **Requisito:** El sistema deberá almacenar el estado de vigencia de cada oferta (`vigente`, `cerrada` o el valor acordado para registros importados sin ficha, por ejemplo `sin_ficha`), y deberá conservar la fecha/hora del cierre cuando pase a `cerrada`.
- **Criterios de aceptación:**
  - Dada una oferta creada a partir de una ficha parseada, cuando se persiste, entonces su estado inicial es `vigente` y se registra la fecha/hora de alta.
  - Dado un código migrado desde `data/seen_codes.json` sin datos de ficha, cuando se persiste, entonces su estado refleja que no se dispone de ficha (por ejemplo, `sin_ficha`) hasta que se complete o se cierre.
  - Dada una oferta vigente, cuando un módulo externo indica su cierre, entonces el estado pasa a `cerrada` y se registra la fecha/hora de cierre.
  - Dado el cierre de una oferta, cuando se consulta posteriormente, entonces se puede observar tanto la fecha de fin de difusión publicada por el portal como la fecha/hora en que el sistema registró el cierre.

### REQ-004 Almacenar embeddings con modelo y versión

- **Requisito:** El sistema deberá almacenar el embedding de una oferta como un BLOB, junto con el nombre y la versión del modelo que lo generó.
- **Criterios de aceptación:**
  - Dada una oferta y su embedding, cuando se persiste, entonces el BLOB se guarda en la misma fila que la oferta.
  - Dado un embedding almacenado, cuando se consulta, entonces se recuperan también el nombre y la versión del modelo asociados.
  - Dado que una oferta aún no tiene embedding, cuando se consulta, entonces el campo de embedding es nulo y la oferta sigue siendo válida.

### REQ-005 Conservar el embedding tras la purga

- **Requisito:** Cuando una oferta se reduce a registro mínimo, el sistema deberá conservar su embedding y los metadatos del modelo.
- **Criterios de aceptación:**
  - Dada una oferta con embedding que cumple las condiciones de purga, cuando se ejecuta la reducción, entonces el BLOB del embedding y el nombre y versión del modelo permanecen en la base de datos.
  - Dado el registro mínimo resultante, cuando se consulta, entonces el embedding sigue disponible para cálculos de similitud futuros.

### REQ-006 Reducir una oferta a registro mínimo tras la purga

- **Requisito:** Cuando una oferta cerrada o finalizada cumple la política de retención sin haber sido marcada como interesada, el sistema deberá eliminar el texto libre y el contacto, conservando únicamente el registro mínimo necesario para histórico, deduplicación y búsqueda semántica.
- **Criterios de aceptación:**
  - Dada una oferta cerrada no interesante que ha superado el plazo de retención, cuando se ejecuta la purga, entonces `texto_libre` y `contacto` quedan nulos o vacíos.
  - Dado el mismo registro tras la purga, cuando se consultan sus campos, entonces siguen presentes comunidad, provincia, código, ocupación, municipio, sector, nivel y contrato (mantenidos en el modelo pero vacíos según DEC-009), fechas de difusión, estado, embedding y metadatos del modelo.

### REQ-007 Garantizar la unicidad por comunidad y código

- **Requisito:** El sistema deberá garantizar que no puede haber dos ofertas con la misma combinación de comunidad y código.
- **Criterios de aceptación:**
  - Dada una base de datos con una oferta de Cantabria y código `062026003633`, cuando se intenta insertar otra oferta de Cantabria con el mismo código, entonces la operación se resuelve como actualización o se rechaza, sin crear un segundo registro.
  - Dada la misma situación con una comunidad distinta y el mismo código, cuando se persiste, entonces se permite porque la unicidad aplica a la pareja `(comunidad, codigo)`.

### REQ-008 Consultar una oferta por comunidad y código

- **Requisito:** El sistema deberá permitir consultar una oferta a partir de su comunidad y su código.
- **Criterios de aceptación:**
  - Dada una oferta almacenada, cuando se consulta por `(comunidad, codigo)`, entonces se devuelven todos sus campos persistidos.
  - Dada una consulta por `(comunidad, codigo)` que no existe, cuando se resuelve, entonces se indica explícitamente que no se encontró la oferta.

### REQ-009 Listar ofertas vigentes

- **Requisito:** El sistema deberá permitir listar las ofertas cuyo estado sea `vigente`.
- **Criterios de aceptación:**
  - Dada una base de datos con ofertas vigentes y cerradas, cuando se solicita el listado de vigentes, entonces el resultado contiene únicamente las ofertas con estado `vigente`.
  - Dado el listado de vigentes, cuando se revisa, entonces incluye al menos comunidad, provincia, código, ocupación, municipio y fechas de difusión.

### REQ-010 Mantener un control de versiones del esquema

- **Requisito:** El sistema deberá llevar un control de versiones del esquema de la base de datos y aplicar las migraciones necesarias para que el fichero SQLite esté siempre en la versión esperada.
- **Criterios de aceptación:**
  - Dada una base de datos recién creada, cuando finaliza la inicialización, entonces existe una tabla de versiones que indica la versión actual del esquema.
  - Dada una base de datos en una versión anterior, cuando se inicia la aplicación, entonces se aplican las migraciones pendientes de forma secuencial y transaccional.
  - Dado un fichero SQLite ya en la versión esperada, cuando se inicia la aplicación, entonces no se reejecutan migraciones ya aplicadas.

### REQ-011 Usar un único fichero SQLite con WAL

- **Requisito:** El sistema deberá usar un único fichero SQLite como base de datos, con el modo de registro anticipado (WAL) activado.
- **Criterios de aceptación:**
  - Dada una instalación nueva, cuando se inicializa la persistencia, entonces se crea un único fichero `.db` en la ruta configurada.
  - Dada la base de datos creada, cuando se consulta el modo de diario, entonces el resultado es `wal`.

### REQ-012 Exponer operaciones de persistencia al resto de módulos

- **Requisito:** El sistema deberá exponer operaciones de lectura y escritura de ofertas al resto de módulos a través de una API de persistencia, sin obligar a esos módulos a conocer el esquema SQL subyacente.
- **Criterios de aceptación:**
  - Dado un módulo que consume la API de persistencia, cuando crea o actualiza una oferta, entonces solo proporciona los datos de la oferta y recibe confirmación o el registro actualizado.
  - Dado un módulo que consume la API de persistencia, cuando consulta una oferta, entonces recibe una estructura de datos que incluye los campos definidos en REQ-002 sin necesidad de ejecutar SQL directamente.

### REQ-013 Migrar los códigos vistos desde `data/seen_codes.json`

- **Requisito:** Cuando se inicializa la persistencia en un entorno que ya contiene `data/seen_codes.json`, el sistema deberá ofrecer una operación de importación idempotente que lea el fichero tal como lo escribe `api-buscador` y cree un registro por cada código visto, sin necesidad de descargar de nuevo su ficha.
- **Criterios de aceptación:**
  - Dado un `data/seen_codes.json` con 103 códigos, cuando se ejecuta la importación, entonces se crean 103 registros en la base de datos con esos códigos, uno por código.
  - Dado un código importado, cuando se consulta su estado de "visto", entonces la base de datos lo reconoce como visto.
  - Dada la importación, cuando finaliza, entonces el sistema deja constancia del número de códigos importados (por ejemplo, en un log, en la respuesta de la operación o en una tabla de auditoría).

### REQ-014 Idempotencia y repetibilidad de la importación desde `data/seen_codes.json`

- **Requisito:** La importación desde `data/seen_codes.json` deberá poder ejecutarse varias veces sin duplicar registros y sin perder datos, de modo que los códigos nuevos que el buscador añada al fichero tras una pasada se incorporen a la base de datos.
- **Criterios de aceptación:**
  - Dada una base de datos que ya contiene los códigos importados, cuando se vuelve a ejecutar la importación con el mismo JSON, entonces no se crean duplicados y el contador de importados indica cero.
  - Dado un `data/seen_codes.json` al que `api-buscador` ha añadido nuevos códigos entre dos ejecuciones, cuando se vuelve a importar, entonces solo se crean registros para los códigos que aún no existen en la base de datos.

### REQ-015 Distinguir ofertas con ficha descargada de códigos migrados mediante el estado

- **Requisito:** El sistema deberá distinguir, en el esquema de ofertas, entre un código que solo se ha visto (importado desde `data/seen_codes.json`) y una oferta cuya ficha completa ha sido ingerida, usando únicamente el campo `estado`.
- **Criterios de aceptación:**
  - Dado un registro importado desde `data/seen_codes.json`, cuando se consulta, entonces su estado es `sin_ficha`.
  - Dada una oferta ingerida con los datos completos de una pasada, cuando se consulta, entonces su estado pasa a `vigente`.
  - Dado un código visto sin ficha (estado `sin_ficha`), cuando ya consta en la base de datos, entonces la persistencia lo trata como ya visto y no fuerza una nueva descarga.

### REQ-016 Exponer la lista de códigos vistos

- **Requisito:** El sistema deberá exponer, a través de la API de persistencia, la lista de códigos vistos para una comunidad, de modo que otros módulos puedan usarla como filtro de ofertas nuevas.
- **Criterios de aceptación:**
  - Dada una comunidad configurada, cuando se solicita la lista de códigos vistos, entonces se devuelven todos los códigos de esa comunidad, tanto los importados desde `data/seen_codes.json` como los procedentes de fichas completas importadas.
  - Dada la lista devuelta, cuando un módulo la usa para filtrar, entonces identifica correctamente las ofertas nuevas como aquellas cuyo código no está en la lista.

### REQ-017 Ingerir ofertas completas desde `GET /buscador/status`

- **Requisito:** El sistema deberá consultar periódicamente `GET /buscador/status` del buscador ya desplegado, detectar cuando `ultima_pasada` contiene un `timestamp` no importado previamente, y persistir las ofertas de `ultima_pasada.ofertas_nuevas` que hayan sido parseadas correctamente, todo ello sin modificar `api-buscador`, sin lanzar pasadas nuevas y sin descargar fichas del portal.
- **Criterios de aceptación:**
  - Dado que `GET /buscador/status` devuelve una `ultima_pasada` con un `timestamp` nuevo y una lista `ofertas_nuevas`, cuando se ejecuta la ingesta, entonces cada oferta se almacena con comunidad, provincia, código, ocupación, municipio, fechas de difusión, texto libre, contacto y los campos vacíos de `sector`, `nivel` y `contrato`, con estado `vigente`.
  - Dado que se vuelve a consultar `GET /buscador/status` con el mismo `timestamp`, cuando se ejecuta la ingesta, entonces no se duplican registros ni se marcan ofertas como importadas de nuevo.
  - Dado un código previamente importado solo desde `data/seen_codes.json` (estado `sin_ficha`), cuando aparece en `ultima_pasada.ofertas_nuevas`, entonces el registro se completa con los datos de la ficha y su estado pasa a `vigente`, sin crear un duplicado.
  - Dado un código que ya existe en la base de datos con estado `vigente`, cuando aparece de nuevo en `ultima_pasada.ofertas_nuevas`, entonces no se duplica ni se sobrescriben sus datos con valores vacíos.
  - Dado que `ultima_pasada` no está disponible, devuelve un `error_global` o el buscador no responde, cuando se ejecuta la ingesta, entonces no se persisten ofertas y se deja constancia del estado consultado.
  - Dado que `api-buscador` se reinicia y pierde `_ultimo_resultado`, cuando `GET /buscador/status` devuelve `ultima_pasada` a `null`, entonces la ingesta no marca como importado ningún resultado anterior y espera a una nueva pasada.

### REQ-018 Sincronizar códigos vistos leyendo `data/seen_codes.json` e ingerir fichas completas desde `GET /buscador/status`

- **Requisito:** El sistema deberá mantener la sincronización de códigos vistos leyendo periódicamente o bajo demanda el fichero `data/seen_codes.json` que `api-buscador` sigue escribiendo, y deberá ingerir las fichas completas consultando `GET /buscador/status`, sin que `api-buscador` deje de actualizar el JSON ni se le exija escribir en la base de datos.
- **Criterios de aceptación:**
  - Dado que `api-buscador` finaliza una pasada y añade códigos a `data/seen_codes.json`, cuando `api-persistencia` ejecuta la importación, entonces esos códigos nuevos aparecen en la base de datos.
  - Dado que `api-buscador` expone una `ultima_pasada` con ofertas nuevas, cuando `api-persistencia` ejecuta la ingesta, entonces esas ofertas se almacenan con todos sus campos y su estado pasa a `vigente`.
  - Dado que la base de datos es la fuente de verdad para otros módulos, cuando se consulta el estado de un código, entonces la respuesta proviene de la base de datos.
  - Dado que `api-buscador` no se modifica, cuando se revisa `data/seen_codes.json` tras una pasada, entonces sigue conteniendo los códigos escritos por `api-buscador` y no se ha alterado desde `api-persistencia`.

## Requisitos no funcionales

### NFR-001 Base de datos SQLite sin servidor

- **Requisito:** El sistema deberá usar SQLite como única base de datos, sin depender de un servidor de base de datos externo.
- **Criterios de aceptación:**
  - Dado el entorno de ejecución, cuando se inicializa la persistencia, entonces no se inicia ni se requiere conexión a un servidor PostgreSQL, MySQL ni similar.

### NFR-002 WAL activado

- **Requisito:** El sistema deberá activar el modo WAL en el fichero SQLite durante la inicialización.
- **Criterios de aceptación:**
  - Dada la base de datos inicializada, cuando se ejecuta `PRAGMA journal_mode`, entonces el valor devuelto es `wal`.

### NFR-003 Códigos de oferta como texto

- **Requisito:** El sistema deberá almacenar los códigos de oferta como texto, sin convertirlos a número entero.
- **Criterios de aceptación:**
  - Dado un código de oferta de 12 dígitos que empiece por cero, cuando se persiste, entonces se conservan todos los dígitos, incluidos los ceros iniciales.

### NFR-004 Fechas de difusión en formato `dd/mm/aaaa`

- **Requisito:** El sistema deberá almacenar y devolver las fechas de inicio y fin de difusión en formato `dd/mm/aaaa`.
- **Criterios de aceptación:**
  - Dada una fecha de difusión `21/11/2026`, cuando se persiste, entonces se almacena exactamente como `21/11/2026`.
  - Dada una oferta con fecha de difusión, cuando se consulta, entonces el valor devuelto sigue el formato `dd/mm/aaaa`.

### NFR-005 Sin base vectorial

- **Requisito:** El sistema no deberá usar una base de datos vectorial ni una extensión vectorial de SQLite para almacenar o consultar embeddings.
- **Criterios de aceptación:**
  - Dado el esquema de la base de datos, cuando se revisan las dependencias y el esquema, entonces no existe tabla ni extensión de búsqueda vectorial; los embeddings se almacenan como BLOB en la tabla de ofertas.

### NFR-006 Serialización de escrituras concurrentes

- **Requisito:** El sistema deberá garantizar que dos escrituras simultáneas sobre la misma base de datos no corrompen los datos ni generan registros duplicados.
- **Criterios de aceptación:**
  - Dadas dos operaciones de escritura concurrentes sobre la misma oferta, cuando ambas finalizan, entonces el resultado es equivalente a haberlas ejecutado una tras otra, sin duplicados.

### NFR-007 Esquema preparado para varias comunidades

- **Requisito:** El esquema deberá admitir ofertas de distintas comunidades sin cambios estructurales.
- **Criterios de aceptación:**
  - Dadas dos ofertas con comunidades distintas y el mismo código, cuando se persisten, entonces se almacenan como registros independientes.

## Supuestos

### SUP-001 Ruta y nombre del fichero SQLite

- **Tipo:** decisional
- **Descripción:** La base de datos será un único fichero SQLite ubicado en `data/job_emcan.db` (ruta relativa a la raíz del proyecto). El directorio `data/` se creará si no existe.
- **Impacto:** REQ-011, NFR-001.
- **Estado:** validado

### SUP-002 Esquema propuesto de la tabla `ofertas`

- **Tipo:** decisional
- **Descripción:** Se propone una tabla `ofertas` con los siguientes campos lógicos: comunidad, provincia, código, ocupación, municipio, sector, nivel, contrato, fecha_inicio_difusion, fecha_fin_difusion, estado, texto_libre, contacto, embedding (BLOB), embedding_model_name, embedding_model_version, fecha_alta, fecha_cierre y fecha_ultima_actualizacion. El identificador técnico será un `rowid` autoincremental; la clave de negocio será la pareja `(comunidad, codigo)` con restricción única.
- **Impacto:** REQ-002, REQ-007, REQ-008.
- **Estado:** validado

### SUP-003 Control de versiones del esquema

- **Tipo:** decisional
- **Descripción:** Se propone una tabla `schema_version(version INTEGER PRIMARY KEY, applied_at TEXT)` y migraciones numeradas secuencialmente. Cada migración se aplicará dentro de una transacción; la versión actual se consultará al arrancar.
- **Impacto:** REQ-010.
- **Estado:** validado

### SUP-004 Política de purga por defecto

- **Tipo:** decisional
- **Descripción:** Cuando una oferta pasa a estado `cerrada`, si tras 7 días naturales no ha sido marcada como interesada, se reducirá a registro mínimo: `texto_libre` y `contacto` pasarán a nulos y el resto de campos se conservarán, incluido el embedding. Esta propuesta es coherente con PDEC-016.
- **Impacto:** REQ-005, REQ-006.
- **Estado:** validado

### SUP-005 Unicidad por comunidad y código

- **Tipo:** decisional
- **Descripción:** La unicidad de una oferta se define por la combinación `(comunidad, codigo)`. El mismo código podría repetirse en comunidades distintas sin conflicto.
- **Impacto:** REQ-007.
- **Estado:** validado

### SUP-006 Embeddings con modelo y versión por fila

- **Tipo:** contextual
- **Descripción:** Cada embedding se guarda en la fila de su oferta junto con el nombre y la versión del modelo que lo generó, conforme a PDEC-019. Si en el futuro cambia el modelo, las ofertas antiguas conservan los metadatos del modelo original.
- **Impacto:** REQ-004, REQ-005.
- **Estado:** validado

### SUP-007 Códigos como texto y fechas `dd/mm/aaaa`

- **Tipo:** contextual
- **Descripción:** Los códigos de oferta se tratan como texto y las fechas de difusión se expresan en `dd/mm/aaaa`, siguiendo las convenciones de `.sdd/architecture.md` y el contrato HTML.
- **Impacto:** REQ-002, NFR-003, NFR-004.
- **Estado:** validado

### SUP-008 API de persistencia sin autenticación

- **Tipo:** contextual
- **Descripción:** La API de persistencia se consume en local y sin autenticación, al igual que el resto de módulos del proyecto en esta fase.
- **Impacto:** REQ-012.
- **Estado:** validado

### SUP-009 Estados de candidatura fuera de esta feature

- **Tipo:** contextual
- **Descripción:** Los estados de seguimiento de candidaturas (`me interesa`, `inscrito`, `entrevista`, `descartada`), notas y recordatorios no se persisten en esta feature; se reservan para `api-candidaturas`. `api-persistencia` solo guarda el estado de vigencia de la oferta (`vigente`, `cerrada` o `sin_ficha` para códigos importados sin ficha).
- **Impacto:** Delimita el alcance frente al seguimiento de candidaturas; complementa REQ-003.
- **Estado:** validado

### SUP-010 Índices propuestos

- **Tipo:** decisional
- **Descripción:** Se proponen los siguientes índices: restricción única sobre `(comunidad, codigo)`, índice sobre `(estado, fecha_fin_difusion)` para consultar ofertas vigentes/cerradas, e índice sobre `(embedding_model_name, embedding_model_version)` para facilitar operaciones futuras sobre embeddings.
- **Impacto:** REQ-009, REQ-010, rendimiento de consultas.
- **Estado:** validado

### SUP-011 Valores por defecto para registros migrados desde `data/seen_codes.json`

- **Tipo:** decisional
- **Descripción:** Para cada código importado desde `data/seen_codes.json` se creará un registro con: comunidad `Cantabria`, provincia vacía, estado `sin_ficha`, fechas de difusión vacías, `sector`, `nivel` y `contrato` vacíos, `texto_libre` y `contacto` vacíos, sin embedding. Estos valores son provisionales porque el JSON solo aporta el código. Los códigos que no empiezan por `06` (por ejemplo, `162026011705` y `162026012828`) también se importan como comunidad `Cantabria`, ya que proceden del listado del portal.
- **Impacto:** REQ-013, REQ-015, REQ-017.
- **Estado:** validado

### SUP-012 Campo para distinguir ficha descargada

- **Tipo:** decisional
- **Descripción:** Descartado. No se añade un campo booleano `ficha_descargada` al esquema. La distinción entre un código importado solo desde `data/seen_codes.json` y una oferta cuya ficha completa ha sido ingerida se realiza mediante el campo `estado`: `sin_ficha` para los registros importados sin ficha, `vigente` para las ofertas con ficha ingerida, y `cerrada` cuando se indique su cierre. Se descarta el booleano para evitar mantener dos fuentes de verdad sobre el mismo concepto.
- **Impacto:** Ninguno; REQ-015, REQ-016 y REQ-017 usan el campo `estado`.
- **Estado:** descartado

### SUP-013 `api-buscador` no se modifica; la compatibilidad se resuelve en persistencia

- **Tipo:** contextual
- **Descripción:** `api-buscador` permanece aprobado e implementado según `specs/api-buscador/requirements.md` (Revisión 5). No se modifica su código, sus especificaciones ni su comportamiento: sigue escribiendo `data/seen_codes.json` como lista plana de códigos y devolviendo el resultado de cada pasada en `GET /buscador/status`. `api-persistencia` lee e importa ese fichero de forma no invasiva e ingiere las fichas completas consultando el endpoint; la sincronización y la integración se resuelven desde el lado de la persistencia.
- **Impacto:** REQ-013, REQ-014, REQ-016, REQ-017, REQ-018.
- **Estado:** validado

### SUP-014 Ingesta de ofertas completas dentro de `api-persistencia`

- **Tipo:** decisional
- **Descripción:** La ingesta de las ofertas completas forma parte de `api-persistencia`. Se realiza consultando `GET /buscador/status` del buscador ya desplegado y persistiendo las ofertas de `ultima_pasada.ofertas_nuevas`. No se modifica `api-buscador`, no se lanzan pasadas nuevas ni se descargan fichas del portal.
- **Impacto:** REQ-017, REQ-018.
- **Estado:** validado

### SUP-015 Cadencia y detección de pasada nueva para la ingesta

- **Tipo:** decisional
- **Descripción:** La ingesta ejecuta un ciclo periódico configurable (por defecto cada 5 minutos) que consulta `GET /buscador/status`. Solo importa cuando el `timestamp` de `ultima_pasada` es distinto del último timestamp ya importado. Si el `timestamp` es el mismo, la ingesta no hace nada. Si `ultima_pasada` es `null`, el buscador no responde o hay un `error_global`, la ingesta omite la importación y espera al siguiente ciclo.
- **Impacto:** REQ-017, REQ-018.
- **Estado:** validado

## Preguntas abiertas

Ninguna.

## Trazabilidad

| Requisito | Funcionalidad de producto | Decisión de producto |
|---|---|---|
| REQ-001 | FUN-003 | PDEC-003 |
| REQ-002 | FUN-001, FUN-003 | PDEC-017, DEC-009 |
| REQ-003 | FUN-003 | PDEC-014 |
| REQ-004 | FUN-006, FUN-011 | PDEC-019 |
| REQ-005 | FUN-011 | PDEC-019 |
| REQ-006 | FUN-003, FUN-011 | PDEC-016 |
| REQ-007 | FUN-003 | PDEC-017 |
| REQ-008 | FUN-002, FUN-003 | PDEC-003 |
| REQ-009 | FUN-002 | PDEC-014 |
| REQ-010 | FUN-003 | PDEC-003 |
| REQ-011 | FUN-003, FUN-011 | PDEC-003 |
| REQ-012 | FUN-001, FUN-003 | PDEC-003 |
| NFR-001 | - | PDEC-003, PDEC-019 |
| NFR-002 | - | PDEC-003 |
| NFR-003 | - | Convención de arquitectura |
| NFR-004 | - | Convención de arquitectura, contrato HTML |
| NFR-005 | - | PDEC-019 |
| NFR-006 | - | PDEC-003 |
| NFR-007 | FUN-015 | PDEC-017 |
| REQ-013 | FUN-003 | PDEC-003, SUP-011 |
| REQ-014 | FUN-003 | PDEC-003, SUP-013 |
| REQ-015 | FUN-003 | PDEC-003, SUP-011 |
| REQ-016 | FUN-001, FUN-003 | PDEC-003, SUP-013 |
| REQ-017 | FUN-001, FUN-003 | PDEC-003, SUP-014, SUP-015 |
| REQ-018 | FUN-003 | PDEC-003, SUP-013, SUP-014, SUP-015 |
