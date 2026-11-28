# Diseño: api-perfil

Estado: aprobado
Revisión: 3
Basado en: requirements@2
Verificación: correcta

## Resumen

`api-perfil` añade al módulo `API` un perfil de búsqueda único, versionado e inmutable, almacenado en un segundo fichero SQLite propio (`data/job_emcan_perfil.db`) con WAL y `busy_timeout`, gestionado por su propio migrador. Expone endpoints bajo `/perfil` para consultar el perfil activo, el historial, una versión concreta, crear una nueva versión, hacer rollback y validar un borrador sin guardar. Usa control optimista por `version_base`, normaliza las listas sin distinguir mayúsculas ni tildes conservando la forma escrita, y no modifica ninguna feature aprobada ni el fichero `data/job_emcan.db`.

## Supuestos sobre el sistema actual

- La API FastAPI vive en `source/api/`, arranca en `source/api/main.py` y ya registra routers de `api-buscador`, `api-persistencia`, `api-historico`, `api-integridad` y `api-listado`.
- `api-persistencia` es dueño exclusivo de `data/job_emcan.db` y de su tabla `schema_version`; `api-perfil` no las toca.
- `api-historico` ya validó el patrón de un segundo fichero SQLite propio (`data/job_emcan_historico.db`) con migrador, WAL y `busy_timeout` propios; `api-perfil` reutiliza ese criterio.
- `api-encaje`, `api-digest`, `api-consulta-puntual` y `app-interfaz` aún no existen; `api-perfil` solo publica la versión activa para que futuros consumidores la referencien de forma estable.
- La estrategia de contratos del equipo es `implementation-first`: el OpenAPI y el YAML de configuración se derivarán de la implementación.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que valida la configuración del perfil, aplica sus migraciones al arrancar y registra el router de `perfil-api`. | existente (se extiende) |
| config-perfil | Fichero YAML con la ruta del fichero SQLite, `busy_timeout`, límites de validación y tamaño máximo de payload. | nuevo |
| db-connection-perfil | Abre y cierra una conexión SQLite por operación, configurando WAL, `busy_timeout` y `foreign_keys` en cada una. | nuevo |
| schema-migrator-perfil | Controla la versión del esquema del fichero propio y aplica migraciones secuenciales transaccionales. | nuevo |
| perfil-repository | Lee y escribe versiones y el puntero de activa; garantiza atomicidad y monotonicidad. | nuevo |
| perfil-normalizer | Normaliza listas (`trim`, descarte de vacíos, deduplicación insensible a mayúsculas y tildes) conservando la forma escrita. | nuevo |
| perfil-validator | Valida contenido mínimo, longitudes, caracteres de control, duplicados y tamaño del payload; compara con la versión activa para detectar "sin cambios". | nuevo |
| perfil-api | Endpoints bajo `/perfil`: consultar activo, historial, versión concreta, crear versión, rollback y validación previa. | nuevo |

## Flujo principal

1. Al arrancar `api-service`, `schema-migrator-perfil` abre `data/job_emcan_perfil.db`, activa WAL, `busy_timeout` y `foreign_keys`, y aplica las migraciones pendientes de forma secuencial y transaccional.
2. `api-service` registra el router de `perfil-api` en la aplicación FastAPI.
3. Un cliente consulta el perfil activo con `GET /perfil/activo`; si `perfil_activo` no tiene fila, `perfil-api` devuelve 200 con `perfil: null` y `version_activa: 0`.
4. Para guardar cambios, el cliente envía un borrador con `version_base` y los campos del perfil a `POST /perfil/versiones`. Si no existe ninguna versión, el único `version_base` aceptado es `0`; cualquier otro valor se rechaza con conflicto.
5. `perfil-api` rechaza payloads mayores de 1 MB y delega en `perfil-validator`.
6. `perfil-validator` valida los campos y `perfil-normalizer` los normaliza; si hay errores, se devuelven sin crear versión.
7. `perfil-validator` compara el contenido normalizado con la versión activa; si es idéntico, se devuelve 409 indicando "sin cambios" sin crear versión.
8. `perfil-repository` abre una conexión, inicia una transacción de escritura, comprueba que `version_base` coincide con la versión activa, inserta la nueva fila en `perfil_version` (el propio SQLite asigna `n+1` mediante `AUTOINCREMENT`), actualiza o inserta el puntero en `perfil_activo` y confirma.
9. Si todo es correcto, se cierra la conexión; en caso de error, se deshace la transacción, se cierra la conexión y la versión activa no cambia.
10. El cliente recibe el número de la nueva versión activa y sus campos.
11. Para un rollback, el cliente envía `version_objetivo` y `version_base` a `POST /perfil/rollback`; el sistema copia el contenido de la versión objetivo a `n+1` y activa la nueva versión.

## Flujos alternativos y de fallo

### ALT-001 Perfil activo no existe

- **Condición:** Se consulta el perfil activo o el historial y `perfil_activo` no contiene ninguna fila.
- **Comportamiento:** `GET /perfil/activo` devuelve 200 con `perfil: null` y `version_activa: 0`. `GET /perfil/versiones` devuelve 200 con `version_activa: 0` y `versiones: []`.
- **Responsable:** perfil-api
- **Resultado:** El cliente distingue la ausencia de perfil de un error de servidor, facilitando el consumo futuro por `api-encaje`.
- **Cubre:** REQ-008, REQ-009, REQ-020, REQ-021

### ALT-002 Versión solicitada no existe o parámetro inválido

- **Condición:** En `GET /perfil/versiones/{version}`, el parámetro de ruta no es un entero válido o es menor que 1, o es un entero válido que no existe en `perfil_version`.
- **Comportamiento:** Si el parámetro no es un entero válido o es menor que 1, `perfil-api` devuelve 400 con el modelo de error común. Si el parámetro es válido pero no existe, devuelve 404.
- **Responsable:** perfil-api
- **Resultado:** No se crea ninguna versión nueva ni cambia la activa.
- **Cubre:** REQ-010

### ALT-003 Payload demasiado grande

- **Condición:** El cuerpo de la petición supera el límite configurado (1 MB por defecto).
- **Comportamiento:** `perfil-api` rechaza la petición antes de procesar los campos individuales, devolviendo 400 con el motivo del rechazo.
- **Responsable:** perfil-api
- **Resultado:** No se normaliza, valida ni persiste nada.
- **Cubre:** REQ-027, NFR-005

### ALT-004 Errores de validación

- **Condición:** El borrador incumple alguna regla de validación (contenido mínimo, longitud, caracteres de control, duplicados).
- **Comportamiento:** `perfil-validator` recopila todos los errores detectados y `perfil-api` devuelve 400 con la lista de errores.
- **Responsable:** perfil-validator
- **Resultado:** No se crea ninguna versión.
- **Cubre:** REQ-013, REQ-017, REQ-018, REQ-019

### ALT-005 Guardado sin cambios respecto a la versión activa

- **Condición:** Tras la normalización, el contenido a guardar es idéntico al de la versión activa.
- **Comportamiento:** `perfil-validator` lo detecta y `perfil-api` devuelve 409 indicando que el perfil activo ya contiene esos valores; no se crea versión.
- **Responsable:** perfil-validator
- **Resultado:** La versión activa permanece inalterada.
- **Cubre:** REQ-015

### ALT-006 Conflicto de concurrencia en escritura

- **Condición:** `version_base` es numérica pero no coincide con la versión activa actual dentro de la transacción.
- **Comportamiento:** `perfil-repository` detecta el conflicto y `perfil-api` devuelve 409.
- **Responsable:** perfil-repository
- **Resultado:** No se crea versión ni cambia la activa.
- **Cubre:** REQ-016

### ALT-007 `version_base` ausente o no numérica

- **Condición:** El cuerpo de escritura no incluye `version_base`, o su valor no es un entero válido.
- **Comportamiento:** `perfil-api` devuelve 400 indicando que `version_base` es obligatoria y debe ser un entero.
- **Responsable:** perfil-api
- **Resultado:** No se llega a validar el contenido ni a tocar la base de datos.
- **Cubre:** REQ-016

### ALT-008 Rollback a la versión ya activa

- **Condición:** Se solicita rollback a la misma versión que ya es la activa.
- **Comportamiento:** `perfil-api` devuelve 409 indicando que la versión solicitada ya es la activa; no se crea versión.
- **Responsable:** perfil-api
- **Resultado:** La versión activa no cambia.
- **Cubre:** REQ-026

### ALT-009 Primer guardado con `version_base` distinta de 0

- **Condición:** No existe ninguna versión y el cliente envía `version_base` distinta de `0`.
- **Comportamiento:** `perfil-repository` detecta que la base no es `0` y `perfil-api` devuelve 409 (conflicto, porque no hay versión activa sobre la que basarse).
- **Responsable:** perfil-repository
- **Resultado:** No se crea versión.
- **Cubre:** REQ-016, REQ-020

### ALT-010 Fallo de escritura o almacenamiento no disponible

- **Condición:** Se produce un error de disco, permisos, `SQLITE_BUSY` tras el tiempo de espera o cualquier fallo de SQLite durante la transacción.
- **Comportamiento:** La transacción se deshace y `perfil-api` devuelve 500 con un mensaje de error de almacenamiento.
- **Responsable:** perfil-repository
- **Resultado:** La versión activa no cambia y no queda una versión parcial.
- **Cubre:** REQ-025, NFR-002

### ALT-011 Fichero corrupto o versión de esquema futura al arrancar

- **Condición:** `schema-migrator-perfil` encuentra una versión de esquema mayor que la esperada, el fichero no es un SQLite válido o no se puede abrir.
- **Comportamiento:** Se registra el error crítico, se marca el perfil como no disponible y se registra el router igualmente; los endpoints de perfil devuelven 503 hasta que se resuelva el problema manualmente. El resto de la API sigue funcionando.
- **Responsable:** schema-migrator-perfil
- **Resultado:** No se sirven perfiles inconsistentes ni se aceptan operaciones sobre el perfil.
- **Cubre:** REQ-025, NFR-007

### ALT-012 Otra instancia tiene abierto el fichero de perfil

- **Condición:** Dos procesos intentan escribir en `data/job_emcan_perfil.db` al mismo tiempo.
- **Comportamiento:** SQLite serializa las escrituras con WAL; `busy_timeout` hace que el segundo escritor espere. Si el tiempo de espera se agota, la operación falla con 500 (ALT-010).
- **Responsable:** db-connection-perfil
- **Resultado:** No se generan versiones duplicadas ni corrupciones.
- **Cubre:** NFR-002, NFR-003

## API

No hay autenticación. Todas las respuestas de error (`400`, `404`, `409`, `500`, `503`) siguen el modelo común descrito al final de esta sección.

### Modelo de error común

```json
{
  "codigo": "VALIDACION_ERROR",
  "mensaje": "Descripción legible del error",
  "detalles": null
}
```

- `codigo`: identificador corto del error (por ejemplo, `VALIDACION_ERROR`, `PARAMETRO_INVALIDO`, `PERFIL_NO_ENCONTRADO`, `CONFLICTO_VERSION`, `ERROR_ALMACENAMIENTO`, `SERVICIO_NO_DISPONIBLE`).
- `mensaje`: descripción legible.
- `detalles`: `null` o información adicional según el error (por ejemplo, el motivo del rechazo de un payload demasiado grande).

Los errores de validación de contenido en `POST /perfil/versiones` y `POST /perfil/rollback` usan este mismo modelo común: `detalles` puede incluir la lista de campos con error. En `POST /perfil/validar`, en cambio, la validez del borrador es el resultado normal de la operación y se devuelve en un 200 con su propio esquema.

### `GET /perfil/activo`

Devuelve el perfil activo y el número de versión que lo identifica.

- **Parámetros:** ninguno.
- **Respuesta 200 (perfil existente):**
  ```json
  {
    "version_activa": 5,
    "perfil": {
      "sectores": ["Técnico", "Administración"],
      "municipios": ["Santander"],
      "provincias": ["Cantabria"],
      "contrato": ["Indefinido"],
      "jornada": ["Completa"],
      "palabras_clave": ["Python", "remoto"],
      "criterios": "Preferencia por puestos con posibilidad de teletrabajo."
    }
  }
  ```
- **Respuesta 200 (sin perfil):**
  ```json
  {
    "version_activa": 0,
    "perfil": null
  }
  ```
- **Errores:** `503` si el perfil no está disponible por fallo de inicialización.
- **Cubre:** REQ-008, REQ-020, REQ-021

### `GET /perfil/versiones`

Devuelve el historial completo de versiones ordenado por versión ascendente. Solo incluye metadatos; no el contenido completo de cada versión.

- **Parámetros:** ninguno.
- **Respuesta 200 (con versiones):**
  ```json
  {
    "version_activa": 5,
    "versiones": [
      {"version": 1, "creado_en": "2026-11-20T10:00:00Z", "activa": false},
      {"version": 2, "creado_en": "2026-11-21T11:30:00Z", "activa": false},
      {"version": 3, "creado_en": "2026-11-22T09:15:00Z", "activa": false},
      {"version": 4, "creado_en": "2026-11-23T16:45:00Z", "activa": false},
      {"version": 5, "creado_en": "2026-11-24T08:00:00Z", "activa": true}
    ]
  }
  ```
- **Respuesta 200 (sin perfil):**
  ```json
  {
    "version_activa": 0,
    "versiones": []
  }
  ```
- **Errores:** `503` si el perfil no está disponible.
- **Nota:** REQ-009 pide "al menos" número, marca temporal e indicación de activa; se cumple sin incluir el contenido. Si en el futuro se necesita el contenido en el historial, se añadiría sin romper el contrato.
- **Cubre:** REQ-009

### `GET /perfil/versiones/{version}`

Devuelve el contenido completo de una versión concreta.

- **Parámetros de ruta:** `version` (entero ≥ 1).
- **Respuesta 200:**
  ```json
  {
    "version": 3,
    "creado_en": "2026-11-22T09:15:00Z",
    "perfil": {
      "sectores": ["Técnico"],
      "municipios": ["Santander"],
      "provincias": ["Cantabria"],
      "contrato": ["Indefinido"],
      "jornada": ["Completa"],
      "palabras_clave": ["Python"],
      "criterios": ""
    }
  }
  ```
- **Errores:**
  - `400` si `version` no es un entero válido o es menor que 1.
  - `404` si la versión no existe.
  - `503` si el perfil no está disponible.
- **Cubre:** REQ-010

### `POST /perfil/versiones`

Crea una nueva versión a partir del borrador, la activa y la devuelve.

- **Cuerpo de petición:**
  ```json
  {
    "version_base": 5,
    "perfil": {
      "sectores": ["Técnico", "Administración"],
      "municipios": ["Santander", "Torrelavega"],
      "provincias": ["Cantabria"],
      "contrato": ["Indefinido"],
      "jornada": ["Completa"],
      "palabras_clave": ["Python", "remoto"],
      "criterios": "Preferencia por puestos con posibilidad de teletrabajo."
    }
  }
  ```
  - `version_base`: entero obligatorio. Para el primer guardado, cuando no existe perfil, debe ser `0`.
- **Respuesta 201:**
  ```json
  {
    "version_activa": 6,
    "perfil": {
      "sectores": ["Técnico", "Administración"],
      "municipios": ["Santander", "Torrelavega"],
      "provincias": ["Cantabria"],
      "contrato": ["Indefinido"],
      "jornada": ["Completa"],
      "palabras_clave": ["Python", "remoto"],
      "criterios": "Preferencia por puestos con posibilidad de teletrabajo."
    }
  }
  ```
- **Errores:**
  - `400` si el cuerpo es inválido, falta `version_base`, `version_base` no es entero, el JSON está mal formado, o hay errores de validación de contenido.
  - `409` si `version_base` es numérica pero no coincide con la activa, o si el contenido normalizado es idéntico al activo.
  - `500` si falla el almacenamiento.
  - `503` si el perfil no está disponible.
- **Cubre:** REQ-011, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-027

### `POST /perfil/rollback`

Crea una nueva versión `n+1` copiando el contenido de la versión objetivo y la activa.

- **Cuerpo de petición:**
  ```json
  {
    "version_base": 5,
    "version_objetivo": 3
  }
  ```
  - `version_base`: entero obligatorio; debe coincidir con la versión activa actual.
  - `version_objetivo`: entero obligatorio; versión a la que se quiere volver.
- **Respuesta 201:**
  ```json
  {
    "version_activa": 6,
    "perfil": {
      ...contenido copiado de la versión objetivo...
    }
  }
  ```
- **Errores:**
  - `400` si falta algún campo, no son enteros, el JSON está mal formado, o `version_objetivo` es menor que 1.
  - `404` si `version_objetivo` no existe.
  - `409` si `version_objetivo` ya es la activa, o si `version_base` no coincide con la activa.
  - `500` si falla el almacenamiento.
  - `503` si el perfil no está disponible.
- **Cubre:** REQ-012, REQ-016, REQ-026

### `POST /perfil/validar`

Valida un borrador sin crear versión ni activarla.

- **Cuerpo de petición:** mismo objeto `perfil` que en `POST /perfil/versiones`, sin `version_base`.
- **Respuesta 200 (válido):**
  ```json
  {
    "valido": true,
    "errores": []
  }
  ```
- **Respuesta 200 (inválido):**
  ```json
  {
    "valido": false,
    "errores": [
      {"campo": "criterios", "mensaje": "El campo supera la longitud máxima permitida."}
    ]
  }
  ```
- **Errores:**
  - `400` si el cuerpo está mal formado, el JSON no es válido, los tipos son incorrectos, o el payload supera 1 MB. Usa el modelo de error común.
  - `503` si el perfil no está disponible.
- **Cubre:** REQ-013, REQ-017, REQ-018, REQ-019, REQ-027

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| api-service | schema-migrator-perfil | Orden de migrar al arranque | llamada interna |
| api-service | perfil-api | Registro del router en la aplicación | llamada interna |
| perfil-api | perfil-validator | Borrador a validar y normalizar | llamada interna |
| perfil-api | perfil-repository | Solicitud de lectura/escritura de versiones | llamada interna |
| perfil-validator | perfil-normalizer | Listas de texto a normalizar | llamada interna |
| perfil-repository | db-connection-perfil | Solicitud de conexión por operación | llamada interna |
| Cliente | perfil-api | Operaciones de consulta, guardado, rollback y validación | HTTP (OpenAPI) |

## Modelo de datos lógico

- **PerfilVersion:** una versión concreta del perfil, identificada por un número entero monótono creciente, con su contenido completo y su marca temporal de creación. Relaciones: es referenciada por el puntero de `PerfilActivo`.
- **PerfilActivo:** puntero único a la `PerfilVersion` vigente. Solo puede haber una fila (id forzado a 1) y una única versión activa. Relaciones: apunta a `PerfilVersion`.
- **SchemaVersionPerfil:** versión actual del esquema del fichero propio. Relaciones: ninguna.

## Esquema conceptual SQLite

### Tabla `schema_version_perfil`

| Columna | Tipo SQLite | Restricciones |
|---|---|---|
| version | INTEGER | PRIMARY KEY |
| applied_at | TEXT | not null |

### Tabla `perfil_version`

| Columna | Tipo SQLite | Restricciones / Notas |
|---|---|---|
| version | INTEGER | PRIMARY KEY AUTOINCREMENT; garantiza monotonicidad y evita reusar ids |
| contenido | TEXT | not null; JSON con los campos del perfil en UTF-8 |
| creado_en | TEXT | not null; ISO 8601 UTC con zona (`Z`) |

### Tabla `perfil_activo`

| Columna | Tipo SQLite | Restricciones / Notas |
|---|---|---|
| id | INTEGER | PRIMARY KEY CHECK (id = 1); fuerza una única fila |
| version | INTEGER | not null; FOREIGN KEY a `perfil_version(version)` |

**Restricciones e índices:**

- `perfil_version(version)` es clave primaria con `AUTOINCREMENT`.
- `perfil_activo(id)` tiene `CHECK (id = 1)` para garantizar un único puntero de activa.
- `perfil_activo(version)` tiene una restricción `FOREIGN KEY` explícita hacia `perfil_version(version)`.
- Cada conexión activa `PRAGMA foreign_keys = ON` junto con `PRAGMA journal_mode = WAL` y `PRAGMA busy_timeout`.

### Serialización del contenido

- El campo `contenido` almacena un objeto JSON con las claves: `sectores`, `municipios`, `provincias`, `contrato`, `jornada`, `palabras_clave` (todas listas de cadenas) y `criterios` (cadena de texto libre).
- La codificación es UTF-8, conservando tildes, eñes y caracteres Unicode válidos tal cual.
- La serialización usa `ensure_ascii=False` para no escapar caracteres no ASCII.
- Las listas se guardan como arrays JSON en la columna `contenido`; no se normalizan en tablas hijas.
- Al leer una versión, las claves ausentes se tratan como lista vacía (para campos de lista) o cadena vacía (para `criterios`), de modo que futuros campos no rompan versiones antiguas.

## Decisiones

### DEC-001 Segundo fichero SQLite propio para el perfil

- **Decisión:** El perfil vive en `data/job_emcan_perfil.db`, un fichero SQLite independiente con WAL y `busy_timeout`, gestionado por su propio migrador y su propia conexión.
- **Alternativas descartadas:**
  - (a) Añadir tablas del perfil a `data/job_emcan.db`: obligaría a compartir el versionado de esquema con `api-persistencia`, que es feature aprobada y no se modifica (SUP-A).
  - (b) Almacenar el perfil en JSON plano: perdería atomicidad, integridad y control de concurrencia.
- **Cubre:** REQ-024, REQ-025, NFR-002, NFR-003, NFR-007

### DEC-002 Listas de texto como arrays JSON dentro de una columna TEXT

- **Decisión:** Los campos estructurados (`sectores`, `municipios`, `provincias`, `contrato`, `jornada`, `palabras_clave`) y `criterios` se serializan en un único objeto JSON almacenado en `perfil_version.contenido`.
- **Alternativas descartadas:**
  - (a) Tablas hijas normalizadas (`perfil_version_sector`, `perfil_version_municipio`, etc.): añaden joins innecesarios para listas cortas, sin relaciones ni restricciones referenciales que justifiquen el modelo relacional.
  - (b) Una columna TEXT por lista: aumenta el número de columnas y obliga a mantener el esquema al añadir campos futuros; JSON es más flexible y los campos siempre se leen/escriben juntos.
- **Cubre:** REQ-004, REQ-005, REQ-006, REQ-007, REQ-018

### DEC-003 Clave primaria autoincremental y puntero de activa separado

- **Decisión:** `perfil_version.version` usa `INTEGER PRIMARY KEY AUTOINCREMENT` para garantizar monotonicidad estricta sin reusar ids. La versión activa se representa con la tabla `perfil_activo` (una sola fila con `id = 1`) en lugar de una bandera por fila.
- **Alternativas descartadas:**
  - (a) `INTEGER PRIMARY KEY` sin `AUTOINCREMENT`: es un alias de `rowid` y podría reusar el id más alto si se borrara la fila máxima, lo que rompería la monotonicidad estricta de REQ-002.
  - (b) Columna `activa` booleana en `perfil_version`: más simple, pero complica las garantías de "una sola activa" y obliga a actualizar filas históricas, rozando la inmutabilidad.
  - (c) Versión activa solo por convenio (la mayor): requiere `MAX(version)` en cada consulta y no permite estados transitorios seguros dentro de una transacción.
- **Cubre:** REQ-002, REQ-003, REQ-011, REQ-014

### DEC-004 Control optimista con `version_base` obligatoria en escrituras

- **Decisión:** Toda operación de escritura (`POST /perfil/versiones` y `POST /perfil/rollback`) exige `version_base`. Si falta o no es un entero válido, se devuelve `400`. Si es numérica pero no coincide con la versión activa actual dentro de la transacción, se rechaza con `409`. Cuando no existe perfil, el único `version_base` aceptado es `0`.
- **Alternativas descartadas:**
  - (a) Bloqueo pesimista: añade complejidad innecesaria para un uso personal y un único editor (SUP-G).
  - (b) Permitir escrituras sin `version_base`: rompería el control optimista y podría sobreescribir cambios concurrentes inadvertidamente.
  - (c) Tratar `version_base` faltante/no numérico como `409`: confunde un parámetro inválido con un conflicto de versión.
- **Cubre:** REQ-016, REQ-020, REQ-026

### DEC-005 Representación de "no existe perfil" como respuesta 200 con `perfil: null`

- **Decisión:** Cuando `perfil_activo` no tiene fila, `GET /perfil/activo` devuelve 200 con `perfil: null` y `version_activa: 0`; `GET /perfil/versiones` devuelve 200 con `version_activa: 0` y `versiones: []`.
- **Alternativas descartadas:**
  - (a) HTTP 404: un consumidor futuro como `api-encaje` necesitaría tratar la ausencia de perfil como un estado esperado, no como un error de recurso.
  - (b) Crear un perfil vacío por defecto: contradice REQ-020 (sin perfil vacío).
- **Cubre:** REQ-008, REQ-009, REQ-020, REQ-021

### DEC-006 Respuesta 409 para "sin cambios" y "rollback a versión activa"

- **Decisión:** Tanto el guardado idéntico a la versión activa como el rollback a la versión ya activa se resuelven con HTTP 409, indicando en el cuerpo el motivo específico.
- **Alternativas descartadas:**
  - (a) 200 con advertencia: confunde al cliente al no señalar que la operación no tuvo efecto.
  - (b) 400: el borrador no es inválido, simplemente no hay cambio; 409 expresa mejor el conflicto con el estado actual.
- **Cubre:** REQ-015, REQ-026

### DEC-007 Normalización NFD + `casefold` conservando la forma escrita

- **Decisión:** Para deduplicar se genera una clave de comparación: `NFD` → eliminar caracteres de categoría `Mn` → `casefold`. Se conserva la primera forma escrita que aparece en la lista.
- **Alternativas descartadas:**
  - (a) Comparación exacta: no cumple REQ-018 (duplicados que solo difieren en mayúsculas o tildes).
  - (b) `lower()` en lugar de `casefold()`: es menos estable para algunos caracteres Unicode.
  - (c) Normalizar la forma escrita: perdería la intención del usuario y la legibilidad (NFR-004).
- **Cubre:** REQ-004, REQ-015, REQ-018, NFR-004

### DEC-008 Inicialización fallida degrada solo el perfil

- **Decisión:** Si la migración o la apertura del fichero de perfil falla al arrancar, se registra el error, se marca el perfil como no disponible y los endpoints de perfil devuelven 503; el resto de la API sigue arrancando.
- **Alternativas descartadas:**
  - (a) Abortar el arranque completo: un problema de perfil no debería dejar sin servicio el resto de la API.
  - (b) Ignorar el error y permitir operaciones: podría propagar datos corruptos (NFR-007).
- **Cubre:** REQ-025, NFR-007

### DEC-009 Conexión SQLite por operación

- **Decisión:** Cada operación de `perfil-repository` abre una conexión SQLite nueva, configura WAL, `busy_timeout` y `foreign_keys`, ejecuta la consulta o transacción, y cierra la conexión al terminar. No se mantiene una conexión persistente compartida entre hilos.
- **Alternativas descartadas:**
  - (a) Conexión persistente con `check_same_thread=False` y un `Lock`: añade complejidad de sincronización manual y riesgo de retener una transacción abierta entre operaciones; FastAPI ejecuta endpoints síncronos en un pool de hilos, por lo que una conexión por operación es más segura y simple.
  - (b) Conexión persistente sin sincronización: `sqlite3` no permite compartir conexiones entre hilos sin `check_same_thread=False`, lo que provocaría errores en tiempo de ejecución.
- **Cubre:** NFR-002, NFR-003

### DEC-010 Asignación de versión mediante `AUTOINCREMENT`

- **Decisión:** La columna `perfil_version.version` usa `INTEGER PRIMARY KEY AUTOINCREMENT` para que SQLite asigne el siguiente entero monótono sin reusar ids, garantizando REQ-002 incluso si algún día se eliminara una fila (cosa que no ocurrirá por REQ-003, pero el mecanismo lo previene).
- **Alternativas descartadas:**
  - (a) Calcular `MAX(version) + 1` explícitamente dentro de la transacción: funciona, pero es más propenso a carreras y requiere bloqueos adicionales; `AUTOINCREMENT` resuelve el mismo problema dentro de SQLite.
  - (b) `INTEGER PRIMARY KEY` sin `AUTOINCREMENT`: no garantiza monotonicidad estricta ante eliminaciones (aunque REQ-003 prohíba borrar, elija el mecanismo más robusto).
- **Cubre:** REQ-002, REQ-003

### DEC-011 Resultado de validación en 200, no en 400

- **Decisión:** `POST /perfil/validar` devuelve siempre 200 para un cuerpo bien formado, con `{valido: true|false, errores: [...]}`. El código 400 se reserva a errores de transporte (JSON mal formado, tipos incorrectos, payload > 1 MB).
- **Alternativas descartadas:**
  - (a) Devolver 400 cuando el borrador tiene errores de validación: confunde un resultado negativo con un error de petición; la validación es la operación, no una condición de error.
  - (b) Usar el modelo de error común para los errores de validación en `POST /perfil/validar`: rompe el contrato de que la respuesta de validación informa de validez sin crear versión.
- **Cubre:** REQ-013

## Concurrencia

- El perfil usa un fichero SQLite separado de `data/job_emcan.db`, por lo que las escrituras de perfil no compiten con la ingesta o la purga de ofertas.
- Se activa WAL en `data/job_emcan_perfil.db` y se configura `busy_timeout` en cada conexión para que los escritores esperen en lugar de fallar con `SQLITE_BUSY`.
- Cada operación de guardado o rollback abre su propia conexión e inicia una transacción de escritura con `BEGIN IMMEDIATE` (o equivalente) para adquirir el bloqueo de escritura antes de leer la versión activa, evitando carreras.
- SQLite serializa las escrituras; dos operaciones simultáneas sobre el perfil se ejecutan equivalentemente una tras otra. La segunda, si `version_base` queda obsoleta tras la primera, recibe 409.
- Los lectores pueden operar concurrentemente gracias a WAL; cada lectura abre y cierra su propia conexión.

## Rendimiento

- Con hasta 100 versiones y un contenido JSON pequeño (listas cortas y criterios de menos de 5000 caracteres), las consultas de perfil activo, historial y versión concreta responden en menos de 500 ms.
- El historial se devuelve completo (hasta 100 versiones), ordenado por versión ascendente; no se pagina, dado que el límite está acordado en NFR-001 y el tamaño JSON es manejable.
- Si en el futuro el historial creciera más allá de 100 versiones, se valoraría la paginación; hoy no es necesaria.

## Configuración

El fichero `config/perfil.yaml` contendrá:

- `perfil.ruta_bd`: ruta al fichero SQLite (por defecto `data/job_emcan_perfil.db`).
- `perfil.busy_timeout_ms`: tiempo de espera para escrituras concurrentes (por defecto `5000`).
- `validacion.longitud_maxima_elemento`: longitud máxima de cada entrada de lista (por defecto `200`).
- `validacion.maximo_elementos_por_lista`: número máximo de elementos por lista (por defecto `100`).
- `validacion.longitud_maxima_criterios`: longitud máxima del texto de criterios (por defecto `5000`).
- `validacion.tamano_maximo_payload_bytes`: tamaño máximo del cuerpo de la petición (por defecto `1048576`, 1 MB).

## Riesgos

- **Fichero corrupto o versión de esquema futura:** `schema-migrator-perfil` detecta el problema al arrancar y marca el perfil como no disponible (503). Mitigación: no se sirven datos corruptos y se fuerza una revisión manual.
- **Disco lleno o permisos incorrectos:** una escritura falla dentro de la transacción y se deshace; la versión activa no cambia. Mitigación: transacciones atómicas y mensajes de error claros.
- **Dos instancias de la API abriendo el mismo fichero:** WAL y `busy_timeout` serializan las escrituras; si se agota el tiempo, la operación devuelve 500 sin cambiar el estado.
- **Payload enorme:** se rechaza antes de procesar los campos, protegiendo la memoria y el tiempo de CPU. Mitigación: límite de 1 MB y validación de longitudes.
- **Conflicto de edición concurrente:** dos clientes que envíen `version_base` obsoleta reciben 409 y pueden recargar la versión activa. Mitigación: control optimista explícito.
- **Rollback inválido:** se rechaza si el objetivo es la activa (REQ-026) o no existe (404). Mitigación: validación previa dentro de la transacción.
- **Pérdida del fichero de perfil:** si se borra el fichero, al arrancar se crea uno nuevo vacío (sin perfil activo). Las versiones históricas se pierden si no hay copia de seguridad externa.
- **Divergencia con `data/job_emcan.db`:** el perfil nunca escribe en la base de ofertas, por lo que no puede corromperla; la única dependencia futura será que `api-encaje` lea la versión activa del perfil.

## Estrategia de tests

- **Tests unitarios de `perfil-normalizer`:** `trim`, descarte de vacíos, deduplicación con tildes y mayúsculas, conservación de la forma escrita, estabilidad del resultado.
- **Tests unitarios de `perfil-validator`:** contenido mínimo, longitudes de elementos y listas, longitud de `criterios`, caracteres de control, payload máximo, detección de "sin cambios" y formato de errores.
- **Tests unitarios de `perfil-repository`:** cálculo de `n+1`, atomicidad de inserción + activación, lectura de activa, lectura de historial, lectura de versión concreta, rechazo de `version_base` obsoleta.
- **Tests de integración con fichero temporal:** arranque del migrador, creación desde cero, detección de versión futura, operaciones completas de guardado y rollback, supervivencia al reinicio simulado.
- **Tests de concurrencia:** dos escrituras simultáneas sobre el perfil; una debe crear `n+1` y la otra debe recibir 409 o esperar y crear `n+2`.
- **Tests de corrupción:** simular fichero no SQLite y versión de esquema futura; verificar que los endpoints devuelven 503 y no modifican nada.
- **Tests de endpoints:** consulta de activo sin perfil, historial sin perfil, versión concreta con parámetro inválido y no existente, guardado válido, guardado sin cambios, rollback, validación previa (válida e inválida) y códigos de error correspondientes.
- **Tests de contrato:** generar y comparar el OpenAPI derivado de la implementación con `docs/contracts/openapi/api-perfil.yaml`.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | perfil-repository, perfil-api | DEC-003 |
| REQ-002 | perfil-repository | DEC-003, DEC-010 |
| REQ-003 | perfil-repository, db-connection-perfil | DEC-002, DEC-003, DEC-010 |
| REQ-004 | perfil-normalizer, perfil-repository | DEC-002, DEC-007 |
| REQ-005 | perfil-repository | DEC-002 |
| REQ-006 | perfil-normalizer, perfil-repository | DEC-002 |
| REQ-007 | perfil-normalizer, perfil-repository | DEC-002 |
| REQ-008 | perfil-api, perfil-repository | DEC-005 |
| REQ-009 | perfil-api, perfil-repository | DEC-005 |
| REQ-010 | perfil-api, perfil-repository | DEC-003 |
| REQ-011 | perfil-repository, db-connection-perfil | DEC-003, DEC-004, DEC-009, DEC-010 |
| REQ-012 | perfil-repository | DEC-003, DEC-010 |
| REQ-013 | perfil-validator, perfil-api | DEC-011 |
| REQ-014 | perfil-repository, db-connection-perfil | DEC-003, DEC-009 |
| REQ-015 | perfil-validator, perfil-api | DEC-006, DEC-007 |
| REQ-016 | perfil-repository, perfil-api | DEC-004 |
| REQ-017 | perfil-validator, perfil-api | DEC-011 |
| REQ-018 | perfil-normalizer, perfil-validator | DEC-007 |
| REQ-019 | perfil-validator, perfil-api | DEC-011 |
| REQ-020 | perfil-api, perfil-repository | DEC-004, DEC-005 |
| REQ-021 | perfil-api, perfil-repository | DEC-005 |
| REQ-022 | perfil-api, perfil-repository | DEC-003 |
| REQ-023 | perfil-api | DEC-005 |
| REQ-024 | db-connection-perfil, schema-migrator-perfil | DEC-001, DEC-009 |
| REQ-025 | schema-migrator-perfil, perfil-repository | DEC-008, DEC-009 |
| REQ-026 | perfil-api, perfil-repository | DEC-004, DEC-006 |
| REQ-027 | perfil-api, perfil-validator | DEC-011 |
| NFR-001 | perfil-api, perfil-repository | DEC-002 |
| NFR-002 | perfil-repository, db-connection-perfil | DEC-001, DEC-004, DEC-009 |
| NFR-003 | db-connection-perfil | DEC-001, DEC-009 |
| NFR-004 | perfil-normalizer, perfil-repository | DEC-007 |
| NFR-005 | perfil-api, perfil-validator | DEC-011 |
| NFR-006 | perfil-repository, db-connection-perfil | DEC-003, DEC-009 |
| NFR-007 | schema-migrator-perfil, perfil-api | DEC-008 |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-perfil.yaml` (nuevo) | Define las operaciones bajo `/perfil`: consultar activo, historial, versión concreta, crear versión, rollback y validación previa. Siguiendo la estrategia `implementation-first`, se derivará de la implementación. |
| Configuración | `config/perfil.yaml` (nuevo) | Configuración de `api-perfil`: ruta del fichero SQLite, `busy_timeout`, límites de validación y tamaño máximo de payload. |

## Cambios sugeridos al mapa

Los componentes de `api-perfil` son detalle interno de implementación dentro del módulo `API` y no reciben identificador propio en el mapa de arquitectura.

- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador, persistencia, histórico, integridad, listado y perfil de búsqueda | -`
- `+ Contrato: openapi | docs/contracts/openapi/api-perfil.yaml | cliente -> api-perfil`
- `+ Contrato: configuracion | config/perfil.yaml | api-perfil -> config-perfil`
