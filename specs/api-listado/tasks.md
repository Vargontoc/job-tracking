# Tareas: api-listado

Estado: aprobado
Revisión: 1
Basado en: requirements@2, design@2
Verificación: correcta

## Resumen

El trabajo se divide en quince tareas (TASK-001..TASK-015) que siguen la cadena de dependencias del diseño: primero la estructura del paquete y la configuración, después el adaptador de lectura en modo solo lectura sobre el SQLite de `api-persistencia`, el parser de fechas, el normalizador de texto y el constructor de filtros, luego el repositorio de consulta, los dos endpoints (`GET /listado` y `GET /listado/filtros`), el registro del router en la aplicación, la verificación de integración, las dos tareas de contrato (`implementation-first`) y por último la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

Los componentes del listado son detalle de implementación interno del módulo `API` y no reciben identificador propio en el mapa de arquitectura: todas las tareas llevan su línea `Módulo` con el identificador `APP`, aunque el código viva en `source/api/listado/`. La actualización del mapa (TASK-015) se limita a la descripción del módulo `API` y a los dos contratos nuevos.

`api-listado` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` ni `api-integridad`: la lectura se realiza exclusivamente en modo solo lectura (`mode=ro`) sobre `data/job_emcan.db`, el mismo criterio validado por `api-historico` en SUP-004.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Configuración del listado.
2. TASK-003 Adaptador de lectura `mode=ro` → TASK-004 Parser de fechas → TASK-005 Normalizador de texto → TASK-006 Constructor de filtros.
3. TASK-007 Repositorio de consulta.
4. TASK-008 Endpoint `GET /listado` → TASK-009 Endpoint `GET /listado/filtros`.
5. TASK-010 Registro del router en la aplicación.
6. TASK-011 Verificación de integración.
7. TASK-012..TASK-013 Contratos (implementation-first).
8. TASK-014 Verificación de solo lectura y rendimiento → TASK-015 Actualización del mapa (descripción del módulo `API` y dos contratos).

## Tareas

### [x] TASK-001 Estructura del paquete del listado y dependencias

- **Cubre:** REQ-010, SUP-005, DEC-001
- **Componente:** api-listado | source/api/listado
- **Módulo:** APP
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/listado/` con su `__init__.py` y los módulos hosting de los componentes del diseño (`config.py`, `read_adapter.py`, `date_parser.py`, `text_normalizer.py`, `filter_builder.py`, `repository.py`, `routes.py`), y declarar en `pyproject.toml` las dependencias que exige el diseño (`pyyaml` para la carga de `config/listado.yaml`), sin introducir motor de base de datos servidor, ni extensión de SQLite para vectores, ni motor de búsqueda de texto (FTS5) ni ninguna otra dependencia que el diseño no prevea.
- **Hecho cuando:** el subpaquete `source/api/listado` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección; y el paquete no referencia ni importa `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` ni `api-integridad` de forma que los modifique.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.listado` ni de las dependencias declaradas.
  - Una comprobación confirma que `yaml` está disponible en el entorno de pruebas.
  - El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL), ni una extensión de SQLite para vectores, ni el módulo `sqlite3` con FTS5 habilitado, conforme a DEC-002.
  - El paquete no escribe ni modifica ficheros bajo `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/`, `source/api/parser.py`, `source/api/downloader.py` ni `source/api/assembler.py`.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [x] TASK-002 Fichero de configuración del listado

- **Cubre:** REQ-009, NFR-001, DEC-006
- **Componente:** config-listado | config/listado.yaml
- **Módulo:** APP
- **Depende de:** TASK-001
- **Alcance:** Crear el fichero de configuración `config/listado.yaml` con la ruta de la base de datos (por defecto `data/job_emcan.db`), el tamaño de página por defecto (por defecto `20`) y el tamaño máximo de página (por defecto `100`), e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado. La ruta se resuelve relativa a la raíz del proyecto y el fichero se lee en modo **solo lectura (`mode=ro`)** en tiempo de consulta.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto del diseño cuando no se indican otros, un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, el tamaño máximo de página cargado es el que se aplica como límite y las rutas son relativas a la raíz del proyecto.
- **Pruebas automáticas:**
  - La carga del fichero `config/listado.yaml` devuelve la ruta de la base de datos, el tamaño de página por defecto y el tamaño máximo de página.
  - Sin fichero de configuración, la ruta es `data/job_emcan.db`, el tamaño de página por defecto es `20` y el tamaño máximo de página es `100`, conforme a NFR-001 y DEC-006.
  - Un fichero con YAML malformado, con una raíz que no es un mapa o con un campo de tipo incorrecto produce un error controlado que identifica el campo problemático.
  - Un tamaño de página por defecto o un tamaño máximo que no son enteros positivos se rechazan con un error controlado que los identifica, conforme a NFR-001.
  - La configuración no contiene ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Abrir `config/listado.yaml` y comprobar que contiene los tres campos con sus valores por defecto.
  2. Cambiar el tamaño máximo de página a `50`, recargar la configuración y comprobar que el nuevo valor es el que se aplica.

### [x] TASK-003 Adaptador de lectura en modo solo lectura

- **Cubre:** REQ-009, REQ-010, ALT-001, ALT-005, SUP-005, DEC-001
- **Componente:** listado-read-adapter | source/api/listado/read_adapter.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el componente que abre el fichero SQLite de `api-persistencia` configurado en modo **solo lectura (`mode=ro`)**, comprueba que el fichero existe y que contiene la tabla `ofertas` esperada, configura `busy_timeout` para amortiguar contenciones y cierra la conexión al terminar cada consulta, sin escribir, sin crear el fichero si no existe y sin modificar el esquema ni las migraciones de `api-persistencia`. Cuando el fichero no existe, no es un SQLite válido o carece de la tabla `ofertas`, el componente comunica un error controlado distinguible que permite a `listado-api` responder que no se puede acceder a los datos.
- **Hecho cuando:** con un fichero SQLite que simula el esquema real de `api-persistencia`, el adaptador abre la conexión en solo lectura y permite consultar la tabla `ofertas`; un intento de escritura sobre esa conexión es rechazado por SQLite; la conexión queda cerrada al terminar cada consulta; y ante una base inexistente, no migrada o corrupta el adaptador devuelve un error controlado que identifica el origen como un problema de acceso a la base de datos, sin crear ficheros.
- **Pruebas automáticas:**
  - La conexión se abre en modo solo lectura: un intento de escritura sobre ella es rechazado por SQLite, conforme a DEC-001 y REQ-010.
  - La lectura no crea el fichero `data/job_emcan.db` si no existe y devuelve un error controlado, conforme a ALT-001.
  - Un fichero SQLite válido sin la tabla `ofertas` produce un error controlado distinguible, conforme a ALT-001.
  - Un fichero que no es un SQLite válido produce un error controlado distinguible, conforme a ALT-001.
  - `PRAGMA busy_timeout` devuelve un valor mayor que cero tras abrir la conexión, conforme a ALT-005.
  - Tras la consulta, no queda ninguna conexión abierta sobre el fichero, conforme a DEC-001.
  - La marca de modificación del fichero SQLite de `api-persistencia` no cambia tras las lecturas, conforme a REQ-010.
  - El componente no escribe ni modifica ficheros bajo `source/api/persistencia/`.
- **Prueba manual:**
  1. Consultar sobre un fichero SQLite de prueba que simule el esquema de `api-persistencia` y comprobar que devuelve filas y que el fichero conserva su marca de modificación.
  2. Apuntar la configuración a una ruta inexistente y comprobar que la consulta falla con un error controlado que no crea el fichero.

### [x] TASK-004 Parser de fechas con guarda de patrón

- **Cubre:** REQ-005, REQ-009, ALT-004, SUP-004, DEC-003
- **Componente:** listado-date-parser | source/api/listado/date_parser.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el componente que valida fechas en formato `dd/mm/aaaa`, rechaza rangos invertidos y genera la expresión SQL que convierte `fecha_inicio_difusion` a texto ordenable ISO (`aaaa-mm-dd`) con una guarda explícita de patrón `GLOB` que devuelve `NULL` para fechas vacías, cadenas cortas o corruptas. El componente expone también la expresión de orden `ORDER BY <expr> IS NULL, <expr> DESC, codigo ASC`, de modo que las ofertas sin fecha válida queden siempre al final del listado.
- **Hecho cuando:** una fecha válida `15/11/2026` se valida y se convierte a `2026-11-15`; una fecha con formato incorrecto (`32/13/2026`, `2026-11-15`, `1/1/26`) se rechaza con un error controlado que indica que el formato esperado es `dd/mm/aaaa`; un rango con "desde" posterior a "hasta" se rechaza con un error controlado que lo identifica; y la expresión SQL generada convierte las fechas con patrón válido y devuelve `NULL` para las demás.
- **Pruebas automáticas:**
  - `15/11/2026` es una fecha válida y se convierte a `2026-11-15`, conforme a REQ-005.
  - `32/13/2026` se rechaza con un error que indica que el formato debe ser `dd/mm/aaaa`, conforme a REQ-009 y ALT-002.
  - `2026-11-15`, `1/1/26` y `15-11-2026` se rechazan con un error de formato, conforme a REQ-009.
  - Un rango con "desde" posterior a "hasta" se rechaza con un error controlado que lo identifica, conforme a REQ-009.
  - La expresión SQL contiene la guarda `GLOB` con el patrón `[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]` y la rama `ELSE NULL`, conforme a DEC-003.
  - Aplicada a una fila con `fecha_inicio_difusion` válida, la expresión devuelve el texto ISO; aplicada a una fila con la cadena vacía o con `20/11` devuelve `NULL`, conforme a ALT-004.
  - La expresión de orden sitúa los nulos detrás de las fechas válidas y desempata por `codigo` ascendente, conforme a REQ-007 y DEC-003.
  - `31/02/2026` (patrón válido pero fecha imposible) no se descarta por la guarda y ordena según el texto ISO resultante, conforme al test adicional de DEC-003.
- **Prueba manual:**
  1. Invocar el parser con `15/11/2026`, con `32/13/2026` y con un rango invertido y comprobar los mensajes devueltos.

### [x] TASK-005 Normalizador de texto insensible a mayúsculas y tildes

- **Cubre:** REQ-002, REQ-004, NFR-003, ALT-006, DEC-002
- **Componente:** listado-text-normalizer | source/api/listado/text_normalizer.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el componente que normaliza cadenas para la búsqueda insensible a mayúsculas y a tildes mediante `lower()` seguido de descomposición Unicode NFD y eliminación de diacríticos, de modo que el término buscado y los campos `ocupacion`, `municipio` y `texto_libre` se comparen en la misma forma normalizada. El componente también decide si un texto normalizado contiene el término normalizado, tratando la cadena vacía como campo sin valor que no aporta coincidencias.
- **Hecho cuando:** "Técnico" y "tecnico" se normalizan a la misma cadena, de modo que el término "tecnico" encuentra la ocupación "Técnico"; "Santander" y "santander" se normalizan igual; y el resultado de normalizar la cadena vacía es la cadena vacía, sin error.
- **Pruebas automáticas:**
  - Normalizar "Técnico" y "tecnico" produce la misma cadena, conforme a NFR-003.
  - Normalizar "Santander" y "santander" produce la misma cadena, conforme a REQ-004.
  - El término "tecnico" coincide con la ocupación "Técnico" y con "TÉCNICO", conforme a REQ-002 y NFR-003.
  - La enye se normaliza ("Año" y "ano" producen la misma cadena), conforme al test adicional de DEC-002.
  - Normalizar la cadena vacía devuelve la cadena vacía y no produce error, conforme a ALT-006.
  - Un término que solo aparecía en un texto purgado (vacío) no produce coincidencias, conforme a REQ-002 y ALT-006.
  - Un término parcial coincide con el texto que lo contiene, conforme a REQ-002.
- **Prueba manual:**
  1. Normalizar "Técnico", "TÉCNICO" y "tecnico" y comprobar que los tres resultados son idénticos.

### [x] TASK-006 Constructor de filtros parametrizado

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-006, ALT-007, DEC-002, DEC-003
- **Componente:** listado-filter-builder | source/api/listado/filter_builder.py
- **Módulo:** APP
- **Depende de:** TASK-004, TASK-005
- **Alcance:** Implementar el componente que traduce los filtros validados a una cláusula `WHERE` con parámetros posicionales: los filtros de estado, sector y rango de fechas se aplican en SQL; los filtros textuales (texto libre y, cuando se aplique, municipio con tolerancia a tildes) se omiten del `WHERE` y se señalan para su aplicación posterior en memoria. Los valores vacíos se tratan como "sin filtro". El filtro por `sector` se incluye aunque el campo se almacene siempre vacío, y el filtro por `oficina` no existe.
- **Hecho cuando:** sin filtros la cláusula `WHERE` no restringe y la lista de parámetros está vacía; con filtros de estado, sector y rango de fechas la cláusula contiene una condición por cada filtro y los valores viajan como parámetros posicionales; con texto libre o municipio con tolerancia a tildes, esa condición no aparece en la cláusula SQL y el componente informa de que el filtrado es textual; y ningún valor se concatena dentro del texto de la consulta.
- **Pruebas automáticas:**
  - Sin filtros, la cláusula `WHERE` está vacía y no hay parámetros, conforme a REQ-001.
  - Un filtro de municipio y otro de fecha activos a la vez generan condiciones combinadas con conjunción `AND`, conforme a REQ-001.
  - Un filtro de texto libre no aparece en la cláusula SQL y el componente informa de que el filtrado textual se aplica en memoria, conforme a DEC-002.
  - Un filtro de municipio con tolerancia a tildes no aparece en la cláusula SQL y el componente informa del filtrado textual, conforme a DEC-002 y REQ-004.
  - Un valor de filtro con comillas o con texto de SQL no altera la estructura de la consulta: se transmite como parámetro, conforme a REQ-010.
  - Los valores vacíos se ignoran y no generan condiciones, conforme a REQ-001.
  - El filtro por estado `vigente` por defecto y el que incluye `cerrada` generan las condiciones correspondientes, y `sin_ficha` nunca se incluye en el conjunto visible, conforme a REQ-006 y SUP-003.
  - El filtro por `sector` genera una condición por parámetro aunque no haya datos que la satisfagan, conforme a REQ-003 y ALT-007.
  - El constructor no genera ninguna condición sobre `oficina`, conforme a SUP-002.
- **Prueba manual:**
  1. Construir una cláusula con estado, sector y rango de fechas y comprobar que los valores aparecen como parámetros y no dentro del texto de la consulta.

### [x] TASK-007 Repositorio de consulta del listado

- **Cubre:** REQ-001, REQ-002, REQ-005, REQ-006, REQ-007, REQ-009, REQ-010, NFR-002, NFR-003, ALT-003, ALT-004, ALT-006, SUP-004, DEC-002, DEC-003
- **Componente:** listado-query-repository | source/api/listado/repository.py
- **Módulo:** APP
- **Depende de:** TASK-003, TASK-005, TASK-006
- **Alcance:** Implementar el componente que ejecuta la consulta del listado sobre la conexión de solo lectura: cuando no hay filtros textuales, calcula el total con `COUNT` en SQL y recupera la página con `LIMIT/OFFSET`; cuando hay filtros textuales, **no usa `LIMIT/OFFSET` en SQL antes de filtrar**, recupera todas las filas candidatas ya ordenadas por fecha de inicio descendente y código ascendente, normaliza y filtra en memoria, calcula el `total` como el número de filas resultantes del filtrado en memoria y solo entonces recorta la página. El componente devuelve la lista de ofertas, el total, la página, el tamaño y los filtros aplicados.
- **Hecho cuando:** sin filtros textuales, la consulta devuelve la página solicitada y el total coincide con el número de ofertas que cumplen los filtros; con filtros textuales, el total refleja el número de filas **después** del filtrado en memoria y la página se recorta sobre esa lista filtrada; el orden es por fecha de inicio descendente con desempate por código ascendente; y un `offset` mayor o igual que el total devuelve una lista vacía con el total real, sin error.
- **Pruebas automáticas:**
  - Con ofertas de fechas 30/11/2026, 20/11/2026 y 15/11/2026, el listado las devuelve en ese orden, conforme a REQ-007.
  - Con dos ofertas de la misma fecha y códigos `061234567890` y `061234567891`, la de código menor aparece primero, conforme a REQ-007 y SUP-004.
  - Sin filtros textuales, el total devuelto coincide con el número de ofertas que cumplen los filtros y la página se obtiene con `LIMIT/OFFSET`, conforme a DEC-002.
  - Con filtro de texto libre, la consulta SQL no aplica `LIMIT` ni `OFFSET` antes del filtrado: se recuperan todas las filas candidatas y la página se recorta tras filtrar en memoria, conforme a DEC-002.
  - Con filtro de texto libre, el `total` es el número de filas tras el filtrado en memoria, no el número de filas candidatas de SQL, conforme a REQ-002 y DEC-002.
  - Con 50 ofertas y tamaño de página 20, la página con desplazamiento 20 devuelve las ofertas 21 a 40, conforme a REQ-007.
  - Con un desplazamiento mayor o igual que el total, la lista devuelta está vacía y el total es el real, sin error, conforme a REQ-007 y ALT-003.
  - Con un filtro textual que no coincide con ninguna fila, la lista está vacía y el total es 0, conforme a REQ-009.
  - Con un filtro textual "tecnico", la oferta con ocupación "Técnico" aparece en el resultado y su total lo refleja, conforme a REQ-002 y NFR-003.
  - Con una oferta cuya `fecha_inicio_difusion` está vacía, esta aparece al final del listado y queda fuera de un filtro de rango de fechas, conforme a ALT-004 y SUP-004.
  - Una oferta con `texto_libre` o `contacto` vacíos por purga aparece en el listado con esos campos vacíos y no aparece al filtrar por un término que solo estaba en el texto, conforme a ALT-006.
  - Las ofertas en estado `sin_ficha` no aparecen nunca en el resultado, y las `cerrada` solo cuando se piden, conforme a REQ-006.
  - La consulta no modifica la base de datos: la marca de modificación del fichero y el número de filas de `ofertas` no cambian, conforme a REQ-010.
- **Prueba manual:**
  1. Consultar con un filtro textual que deje menos resultados que el total de SQL y comprobar que el `total` devuelto y la página se corresponden con el conjunto filtrado.

### [x] TASK-008 Endpoint del listado de ofertas

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, SUP-003, DEC-004, DEC-005, ALT-001, ALT-002, ALT-003
- **Componente:** listado-api | source/api/listado/routes.py
- **Módulo:** APP
- **Depende de:** TASK-004, TASK-006, TASK-007
- **Alcance:** Implementar el endpoint `GET /listado` con los filtros opcionales `texto`, `sector`, `municipio`, `fecha_desde`, `fecha_hasta`, `incluir_cerradas`, `offset` y `tamano_pagina`: valida los parámetros con el parser de fechas y las reglas de paginación antes de tocar la base de datos, orquesta los componentes del diseño y forma la respuesta JSON con la lista de ofertas y los metadatos (`total`, `pagina`, `tamano_pagina` y filtros aplicados). Cada oferta devuelta incluye comunidad, código, ocupación, municipio, provincia, sector, `fecha_inicio_difusion`, `fecha_fin_difusion`, estado, contacto y `texto_libre`. Los endpoints no exigen autenticación, como el resto de la API.
- **Hecho cuando:** un cliente puede consultar el listado con filtros combinables y paginación, la respuesta incluye la lista de ofertas con todos los campos exigidos y los metadatos de paginación y filtros aplicados; un parámetro inválido se rechaza con un error que indica qué parámetro falla y, en el caso de las fechas, el formato esperado, sin llegar a la base de datos; un tamaño de página superior al máximo se recorta al máximo y un tamaño menor o igual que cero se rechaza; y un listado sin coincidencias devuelve una lista vacía con total 0 y sin error.
- **Pruebas automáticas:**
  - Una consulta sin filtros devuelve las ofertas `vigente` con comunidad, código, ocupación, municipio, provincia, sector, `fecha_inicio_difusion`, `fecha_fin_difusion`, estado, contacto y `texto_libre`, conforme a REQ-008.
  - Los metadatos incluyen `total`, `pagina`, `tamano_pagina` y los filtros aplicados, conforme a REQ-008.
  - Varios filtros activos a la vez devuelven solo las ofertas que los cumplen todos, conforme a REQ-001.
  - Con `incluir_cerradas` activo aparecen las `vigente` y las `cerrada`; sin él solo las `vigente`; las `sin_ficha` nunca aparecen, conforme a REQ-006 y SUP-003.
  - Con un filtro por `sector` el resultado está vacío y la respuesta es válida, conforme a REQ-003 y ALT-007.
  - Con un filtro por municipio en minúsculas se obtienen las ofertas del municipio almacenado en mayúsculas, conforme a REQ-004.
  - Con un rango de fechas `10/11/2026` a `20/11/2026` solo aparece la oferta del 15/11/2026, conforme a REQ-005.
  - Con `fecha_desde` solo se incluyen las ofertas con fecha igual o posterior; con `fecha_hasta` solo, las de fecha igual o anterior, conforme a REQ-005.
  - Con un tamaño de página 150 el tamaño se recorta al máximo configurado y la respuesta lo refleja, conforme a NFR-001 y DEC-004.
  - Con un tamaño de página 50 se respeta el valor solicitado, conforme a NFR-001.
  - Con un tamaño de página cero o negativo, o con un desplazamiento negativo, la petición se rechaza con un error que identifica el parámetro, conforme a REQ-009 y ALT-002.
  - Con una fecha `32/13/2026` la petición se rechaza con un error que indica que el formato debe ser `dd/mm/aaaa`, conforme a REQ-009 y ALT-002.
  - Con un rango invertido la petición se rechaza con un error que lo identifica, conforme a REQ-009.
  - Un filtro que no produce coincidencias devuelve una lista vacía con total 0 y sin error, conforme a REQ-009.
  - Con un desplazamiento mayor o igual que el total, la respuesta es 200 con `items` vacío y metadatos coherentes, conforme a REQ-007 y ALT-003.
  - Con una base de datos inexistente o sin la tabla `ofertas`, la respuesta es un error controlado que indica que no se puede acceder a los datos, conforme a REQ-009 y ALT-001.
  - Una oferta con texto y contacto purgados se devuelve con esos campos vacíos y el resto de campos intactos, conforme a REQ-008 y ALT-006.
  - El endpoint no exige cabeceras de autenticación ni devuelve 401 o 403.
- **Prueba manual:**
  1. Consultar `GET /listado` con varios filtros y comprobar que la lista y los metadatos son los esperados.
  2. Consultar con una fecha mal formada y comprobar el mensaje de error y que la base de datos no se ha tocado.

### [x] TASK-009 Endpoint de filtros disponibles

- **Cubre:** REQ-003, REQ-008, DEC-005
- **Componente:** listado-api | source/api/listado/routes.py
- **Módulo:** APP
- **Depende de:** TASK-008
- **Alcance:** Implementar el endpoint `GET /listado/filtros` que devuelve los filtros soportados por el listado (texto, sector, municipio, `fecha_desde`, `fecha_hasta` e `incluir_cerradas`) con sus metadatos (tipo, formato y ejemplo), sin consultar la base de datos y sin exigir autenticación. El filtro por `oficina` no se anuncia, porque el campo no existe en el esquema de `api-persistencia`.
- **Hecho cuando:** la respuesta lista los filtros soportados con su tipo, formato y ejemplo, e incluye `sector` aunque hoy no haya datos que lo satisfagan; no incluye `oficina`; y el endpoint no escribe ni lee la base de datos.
- **Pruebas automáticas:**
  - La respuesta contiene los filtros `texto`, `sector`, `municipio`, `fecha_desde`, `fecha_hasta` e `incluir_cerradas`, conforme a REQ-003 y DEC-005.
  - Cada filtro anunciado lleva su tipo, su formato y su ejemplo, conforme a DEC-005.
  - El filtro `sector` figura como soportado aunque no haya ofertas con ese valor, conforme a REQ-003 y ALT-007.
  - La respuesta no anuncia ningún filtro por `oficina`, conforme a SUP-002.
  - Los filtros de fecha anuncian el formato `dd/mm/aaaa`, conforme a REQ-005.
  - El endpoint no modifica la base de datos ni su marca de modificación, conforme a REQ-010.
  - El endpoint no exige cabeceras de autenticación ni devuelve 401 o 403.
- **Prueba manual:**
  1. Consultar `GET /listado/filtros` y comprobar que aparecen los seis filtros con sus metadatos y que no aparece `oficina`.

### [x] TASK-010 Registro del router del listado en la aplicación

- **Cubre:** REQ-001, REQ-010, SUP-005, DEC-001
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-007, TASK-008, TASK-009
- **Alcance:** Integrar en el ciclo de vida de la aplicación FastAPI existente (`source/api/main.py`, con su `lifespan` y su `app_state`) la carga de la configuración del listado, la instanciación del adaptador de lectura, del constructor de filtros, del normalizador, del parser de fechas y del repositorio de consulta, y el registro del router con sus dos rutas, de modo que convivan en el mismo proceso el planificador de `api-buscador`, la `ingestion-task`, la `purge-task`, la `historico-task` y la `integridad-task`, sin modificar ninguno de esos módulos. Si la carga de la configuración del listado falla, el error se registra y la aplicación sigue arrancando sin la feature.
- **Hecho cuando:** al arrancar la aplicación, el router del listado queda registrado y sus dos rutas responden; el estado compartido del listado queda disponible en `app_state`; con una configuración del listado ausente o malformada el arranque registra el error y la aplicación sigue disponible sin la feature; y los endpoints existentes de `api-buscador`, `api-persistencia`, `api-historico` y `api-integridad` siguen respondiendo igual.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, `GET /listado` y `GET /listado/filtros` responden y no devuelven 404, conforme a REQ-001.
  - El router del listado no solapa sus rutas con las del buscador, de la persistencia, del histórico ni de la integridad.
  - Con una configuración del listado ausente o malformada, el arranque registra el error y la aplicación sigue disponible sin la feature, sin abortar el arranque de las demás.
  - Los endpoints de `api-buscador`, `api-persistencia`, `api-historico` y `api-integridad` siguen respondiendo igual después de integrar el listado.
  - La integración no modifica `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/` ni `source/api/parser.py`.
  - El arranque no altera el contenido ni la marca de modificación de `data/job_emcan.db`, conforme a REQ-010 y SUP-005.
- **Prueba manual:**
  1. Arrancar la aplicación y comprobar que `GET /listado` y `GET /listado/filtros` responden.
  2. Comprobar que los endpoints ya existentes siguen respondiendo igual.

### [x] TASK-011 Verificación de integración del listado

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, NFR-001, NFR-002, NFR-003, SUP-001, SUP-002, SUP-003, SUP-004, SUP-005, DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-010
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, la configuración, el adaptador de lectura, el parser de fechas, el normalizador de texto, el constructor de filtros, el repositorio y los endpoints, montando la aplicación con un fichero SQLite temporal que simule el esquema real de `api-persistencia` (ofertas `vigente`, `cerrada` y `sin_ficha`, con `sector` vacío, fechas en `dd/mm/aaaa` y `fecha_inicio_difusion` vacía en algún caso), y cubriendo los casos de filtros combinados, orden y desempate, paginación, filtro textual con tildes, filtro por sector, base inexistente o sin tabla, parámetros inválidos, lectura concurrente con la ingesta o la purga y oferta con texto purgado.
- **Hecho cuando:** con el esquema real simulado, el listado devuelve las ofertas con los campos y metadatos exigidos y con el orden y la visibilidad esperados; el filtro textual con tildes recupera la oferta "Técnico" y el `total` refleja el resultado tras el filtrado en memoria; un parámetro inválido o una base inaccesible producen el error controlado previsto; y ninguna consulta modifica la base de datos.
- **Pruebas automáticas:**
  - Con una base de prueba que simule el esquema real de `api-persistencia`, `GET /listado` devuelve las ofertas `vigente` con todos los campos exigidos por REQ-008, conforme a REQ-008.
  - Con filtros de municipio, sector y rango de fechas activos a la vez, solo aparecen las ofertas que los cumplen todos, conforme a REQ-001.
  - Con un filtro de texto "tecnico", la oferta con ocupación "Técnico" aparece en el resultado y el `total` es el del conjunto filtrado en memoria, conforme a REQ-002 y DEC-002.
  - Con un filtro de texto y un desplazamiento, la página se recorta sobre el conjunto ya filtrado y no sobre las filas candidatas de SQL, conforme a DEC-002.
  - Con ofertas de la misma fecha y códigos distintos, el desempate por código ascendente se respeta, conforme a REQ-007.
  - Con ofertas `vigente`, `cerrada` y `sin_ficha`, la consulta por defecto devuelve solo las `vigente`, con `incluir_cerradas` devuelve `vigente` y `cerrada`, y las `sin_ficha` nunca aparecen, conforme a REQ-006.
  - Con un filtro por `sector`, el resultado está vacío y la respuesta es válida, conforme a REQ-003 y ALT-007.
  - Con un `offset` mayor o igual que el total, la respuesta es 200 con lista vacía y total real, conforme a ALT-003.
  - Con una fecha mal formada o un rango invertido, la respuesta es un error controlado que no llega a la base de datos, conforme a REQ-009 y ALT-002.
  - Con un fichero de base de datos inexistente o sin la tabla `ofertas`, la respuesta es un error controlado que indica que no se puede acceder a los datos, conforme a ALT-001.
  - Con una oferta cuya `fecha_inicio_difusion` está vacía, esta aparece al final y queda fuera de los filtros de rango, conforme a ALT-004 y SUP-004.
  - Con una oferta con `texto_libre` y `contacto` purgados, aparece con esos campos vacíos y no coincide con un término que solo estaba en el texto, conforme a ALT-006.
  - Con una escritura concurrente simulada sobre la misma base, la lectura en `mode=ro` devuelve un conjunto consistente y no bloquea ni aborta al escritor, conforme a ALT-005.
  - Tras toda la integración, la base de datos de `api-persistencia` conserva su contenido y su marca de modificación, conforme a REQ-010 y SUP-005.
  - Los endpoints existentes de `api-buscador`, `api-persistencia`, `api-historico` y `api-integridad` siguen respondiendo igual, conforme a SUP-001.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio de datos tras la prueba: el fichero SQLite de `api-persistencia` conserva su contenido y no aparece ningún fichero nuevo.

### [x] TASK-012 Contrato: openapi - endpoints de consulta del listado

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, SUP-002, SUP-003, DEC-002, DEC-003, DEC-004, DEC-005
- **Componente:** listado-api | source/api/listado/routes.py
- **Módulo:** APP
- **Depende de:** TASK-009, TASK-011
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-listado.yaml` que formaliza los endpoints `GET /listado` (consulta filtrada y paginada de ofertas) y `GET /listado/filtros` (filtros soportados) tal como quedaron implementados: parámetros de texto, sector, municipio, `fecha_desde`, `fecha_hasta`, `incluir_cerradas`, `offset` y `tamano_pagina`; esquema de oferta con todos los campos exigidos por REQ-008; metadatos de paginación y filtros aplicados; y respuestas de error por parámetro inválido y por base de datos inaccesible.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-listado.yaml`, describe las dos operaciones con sus esquemas de entrada y salida y sus respuestas de error, y coincide con la implementación verificada en TASK-011.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las dos operaciones con sus respuestas 200.
  - El esquema de oferta del contrato incluye comunidad, código, ocupación, municipio, provincia, sector, `fecha_inicio_difusion`, `fecha_fin_difusion`, estado, contacto y `texto_libre`, conforme a REQ-008.
  - El esquema de los metadatos incluye `total`, `pagina`, `tamano_pagina` y los filtros aplicados, conforme a REQ-008.
  - El contrato documenta las respuestas de error por fecha mal formada, por rango invertido y por base de datos inaccesible, conforme a REQ-009 y ALT-001.
  - El contrato documenta el tamaño máximo de página y el recorte de un tamaño superior, conforme a NFR-001 y DEC-004.
  - El contrato documenta que el filtro por sector existe aunque hoy no haya datos que lo satisfagan, y que no existe filtro por oficina, conforme a REQ-003 y SUP-002.
  - El contrato documenta que los códigos se devuelven como texto de 12 dígitos y las fechas de difusión en `dd/mm/aaaa`, conforme a DEC-003 y SUP-003.
  - Las rutas y los campos del contrato coinciden con los que devuelve la implementación en la prueba de integración.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las dos interfaces de la fila de contratos afectados.
  2. Comparar el contrato con las respuestas JSON reales obtenidas en TASK-011 y confirmar que no hay campos divergentes.

### [x] TASK-013 Contrato: configuración - fichero de configuración del listado

- **Cubre:** REQ-009, NFR-001, DEC-006
- **Componente:** config-listado | config/listado.yaml
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-010
- **Alcance:** Formalizar el contrato de configuración del listado: documentar el formato exacto del fichero `config/listado.yaml` (ruta de la base de datos, tamaño de página por defecto y tamaño máximo de página) y sus valores por defecto, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación aplica en TASK-010.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/listado.yaml` se carga con el formato documentado y devuelve la ruta, el tamaño de página por defecto y el tamaño máximo de página.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Una configuración con un tipo incorrecto se rechaza con un error controlado, conforme a NFR-001.
  - Los valores por defecto documentados (`data/job_emcan.db`, `20` y `100`) coinciden con los que aplica la implementación, conforme a DEC-006.
  - El contrato documenta que la ruta del SQLite de persistencia se usa en modo solo lectura (`mode=ro`), conforme a DEC-001.
  - El contrato no documenta ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración del listado) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### [x] TASK-014 Verificación de solo lectura, rendimiento y aislamiento de la feature

- **Cubre:** REQ-010, NFR-002, NFR-003, SUP-001, SUP-005, DEC-001, DEC-002, ALT-005
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-011
- **Alcance:** Verificar de extremo a extremo las garantías transversales de la feature con una base de datos de prueba: (a) solo lectura: la consulta del listado no crea, modifica ni elimina ofertas ni ningún otro registro y no altera la marca de modificación del fichero; (b) rendimiento: con 500 ofertas vigentes, el listado filtrado se devuelve en menos de 2 segundos, con y sin filtro textual; (c) aislamiento: `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` y `api-integridad` no han sido modificados por la feature y el código del listado no contiene operaciones de escritura sobre ofertas.
- **Hecho cuando:** con 500 ofertas vigentes, la respuesta del listado sin filtros y con filtro textual llega en menos de 2 segundos; tras todas las consultas, el número de filas de la tabla `ofertas` y la marca de modificación del fichero no han cambiado; y ninguna operación `INSERT`, `UPDATE` o `DELETE` sobre ofertas aparece en el código del paquete `source/api/listado/`.
- **Pruebas automáticas:**
  - Con 500 ofertas vigentes, el listado sin filtros responde en menos de 2 segundos, conforme a NFR-002.
  - Con 500 ofertas vigentes y un filtro textual, el listado responde en menos de 2 segundos, conforme a NFR-002 y DEC-002.
  - El filtrado textual con 500 ofertas candidatas no degrada el tiempo de respuesta por encima del límite, conforme al coste declarado en DEC-002.
  - El número de filas de la tabla `ofertas` es idéntico antes y después de una tanda de consultas del listado, conforme a REQ-010.
  - La marca de modificación del fichero SQLite de `api-persistencia` no cambia tras una tanda de consultas, conforme a REQ-010 y SUP-005.
  - Una comparación del contenido del fichero antes y después de las consultas no detecta diferencias, conforme a REQ-010.
  - El código del paquete `source/api/listado/` no contiene llamadas de escritura (`INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `DROP`) sobre la tabla `ofertas`, conforme a REQ-010 y DEC-001.
  - La lectura en `mode=ro` con `busy_timeout` no bloquea una escritura concurrente simulada sobre la misma base, conforme a ALT-005.
  - Una comparación de los ficheros de `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/`, `source/api/integridad/` y `source/api/parser.py` confirma que la feature no los ha modificado, conforme a SUP-001.
- **Prueba manual:**
  1. Ejecutar la prueba de rendimiento con 500 ofertas y revisar el tiempo medido en el informe: queda por debajo de 2 segundos.
  2. Revisar el registro de la base de datos de prueba antes y después: el contenido es idéntico.

### [x] TASK-015 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-012, TASK-013, TASK-014
- **Alcance:** Actualizar `.sdd/architecture.md` en tres puntos y solo en esos tres: (a) la línea del módulo `API`, cuya responsabilidad pasa a incluir también el listado filtrable de ofertas; (b) añadir a la sección de contratos la entrada `openapi | docs/contracts/openapi/api-listado.yaml | cliente -> api-listado`; y (c) añadir a la sección de contratos la entrada `configuracion | config/listado.yaml | api-listado -> config-listado`. El mapa **no** gana entradas de módulo para los componentes internos del listado, que son detalle de implementación dentro del módulo `API` y no reciben identificador propio en el mapa.
- **Hecho cuando:** la línea del módulo `API` de `.sdd/architecture.md` menciona el listado filtrable en su responsabilidad; la sección de contratos contiene las dos entradas nuevas (`openapi` del listado y `configuracion` de `config/listado.yaml`); y la sección de módulos no contiene ninguna entrada nueva para los componentes internos del listado.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que la línea del módulo `API` incluye el listado filtrable en su descripción de responsabilidad.
  - Una comprobación confirma que la sección de contratos incluye la entrada `openapi | docs/contracts/openapi/api-listado.yaml | cliente -> api-listado`.
  - Una comprobación confirma que la sección de contratos incluye la entrada `configuracion | config/listado.yaml | api-listado -> config-listado`.
  - Una comprobación confirma que la sección de módulos no ha ganado entradas para los componentes internos del listado (adaptador de lectura, parser de fechas, normalizador de texto, constructor de filtros, repositorio y endpoints) ni para el subpaquete `source/api/listado`.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que la línea del módulo `API` incluye el listado en su responsabilidad y que la sección de contratos contiene las dos entradas nuevas.
  2. Revisar la sección de módulos del mapa y comprobar que no se ha añadido ninguna entrada para los componentes internos del listado.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-006, TASK-007, TASK-008, TASK-010, TASK-011, TASK-012 |
| REQ-002 | TASK-005, TASK-006, TASK-007, TASK-008, TASK-011, TASK-012 |
| REQ-003 | TASK-006, TASK-008, TASK-009, TASK-011, TASK-012 |
| REQ-004 | TASK-005, TASK-006, TASK-008, TASK-011, TASK-012 |
| REQ-005 | TASK-004, TASK-006, TASK-007, TASK-008, TASK-011, TASK-012 |
| REQ-006 | TASK-006, TASK-007, TASK-008, TASK-011, TASK-012 |
| REQ-007 | TASK-004, TASK-007, TASK-008, TASK-011, TASK-012 |
| REQ-008 | TASK-008, TASK-009, TASK-011, TASK-012 |
| REQ-009 | TASK-002, TASK-003, TASK-004, TASK-007, TASK-008, TASK-011, TASK-012, TASK-013 |
| REQ-010 | TASK-001, TASK-003, TASK-006, TASK-007, TASK-010, TASK-011, TASK-014 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-002, TASK-008, TASK-011, TASK-012, TASK-013 |
| NFR-002 | TASK-007, TASK-011, TASK-014 |
| NFR-003 | TASK-005, TASK-007, TASK-011, TASK-014 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-002, TASK-003, TASK-007, TASK-010, TASK-011, TASK-013, TASK-014, TASK-015 |
| DEC-002 | TASK-001, TASK-005, TASK-006, TASK-007, TASK-011, TASK-012, TASK-014, TASK-015 |
| DEC-003 | TASK-004, TASK-006, TASK-007, TASK-011, TASK-012, TASK-015 |
| DEC-004 | TASK-008, TASK-011, TASK-012, TASK-015 |
| DEC-005 | TASK-008, TASK-009, TASK-011, TASK-012, TASK-015 |
| DEC-006 | TASK-002, TASK-011, TASK-013, TASK-015 |

| Supuesto | Tareas |
|---|---|
| SUP-001 | TASK-006, TASK-011, TASK-012, TASK-014 |
| SUP-002 | TASK-006, TASK-009, TASK-012 |
| SUP-003 | TASK-006, TASK-008, TASK-012 |
| SUP-004 | TASK-004, TASK-007, TASK-011 |
| SUP-005 | TASK-001, TASK-003, TASK-007, TASK-010, TASK-011, TASK-014 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-003, TASK-008, TASK-011, TASK-012 |
| ALT-002 | TASK-004, TASK-008, TASK-011 |
| ALT-003 | TASK-007, TASK-008, TASK-011 |
| ALT-004 | TASK-004, TASK-007, TASK-011 |
| ALT-005 | TASK-003, TASK-011, TASK-014 |
| ALT-006 | TASK-005, TASK-007, TASK-008, TASK-011 |
| ALT-007 | TASK-006, TASK-008, TASK-009, TASK-011 |

## Avisos

- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-012 depende de TASK-009 y TASK-011, y TASK-013 depende de TASK-002 y TASK-010.
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
- Los componentes del listado (`api-listado`, `config-listado`, `listado-read-adapter`, `listado-query-repository`, `listado-filter-builder`, `listado-date-parser`, `listado-text-normalizer` y `listado-api`) son **detalle de implementación interno del módulo `API`**: no reciben identificador propio en `.sdd/architecture.md` y no se proponen como módulos nuevos del mapa, conforme a `design@2`. Las tareas que los implementan los citan en su línea `Componente` (con la ruta interna dentro de `source/api/listado/`) y llevan su línea `Módulo` con el identificador `APP`, que es la etiqueta del trabajo; el código permanece en `source/api/listado/`.
- TASK-015 no registra módulos nuevos del listado. Su alcance se limita a actualizar la línea del módulo `API` de `.sdd/architecture.md` para que su responsabilidad incluya el listado filtrable, a añadir las dos entradas de contrato (`openapi | docs/contracts/openapi/api-listado.yaml | cliente -> api-listado` y `configuracion | config/listado.yaml | api-listado -> config-listado`) y a comprobar que el mapa no gana entradas de módulo para los componentes internos del listado.
- `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` y `api-integridad` no se modifican en ninguna tarea. La compatibilidad se resuelve solo desde `api-listado`, con lectura directa en modo solo lectura `mode=ro` de `data/job_emcan.db` (TASK-003 y TASK-007), el mismo criterio validado por `api-historico` en SUP-004, conforme a DEC-001.
- La regla central de DEC-002 queda explícita en TASK-007: con filtro textual **no** se usa `LIMIT/OFFSET` en SQL antes de filtrar, las filas candidatas se recuperan ya ordenadas por fecha de inicio descendente y código ascendente, el filtrado se hace en memoria y el `total` se calcula sobre el conjunto ya filtrado; el `COUNT` en SQL solo se usa cuando no hay filtros textuales. TASK-008 y TASK-011 comprueban el mismo comportamiento desde el endpoint y desde la integración.
- El diseño no fija el prefijo de las rutas de `listado-api`. Se adopta por defecto el prefijo `/listado`, coherente con los endpoints `GET /listado` y `GET /listado/filtros` que fija DEC-005; si la capa técnica adopta otro, el cambio queda limitado a TASK-008, TASK-009, TASK-011 y TASK-012.
- El diseño no fija el nombre de los parámetros de consulta del endpoint. Se adoptan por defecto `texto`, `sector`, `municipio`, `fecha_desde`, `fecha_hasta`, `incluir_cerradas`, `offset` y `tamano_pagina`, que son los nombres que aparecen en la descripción del flujo principal de `design@2`; si la capa técnica usa otros, el cambio queda limitado a TASK-008, TASK-009, TASK-011 y TASK-012.
- El diseño no fija la granularidad de los metadatos de `GET /listado/filtros` ni sus nombres exactos. TASK-009 se limita a lo exigible: cada filtro soportado se anuncia con su tipo, su formato y su ejemplo.
- REQ-008 exige devolver `provincia`, que existe en el esquema real de `api-persistencia` pero no se menciona en la lista de campos del modelo de datos lógico de `design@2`; TASK-008 lo incluye porque el requisito lo nombra explícitamente y la columna existe en el esquema documentado.
- El filtro por `sector` se implementa aunque hoy el campo se almacene siempre vacío (DEC-009 de `api-persistencia`): el resultado será vacío hasta que exista una feature que persista el sector, conforme a SUP-001 y ALT-007. El filtro por `oficina` no se implementa porque el campo no existe en el esquema, conforme a SUP-002.
- REQ-009 y DEC-004 interpretan "página fuera de rango" como valores negativos o inválidos de `offset` o del tamaño de página; un `offset` válido mayor o igual que el total devuelve una página vacía con el total real, sin error, conforme a REQ-007 y ALT-003.
- La lectura concurrente con la ingesta o la purga (ALT-005) se cubre con la conexión `mode=ro` y el `busy_timeout` de TASK-003, y se verifica en TASK-011 y TASK-014. `api-listado` no bloquea a los escritores de `api-persistencia`.
- El documento contiene 15 tareas (TASK-001..TASK-015); la numeración es continua y no hay huecos. El apartado "Orden de implementación" los agrupa en 8 pasos numerados, cada uno con las tareas que encadenan.
