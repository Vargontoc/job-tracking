# Diseño: api-listado

Estado: aprobado
Revisión: 2
Basado en: requirements@2
Verificación: correcta

## Resumen

`api-listado` añade al módulo `API` un endpoint de solo lectura para consultar ofertas con filtros combinables, paginación y ordenación, sin modificar `api-persistencia` ni sus contratos. La lectura se resuelve con un adaptador de solo lectura (`mode=ro`) sobre el mismo SQLite de `api-persistencia`, reutilizando el criterio validado por `api-historico`; los filtros de estado, sector y rango de fechas se ejecutan en SQL. Cuando hay búsqueda por texto libre, SQL solo aplica los filtros no textuales, se recuperan las filas candidatas ordenadas, se normalizan y filtran en memoria antes de paginar, y el total se calcula sobre el conjunto ya filtrado, cumpliendo la tolerancia a tildes de NFR-003 con el volumen actual.

## Supuestos sobre el sistema actual

- `api-persistencia` mantiene la base de datos SQLite `data/job_emcan.db` como fuente de verdad, con WAL activado, `busy_timeout` configurado y el esquema de la tabla `ofertas` documentado en `specs/api-persistencia/design.md`.
- `persistencia-api` expone solo crear/actualizar, consultar por `(comunidad, codigo)`, listar vigentes y listar códigos vistos; no ofrece filtros ni paginación.
- `api-historico` ya validó en SUP-004 la lectura directa en `mode=ro` sobre `data/job_emcan.db` para consultas no cubiertas por `persistencia-api`.
- El esquema de `ofertas` almacena fechas de difusión como texto en formato `dd/mm/aaaa`, el campo `sector` siempre vacío (DEC-009) y el campo `oficina` no existe.
- `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` y `api-integridad` no se modifican.
- La aplicación FastAPI comparte el proceso con las tareas de persistencia, histórico e integridad; los endpoints de `api-listado` conviven en el mismo `app`.

## Componentes

| Componente | Responsabilidad | Existente o nuevo |
|---|---|---|
| api-service | Aplicación FastAPI que registra el router de `api-listado` en el arranque. | existente (se extiende) |
| config-listado | Fichero YAML con la ruta de la base de datos, tamaño de página por defecto y tamaño máximo de página. | nuevo |
| listado-read-adapter | Abre una conexión SQLite `mode=ro` a `data/job_emcan.db`, configura `busy_timeout` y la cierra tras cada consulta. | nuevo |
| listado-query-repository | Ejecuta la consulta SQL de listado aplicando filtros, orden y paginación, y devuelve resultados más recuento total. | nuevo |
| listado-filter-builder | Construye de forma segura el `WHERE` con parámetros posicionales a partir de los filtros recibidos. | nuevo |
| listado-date-parser | Normaliza fechas `dd/mm/aaaa`, valida rangos y genera la expresión SQL para comparar/ordenar `fecha_inicio_difusion`. | nuevo |
| listado-text-normalizer | Normaliza cadenas para búsqueda insensible a mayúsculas y tildes (Unicode NFD). | nuevo |
| listado-api | Endpoints `GET /listado` y `GET /listado/filtros`: valida parámetros, orquesta los componentes y forma la respuesta JSON. | nuevo |

## Flujo principal

1. Al arrancar `api-service` se registra el router de `listado-api` junto a los routers existentes.
2. `listado-api` recibe una petición `GET /listado` con los filtros opcionales (texto, sector, municipio, fecha_desde, fecha_hasta, incluir_cerradas, offset, tamaño).
3. `listado-api` valida los parámetros con `listado-date-parser` y las reglas de paginación; si hay error, responde con un mensaje claro.
4. `listado-filter-builder` traduce los filtros válidos a una cláusula `WHERE` parametrizada. Si hay filtro de texto libre (o el filtro de municipio requiere tolerancia a tildes), los filtros textuales se omiten del `WHERE`: SQL solo aplica los filtros no textuales (estado, sector, rango de fechas).
5. `listado-query-repository` abre una conexión de solo lectura a través de `listado-read-adapter`. Si no hay filtros textuales, ejecuta un `COUNT` total en SQL y recupera la página con `LIMIT/OFFSET`. Si hay filtros textuales, no calcula el total todavía y recupera todas las filas candidatas ordenadas por fecha y código, sin paginar en SQL.
6. Cuando hay filtro de texto libre, `listado-text-normalizer` normaliza el término y los campos (`ocupacion`, `municipio`, `texto_libre`) de cada fila candidata, aplica el filtro en memoria y descarta las que no coincidan. El recuento `total` es la longitud de la lista filtrada. A continuación se recorta la página (`[offset:offset+tamaño]`) y se transforma al modelo de respuesta.
7. `listado-api` devuelve la lista de ofertas y metadatos (total, página, tamaño, filtros aplicados).

## Flujos alternativos y de fallo

### ALT-001 Base de datos no existe o no está migrada

- **Condición:** `data/job_emcan.db` no existe, no es un fichero SQLite válido o carece de la tabla `ofertas` esperada.
- **Comportamiento:** `listado-read-adapter` detecta el fallo al abrir o al comprobar el esquema y `listado-api` devuelve un error controlado indicando que no se puede acceder a los datos.
- **Responsable:** listado-read-adapter
- **Resultado:** No se devuelven ofertas; el mensaje identifica el origen como un problema de acceso a la base de datos.
- **Cubre:** REQ-009

### ALT-002 Parámetros inválidos

- **Condición:** Una fecha no cumple `dd/mm/aaaa`, el rango está invertido, `offset` o la página solicitada es negativa, o el tamaño de página supera el máximo permitido. Se interpreta que "página fuera de rango" de REQ-009 se refiere a estos valores negativos o inválidos, no a un `offset` que ya supera el total.
- **Comportamiento:** `listado-api` rechaza la petición con un error que indica qué parámetro falla y, en el caso de las fechas, el formato esperado.
- **Responsable:** listado-api
- **Resultado:** La consulta no llega a la base de datos.
- **Cubre:** REQ-009, NFR-001

### ALT-003 Offset igual o mayor que el total

- **Condición:** El `offset` es válido (no negativo) pero mayor o igual que el total de ofertas que cumplen los filtros.
- **Comportamiento:** `listado-query-repository` devuelve una lista vacía, `total` igual al número real de coincidencias y sin error. Esto no se considera "página fuera de rango" en el sentido de REQ-009, sino un resultado válido y vacío conforme a REQ-007.
- **Responsable:** listado-query-repository
- **Resultado:** Respuesta 200 con `items: []` y metadatos coherentes.
- **Cubre:** REQ-007, REQ-009

### ALT-004 Ofertas sin fecha de inicio de difusión

- **Condición:** Una oferta vigente o cerrada tiene `fecha_inicio_difusion` vacía o no parseable.
- **Comportamiento:** Quedan excluidas de los filtros de rango de fechas y se sitúan al final del orden descendente por fecha.
- **Responsable:** listado-date-parser
- **Resultado:** Aparecen en el listado solo cuando no se aplica filtro de fechas, siempre detrás de las ofertas con fecha válida.
- **Cubre:** REQ-005, REQ-007, SUP-004

### ALT-005 Lectura concurrente con ingesta o purga

- **Condición:** Un endpoint de listado se ejecuta mientras `ingestion-task` o `purge-task` escriben en `data/job_emcan.db`.
- **Comportamiento:** La conexión `mode=ro` con WAL lee una instantánea consistente sin bloquear a los escritores; `busy_timeout` amortigua breves contenciones al abrir la conexión.
- **Responsable:** listado-read-adapter
- **Resultado:** El listado es consistente y no se ve alterado por escrituras concurrentes.
- **Cubre:** REQ-010

### ALT-006 Texto libre o contacto purgados

- **Condición:** El campo `texto_libre` o `contacto` de una oferta está vacío por haberse aplicado la purga de `api-persistencia`.
- **Comportamiento:** La oferta sigue apareciendo en el listado si cumple el resto de filtros; los campos purgados se devuelven vacíos y no contribuyen a la búsqueda por texto libre.
- **Responsable:** listado-query-repository
- **Resultado:** El resultado refleja el registro mínimo sin texto ni contacto.
- **Cubre:** REQ-002, REQ-008

### ALT-007 Campo `sector` siempre vacío

- **Condición:** El cliente aplica un filtro por `sector` distinto de vacío.
- **Comportamiento:** El filtro se aplica en SQL; dado que todas las ofertas tienen `sector` vacío, el resultado está vacío. El endpoint `GET /listado/filtros` sigue anunciando `sector` como filtro soportado.
- **Responsable:** listado-filter-builder
- **Resultado:** Respuesta válida con `items: []` y metadatos; el filtro existe pero no aporta resultados hasta que una feature futura persista el sector.
- **Cubre:** REQ-003

## Interfaces entre componentes

| Origen | Destino | Qué se comunica | Protocolo |
|---|---|---|---|
| api-service | listado-api | Registro del router en la aplicación | llamada interna |
| listado-api | listado-filter-builder | Filtros validados para construir `WHERE` | llamada interna |
| listado-api | listado-date-parser | Cadenas de fecha para validación y conversión | llamada interna |
| listado-api | listado-text-normalizer | Término de búsqueda para normalización | llamada interna |
| listado-api | listado-query-repository | Cláusulas `WHERE`, `ORDER BY`, `LIMIT/OFFSET` | llamada interna |
| listado-query-repository | listado-read-adapter | Petición de conexión `mode=ro` a la BD | llamada interna |
| Cliente | listado-api | Petición de listado filtrado y paginado | HTTP (OpenAPI) |

## Modelo de datos lógico

- **Oferta:** entidad gestionada por `api-persistencia` en `data/job_emcan.db`. `api-listado` solo la lee; no modifica sus campos.
- **FiltroAplicado:** par clave-valor que representa un filtro recibido y aplicado en la consulta actual. Relaciones: ninguna.

## Decisiones

### DEC-001 Vía de lectura: adaptador `mode=ro` sobre `data/job_emcan.db`

- **Decisión:** `api-listado` lee directamente el fichero SQLite de `api-persistencia` mediante un adaptador de solo lectura (`mode=ro`), reutilizando el criterio validado por `api-historico` en SUP-004.
- **Alternativas descartadas:**
  - (a) Ampliar `persistencia-api` con filtros y paginación: obligaría a revisar una feature aprobada e implementada, contradiciendo la restricción de no modificar `api-persistencia`.
  - (b) Mantener una réplica propia de las ofertas: duplicaría datos, requeriría sincronización y violaría el principio de solo lectura sobre el origen de `api-persistencia`.
- **Cubre:** REQ-001, REQ-010, SUP-005

### DEC-002 Normalización de texto en aplicación antes de paginar

- **Decisión:** Cuando hay filtro de texto libre (y cuando el filtro de municipio requiera tolerancia a tildes), SQL aplica solo los filtros no textuales (estado, sector, rango de fechas). Se recuperan las filas candidatas ya ordenadas por fecha y código, se normalizan en Python el término y los campos (`ocupacion`, `municipio`, `texto_libre`) mediante `lower()` + descomposición Unicode NFD y eliminación de diacríticos, y se filtra en memoria **antes** de calcular el total y recortar la página (`[offset:offset+tamaño]`). El `COUNT` en SQL solo se usa cuando no hay filtros textuales; con filtro de texto, el `total` es el número de filas tras el filtrado en memoria.
- **Alternativas descartadas:**
  - (a) Prefiltrar en SQL con el término crudo usando `lower()` + `LIKE` y refinar en memoria: pierde filas cuando el término no lleva tilde y el dato sí. Por ejemplo, con "tecnico" buscado y "Técnico" almacenado, `lower('Técnico') = 'técnico'`, que no contiene "tecnico", así que la fila se descarta en SQL y la normalización posterior nunca la recupera. Además, si el `COUNT` y el `LIMIT/OFFSET` se hacen antes del filtrado en memoria, `total` y la página son incorrectos.
  - (b) Depender de `LIKE lower()` exclusivamente: cumple la insensibilidad a mayúsculas/minúsculas pero no a tildes, incumpliendo los criterios de aceptación de NFR-003.
  - (c) Añadir una extensión `unaccent` o similar a SQLite: contradice el stack del proyecto (SQLite estándar sin extensiones) y añade dependencia externa.
- **Coste:** Con el volumen objetivo de 500 ofertas, recuperar todas las filas ordenadas, leer sus campos de texto, normalizar NFD y comparar tarda menos de 10 ms en condiciones normales, bien dentro del límite de 2 s de NFR-002. La memoria adicional es despreciable porque solo se retienen las columnas necesarias del listado. Si el volumen creciera sustancialmente (por ejemplo, varios miles de ofertas), habría que evaluar un índice de texto (FTS5), una extensión como `sqlite-vec` o un campo normalizado persistido en `api-persistencia`; esas alternativas quedan fuera del alcance actual y no rompen NFR-002 con el volumen contemplado.
- **Cubre:** REQ-002, REQ-004, REQ-007, NFR-002, NFR-003

### DEC-003 Comparación de fechas mediante expresión SQL derivada con guarda de patrón

- **Decisión:** Se convierte `fecha_inicio_difusion` de `dd/mm/aaaa` a texto ordenable ISO (`aaaa-mm-dd`) con una expresión SQL que incluye una guarda explícita de patrón, por ejemplo:
  ```
  CASE
    WHEN fecha_inicio_difusion GLOB '[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]'
    THEN substr(fecha_inicio_difusion,7,4) || '-' || substr(fecha_inicio_difusion,4,2) || '-' || substr(fecha_inicio_difusion,1,2)
    ELSE NULL
  END
  ```
  Las fechas vacías, cadenas cortas o que no cumplan el patrón se tratan como nulas: quedan fuera de los filtros de rango y se sitúan al final del orden descendente. El orden se expresa como `ORDER BY <expr> IS NULL, <expr> DESC, codigo ASC` (o equivalente), de modo que los nulos aparecen siempre detrás de las fechas válidas.
- **Alternativas descartadas:**
  - (a) Aplicar `substr(...)` sin guarda de patrón: produce valores basura (`'--'`, `'20-11-26'`) sobre cadenas vacías o corruptas, que no son nulos y pueden ordenar incorrectamente o pasar filtros de rango no deseados.
  - (b) Parsear y comparar fechas en Python: obligaría a traer todas las ofertas a memoria para ordenarlas, complicando la paginación y el rendimiento.
  - (c) Alterar el esquema para almacenar fechas como INTEGER o ISO: tocaría `api-persistencia`, feature aprobada que no se modifica.
- **Tests adicionales:** fechas imposibles como `31/02/2026` (el patrón pasa pero no es fecha real) deben ordenarse según la expresión ISO resultante; cadenas cortas como `''` o `'20/11'` deben quedar como nulas y al final.
- **Cubre:** REQ-005, REQ-007, SUP-004

### DEC-004 Paginación: validación y recorte

- **Decisión:** El tamaño de página se valida: si supera 100 se recorta a 100; si es menor o igual a 0 se rechaza. El `offset` o la página negativos se rechazan; se interpreta que "página fuera de rango" de REQ-009 se refiere a estos valores negativos o inválidos. Un `offset` válido (mayor o igual a 0) que sea igual o mayor que el total devuelve una página vacía con el `total` real, sin error, cumpliendo REQ-007.
- **Alternativas descartadas:**
  - (a) Rechazar tamaños mayores de 100: también válido, pero el recorte es más permisivo con clientes que pidan un tamaño grande por defecto.
  - (b) Permitir offset negativo con semántica de "páginas desde el final": no está solicitado y complica la interfaz.
  - (c) Rechazar `offset >= total` como "página fuera de rango": contradice explícitamente REQ-007, que exige devolver lista vacía cuando el offset supera el total.
- **Cubre:** REQ-007, REQ-009, NFR-001

### DEC-005 Endpoint dedicado para filtros disponibles

- **Decisión:** Además del endpoint `GET /listado`, se expone `GET /listado/filtros` para devolver los filtros soportados (texto, sector, municipio, fecha_desde, fecha_hasta, incluir_cerradas) y sus metadatos (tipo, formato, ejemplo).
- **Alternativas descartadas:**
  - (a) Incluir la lista de filtros solo en la documentación OpenAPI: no cubriría explícitamente el criterio de aceptación de REQ-003 sobre "consulta la lista de filtros disponibles".
  - (b) Añadir un parámetro `meta` al endpoint de listado: mezclaría metadatos de descubrimiento con resultados.
- **Cubre:** REQ-003

### DEC-006 Configuración propia para el listado

- **Decisión:** Se añade `config/listado.yaml` con la ruta de la base de datos, el tamaño de página por defecto y el tamaño máximo de página. Los valores por defecto son `data/job_emcan.db`, `20` y `100` respectivamente.
- **Alternativas descartadas:**
  - (a) Reutilizar `config/persistencia.yaml`: acoplaría `api-listado` a la configuración interna de otra feature y dificultaría cambios futuros.
  - (b) Valores embebidos en código: dificulta ajustes sin redeploy y rompe la convención del proyecto de mantener configuración en YAML.
- **Cubre:** NFR-001, REQ-009

## Riesgos

- **Base de datos no inicializada:** si `data/job_emcan.db` no existe o no tiene la tabla `ofertas`, el endpoint devuelve un error controlado (ALT-001). Mitigación: comprobación de existencia del fichero y del esquema al abrir la conexión.
- **Esquema de `ofertas` cambiado en `api-persistencia`:** `api-listado` depende de las columnas documentadas. Mitigación: tests de integración con el esquema real y revisión del contrato en cada cambio de `api-persistencia`.
- **`texto_libre` o `contacto` purgados:** el filtro por texto no encontrará términos que solo existían en campos purgados. Mitigación: documentar el comportamiento y devolver los campos vacíos en la respuesta.
- **Tildes en búsquedas:** soportadas mediante normalización en aplicación (DEC-002). Mitigación: tests unitarios con tildes, mayúsculas y eñes.
- **Página fuera de rango:** se interpreta como `offset` o página negativos, que se rechazan (ALT-002); un `offset` válido mayor o igual que el total devuelve lista vacía con `total` real (ALT-003). Mitigación: incluir `total` en metadatos para que el cliente ajuste la navegación.
- **Concurrencia con ingesta/purga en WAL:** la lectura `mode=ro` no bloquea escritores. Mitigación: `busy_timeout` configurado y cierre de conexión por consulta para no retener recursos.
- **Datos corruptos (fechas imposibles):** se excluyen de filtros de fecha y ordenan al final (ALT-004). Mitigación: validación de patrón `dd/mm/aaaa` y rangos numéricos básicos en `listado-date-parser`.

## Trazabilidad

| Requisito | Componentes | Decisiones |
|---|---|---|
| REQ-001 | listado-filter-builder, listado-query-repository | DEC-001 |
| REQ-002 | listado-filter-builder, listado-text-normalizer | DEC-002 |
| REQ-003 | listado-api, listado-filter-builder | DEC-005 |
| REQ-004 | listado-filter-builder, listado-text-normalizer | DEC-002 |
| REQ-005 | listado-date-parser, listado-filter-builder | DEC-003 |
| REQ-006 | listado-filter-builder | - |
| REQ-007 | listado-query-repository, listado-date-parser, listado-text-normalizer | DEC-002, DEC-003, DEC-004 |
| REQ-008 | listado-api | - |
| REQ-009 | listado-api, listado-date-parser, listado-query-repository | DEC-004 |
| REQ-010 | listado-read-adapter | DEC-001 |
| NFR-001 | listado-api, config-listado | DEC-004, DEC-006 |
| NFR-002 | listado-query-repository, listado-text-normalizer | DEC-002, DEC-003 |
| NFR-003 | listado-text-normalizer | DEC-002 |

## Contratos afectados

| Protocolo | Contrato | Cambio |
|---|---|---|
| HTTP/OpenAPI | `docs/contracts/openapi/api-listado.yaml` (nuevo) | Define `GET /listado` (consulta filtrada y paginada de ofertas) y `GET /listado/filtros` (filtros soportados), con el esquema de oferta, metadatos de paginación y respuestas de error. Siguiendo la estrategia `implementation-first` de `.sdd/team.md`, se derivará de la implementación. |
| Configuración | `config/listado.yaml` (nuevo) | Configuración de `api-listado`: ruta de la base de datos, tamaño de página por defecto y tamaño máximo de página. |

## Cambios sugeridos al mapa

Los componentes de `api-listado` son detalle interno de implementación dentro del módulo `API` y no reciben identificador propio en el mapa de arquitectura.

- `~ Módulo: API | source/api | API FastAPI de parseo de PDFs, rastreo del buscador, persistencia, histórico, integridad y listado filtrable de ofertas | -`
- `+ Contrato: openapi | docs/contracts/openapi/api-listado.yaml | cliente -> api-listado`
- `+ Contrato: configuracion | config/listado.yaml | api-listado -> config-listado`

## Estrategia de tests

- **Tests unitarios de `listado-filter-builder`:** combinaciones de filtros (AND), valores vacíos, parámetros posicionales y ausencia de concatenación insegura.
- **Tests unitarios de `listado-date-parser`:** fechas válidas, fechas vacías, fechas corruptas, rango invertido y conversión a expresión SQL con guarda `GLOB`; fecha imposible (`31/02/2026`) y cadena corta (`''`, `'20/11'`) deben quedar como nulas y ordenarse al final.
- **Tests unitarios de `listado-text-normalizer`:** mayúsculas/minúsculas, tildes, eñes, cadenas vacías y términos parciales; verificar que "tecnico" coincide con "Técnico".
- **Tests unitarios de paginación:** tamaño recortado a 100, offset negativo rechazado, offset igual o mayor que el total devuelve vacío con `total` real, cálculo de metadatos; verificar que el recorte de página se hace después del filtrado en memoria cuando hay texto libre.
- **Tests de integración con base de datos temporal:** esquema real de `api-persistencia`, ofertas en estados `vigente`, `cerrada` y `sin_ficha`, filtros combinados, orden por fecha descendente y desempate por código; filtro de texto con tildes ("tecnico" contra "Técnico") recupera la fila y el `total` refleja el resultado tras el filtrado en memoria.
- **Tests del endpoint `GET /listado`:** respuesta con lista y metadatos, ausencia de autenticación, errores de parámetros y base inaccesible.
- **Tests del endpoint `GET /listado/filtros`:** lista de filtros soportados incluye `sector`.
- **Tests de rendimiento:** 500 ofertas vigentes, consulta sin filtros y con filtro de texto; se espera respuesta inferior a 2 s en condiciones normales.
- **Tests de solo lectura:** verificar que la consulta no modifica la base de datos ni crea registros.

## Avisos

- `api-listado` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` ni `api-integridad`; la lectura se realiza exclusivamente en `mode=ro` sobre el origen de datos de `api-persistencia`.
- El campo `sector` existe como filtro pero devolverá siempre resultados vacíos mientras `api-persistencia` lo almacene vacío conforme a DEC-009.
- El filtro por `oficina` queda fuera del alcance porque el dato no existe en el esquema de `api-persistencia`.
- La búsqueda por texto libre se resuelve recuperando las filas candidatas ordenadas desde SQL (sin filtros textuales), normalizando y filtrando en memoria antes de paginar; con volúmenes muy superiores a 500 ofertas podría requerir revisión (FTS5, campo normalizado o extensión SQLite).
- La estrategia de contratos del equipo es `implementation-first`, por lo que el OpenAPI de `api-listado` se actualizará a partir del código una vez implementado.
