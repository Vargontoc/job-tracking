# Tareas: api-integridad

Estado: aprobado
Revisión: 1
Basado en: requirements@2, design@3
Verificación: correcta

## Resumen

El trabajo se divide en veintiuna tareas (TASK-001..TASK-021) que siguen la cadena de dependencias del diseño: primero la estructura del paquete y la configuración, después el almacén de PDFs y metadatos (escritura atómica, hash SHA-256, `.meta.json` y PDF huérfano) y la purga por fecha del nombre, luego los tres adaptadores (descarga en proceso, parseo en proceso y `GET /buscador/status`), el comparador con su veredicto, el almacén de avisos y el índice de ejecuciones, a continuación la tarea diaria con su idempotencia y su lógica de catch-up, el arranque y apagado en el proceso FastAPI, los tres endpoints de consulta, la verificación de integración, las dos tareas de contrato (`implementation-first`) y por último la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

Los componentes de la integridad son detalle de implementación interno del módulo `API` y no reciben identificador propio en el mapa de arquitectura: todas las tareas llevan su línea `Módulo` con el identificador `APP`, aunque el código viva en `source/api/integridad/`. La actualización del mapa (TASK-021) se limita a la línea del módulo `API` y a los dos contratos nuevos.

`api-integridad` no modifica `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`: la integración es por contrato HTTP (`GET /buscador/status`), por invocación en proceso de `source/api/downloader.py` y `source/api/parser.py` y por convivencia de tareas programadas en el mismo proceso FastAPI.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Configuración de la integridad.
2. TASK-003 Almacén de PDFs y metadatos → TASK-004 PDF huérfano y listado de conservados → TASK-005 Purga por fecha del nombre.
3. TASK-006 Adaptador de descarga → TASK-007 Adaptador de parseo → TASK-008 Adaptador del estado del buscador.
4. TASK-009 Comparador y veredicto → TASK-010 Avisos → TASK-011 Índice de ejecuciones.
5. TASK-012 Tarea diaria programada → TASK-013 Catch-up con margen.
6. TASK-014 Arranque y apagado en la aplicación.
7. TASK-015 Último veredicto → TASK-016 Ejecuciones del último mes → TASK-017 PDFs conservados.
8. TASK-018 Verificación de integración.
9. TASK-019..TASK-020 Contratos (implementation-first).
10. TASK-021 Actualización del mapa (descripción del módulo `API` y dos contratos).

## Tareas

### [ ] TASK-001 Estructura del paquete de la integridad y dependencias

- **Cubre:** REQ-001, REQ-002, SUP-003, SUP-005, DEC-001, DEC-003
- **Componente:** integridad-task | source/api/integridad
- **Módulo:** APP
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/integridad/` con su `__init__.py` y los módulos hosting de los componentes del diseño (`config.py`, `pdf_store.py`, `purger.py`, `downloader_adapter.py`, `parser_adapter.py`, `buscador_client.py`, `comparador.py`, `avisos.py`, `ejecuciones.py`, `task.py`, `routes.py`), y declarar en `pyproject.toml` las dependencias que exige el diseño (`httpx` para el cliente HTTP de `GET /buscador/status`, `pdfplumber` para el parseo en proceso del PDF de difusión, `pyyaml` para la carga de `config/integridad.yaml`, la librería de zona horaria estándar para NFR-004 y el mecanismo de planificación en proceso), sin introducir motor de base de datos servidor ni extensión vectorial.
- **Hecho cuando:** el subpaquete `source/api/integridad` se importa sin errores, las dependencias declaradas cubren las que usa el diseño y el runner de pruebas recorre `tests/` sin fallos de colección; y el paquete no modifica ni importa de forma que los altere `api-buscador`, `api-persistencia`, `api-pdf-parser` ni `api-historico`.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.integridad` ni de las dependencias declaradas.
  - Una comprobación confirma que `httpx`, `pdfplumber`, `yaml` y el soporte de zona horaria están disponibles en el entorno de pruebas.
  - El paquete no importa ni referencia un motor de base de datos servidor (SQLAlchemy, PostgreSQL, MySQL) ni una extensión de SQLite para vectores.
  - El paquete no escribe ni modifica ficheros bajo `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/` ni `source/api/parser.py`, `source/api/downloader.py` y `source/api/assembler.py`, conforme a SUP-005.
  - El paquete no crea ni abre ningún fichero SQLite propio, conforme a DEC-001.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [ ] TASK-002 Fichero de configuración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, NFR-001, NFR-002, NFR-004, SUP-001, SUP-003, DEC-001, DEC-005, DEC-007
- **Componente:** config-integridad | config/integridad.yaml
- **Módulo:** APP
- **Depende de:** TASK-001
- **Alcance:** Crear el fichero de configuración `config/integridad.yaml` con la zona horaria (por defecto `Europe/Madrid`), la hora de ejecución diaria (por defecto `2`, es decir 02:00, tras la pasada del buscador configurada a la 01:00 en `config/buscador.yaml`), el margen de catch-up `margen_catchup` en minutos (por defecto `60`), los días de retención de los PDFs (por defecto `30`), la tolerancia absoluta (por defecto `1`), la tolerancia relativa en porcentaje (por defecto `5`), el umbral de cordura del recuento del PDF (por defecto `70`), la ruta base de los PDFs (por defecto `data/pdfs`), la URL base del buscador (por defecto `http://localhost:8000`) y las comunidades configuradas (por defecto, las entradas de `config/comunidades.yaml`), e implementar su carga con valores por defecto y error controlado ante fichero ausente o malformado.
- **Hecho cuando:** la carga devuelve la configuración completa con los valores por defecto del diseño cuando no se indican otros, un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, la zona horaria cargada es válida y utilizable para obtener la fecha local, la hora es un entero en el rango 0-23, el margen de catch-up es un entero mayor o igual que cero y las rutas son relativas a la raíz del proyecto.
- **Pruebas automáticas:**
  - La carga del fichero `config/integridad.yaml` devuelve zona horaria, hora de ejecución, margen de catch-up, días de retención, tolerancias, umbral de cordura, ruta base de PDFs, URL base del buscador y lista de comunidades.
  - Sin fichero de configuración, la zona horaria es `Europe/Madrid`, la hora es `2`, el margen de catch-up es `60`, los días de retención son `30`, la tolerancia absoluta es `1`, la tolerancia relativa es `5` y el umbral de cordura es `70`, conforme a NFR-001, NFR-002, SUP-001 y DEC-007.
  - Un fichero con YAML malformado, con un submapa que no es un mapa o con un campo de tipo incorrecto produce un error controlado que identifica el campo problemático.
  - Una zona horaria inválida se rechaza con un error controlado que la identifica, conforme a NFR-004.
  - Una hora fuera del rango 0-23, con minutos, con fracciones o como lista se rechaza con un error controlado que la identifica, conforme a NFR-001.
  - Un margen de catch-up negativo o no entero se rechaza con un error controlado que lo identifica, conforme a DEC-007.
  - Un umbral de cordura o una tolerancia negativa se rechazan con un error controlado que los identifica, conforme a NFR-002.
  - La configuración no contiene ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Abrir `config/integridad.yaml` y comprobar que contiene los campos con sus valores por defecto.
  2. Cambiar la hora a `5` y el margen de catch-up a `30`, recargar la configuración y comprobar que los nuevos valores son los que se aplican.

### [ ] TASK-003 Almacén de PDFs y de metadatos del día

- **Cubre:** REQ-002, REQ-005, NFR-003, SUP-001, SUP-003, DEC-001, DEC-002, DEC-003, ALT-003, ALT-007
- **Componente:** pdf-store | source/api/integridad/pdf_store.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el almacén que gestiona el árbol `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y su fichero de metadatos asociado `data/pdfs/<comunidad>/<aaaa-mm-dd>.meta.json`: escritura del PDF de forma atómica (fichero temporal en el mismo directorio y `rename` al nombre definitivo), cálculo del hash SHA-256 del contenido, escritura y lectura atómica del `.meta.json` con los campos del modelo de datos lógico (hash, recuento del PDF, recuento del buscador, diferencia, tolerancias, umbral de cordura, veredicto, errores y marca de tiempo), y escritura de un `.meta.json` en estado `fallido` cuando la descarga falla, sin conservar PDF.
- **Hecho cuando:** tras guardar un PDF, existe `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y su `data/pdfs/<comunidad>/<aaaa-mm-dd>.meta.json` con el hash SHA-256 del contenido y los campos del día; el PDF queda visible en el nombre definitivo solo tras el `rename`, sin ficheros temporales remanentes; un `.meta.json` en estado `fallido` existe sin PDF asociado; y el hash guardado coincide con el SHA-256 del contenido del PDF.
- **Pruebas automáticas:**
  - Tras escribir un PDF, existe el fichero en `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y el nombre permite identificar la fecha y la comunidad, conforme a REQ-002 y SUP-003.
  - El hash registrado en el `.meta.json` coincide con el SHA-256 calculado sobre el contenido del PDF, conforme a DEC-003.
  - La escritura del PDF es atómica: durante la escritura no existe el fichero con el nombre definitivo incompleto y tras ella no queda ningún fichero temporal en el directorio de la comunidad, conforme a DEC-001.
  - La escritura del `.meta.json` es atómica: tras ella no queda ningún fichero temporal en el directorio de la comunidad y el `.meta.json` resultante es JSON válido.
  - Un `.meta.json` en estado `fallido` con el mensaje de error se escribe y no queda PDF asociado, conforme a ALT-003 y DEC-002.
  - El `.meta.json` incluye los campos hash, recuento del PDF, recuento del buscador, diferencia, tolerancias aplicadas, umbral de cordura, veredicto, errores y marca de tiempo, conforme a REQ-005.
  - La lectura de un `.meta.json` devuelve sus campos; un `.meta.json` ilegible o corrupto se comunica como tal y no se interpreta como un día válido, conforme al riesgo de metadatos corruptos de `design@3`.
  - El almacén no crea ni abre ningún fichero SQLite, conforme a DEC-001.
  - El directorio de la comunidad se crea si no existe.
- **Prueba manual:**
  1. Guardar un PDF de prueba y revisar `data/pdfs/<comunidad>/`: aparecen el PDF y el `.meta.json` con el hash, y no queda ningún fichero temporal.

### [ ] TASK-004 PDF huérfano y listado de PDFs conservados

- **Cubre:** REQ-002, REQ-005, REQ-009, SUP-003, DEC-002, ALT-007
- **Componente:** pdf-store | source/api/integridad/pdf_store.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar, sobre el mismo almacén, la detección y el tratamiento del PDF huérfano (existe el PDF del día pero no su `.meta.json`, por escritura interrumpida): se lo considera reprocesable, se recalcula su hash y se genera el `.meta.json` a partir del parseo; y el listado de los PDFs conservados, que devuelve por cada uno su fecha, su comunidad y su ruta identificable.
- **Hecho cuando:** ante un PDF del día sin `.meta.json`, el almacén informa de que el día está incompleto y permite regenerar sus metadatos; el listado de PDFs conservados devuelve un elemento por cada `<aaaa-mm-dd>.pdf` existente con fecha, comunidad y ruta; y un `.meta.json` ilegible no impide listar el resto.
- **Pruebas automáticas:**
  - Un PDF del día sin `.meta.json` se detecta como huérfano y se comunica como tal, conforme a ALT-007.
  - Regenerados los metadatos del PDF huérfano, existe su `.meta.json` con el hash recalculado y los campos del día, conforme a ALT-007.
  - El listado de PDFs conservados devuelve un elemento por cada PDF existente con su fecha, su comunidad y su ruta identificable, conforme a REQ-009.
  - Un `.meta.json` ilegible se omite del listado de metadatos sin impedir listar el resto, conforme al riesgo de metadatos corruptos de `design@3`.
  - Un directorio de comunidad vacío o inexistente no produce error en el listado, conforme a REQ-009.
  - El almacén no crea ni abre ningún fichero SQLite, conforme a DEC-001.
- **Prueba manual:**
  1. Colocar un PDF suelto sin `.meta.json` en el directorio de una comunidad y ejecutar el listado: aparece como PDF conservado y se informa del día incompleto.

### [ ] TASK-005 Purga de PDFs por la fecha del nombre

- **Cubre:** REQ-002, SUP-003, DEC-002, DEC-004
- **Componente:** pdf-purger | source/api/integridad/purger.py
- **Módulo:** APP
- **Depende de:** TASK-004
- **Alcance:** Implementar la purga que recorre el árbol `data/pdfs/<comunidad>/` y elimina los ficheros `<aaaa-mm-dd>.pdf` y `<aaaa-mm-dd>.meta.json` cuya fecha, extraída del nombre y no del `mtime`, sea más antigua que el período de retención configurado, nunca eliminando el fichero del día en curso ni los de la ventana de retención.
- **Hecho cuando:** tras la purga, no queda ningún PDF ni `.meta.json` con una fecha más antigua que la ventana de retención; los ficheros con 30 días o menos de antigüedad se conservan; el PDF y los metadatos del día en curso se conservan siempre; y la antigüedad se determina por la fecha del nombre aunque la marca de modificación del fichero sea más reciente.
- **Pruebas automáticas:**
  - Un PDF con más de 30 días de antigüedad en su nombre se elimina junto con su `.meta.json`, conforme a REQ-002.
  - Un PDF con exactamente 30 días de antigüedad en su nombre se conserva, conforme a REQ-002.
  - Un PDF con menos de 30 días de antigüedad se conserva, conforme a REQ-002.
  - El PDF y el `.meta.json` del día en curso nunca se eliminan, conforme a REQ-002.
  - La antigüedad se calcula por la fecha del nombre y no por la marca de modificación: un fichero antiguo con `mtime` reciente se elimina, conforme a DEC-004.
  - Con los días de retención configurados a `7`, la ventana de retención aplicada es de 7 días, conforme a NFR-002 implícito en la configuración de TASK-002.
  - Un PDF con parseo fallido y su `.meta.json` se purgan con el mismo plazo que los demás, conforme a DEC-002.
  - La purga no toca ficheros cuyo nombre no sigue el patrón `<aaaa-mm-dd>.pdf`, conforme a DEC-004.
  - La purga no crea ni abre ningún fichero SQLite, conforme a DEC-001.
- **Prueba manual:**
  1. Preparar PDFs con nombres de hace 40, 30 y 5 días y ejecutar la purga: solo desaparece el de 40 días.

### [ ] TASK-006 Adaptador de descarga del PDF de difusión

- **Cubre:** REQ-001, REQ-002, SUP-003, SUP-005, DEC-002, ALT-003
- **Componente:** downloader-adapter | source/api/integridad/downloader_adapter.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el adaptador que descarga el PDF de difusión de una comunidad invocando **en proceso** el módulo descargador existente (`source/api/downloader.py`) y normaliza su resultado para el almacén: devuelve los bytes del PDF o un error controlado distinguible (error HTTP, tiempo de espera agotado o error de conexión), sin reimplementar la descarga ni llamar al endpoint `GET /parse`.
- **Hecho cuando:** con un descargador simulado que devuelve bytes, el adaptador devuelve esos bytes y no escribe nada en disco por sí mismo; con un descargador que devuelve un error controlado, el adaptador lo propaga de forma distinguible sin lanzar excepción; y el adaptador no emite ninguna petición HTTP al endpoint `GET /parse` de la propia API.
- **Pruebas automáticas:**
  - Con un cliente de prueba que responde con un PDF válido, el adaptador devuelve los bytes del PDF, conforme a REQ-001.
  - Con un error HTTP, el adaptador devuelve un error controlado distinguible que incluye el mensaje, conforme a ALT-003.
  - Con un tiempo de espera agotado o un error de conexión, el adaptador devuelve un error controlado distinguible, conforme a ALT-003.
  - El adaptador invoca el descargador en proceso: no se realiza ninguna llamada HTTP a `GET /parse` ni a ningún otro endpoint de la API, conforme a SUP-005.
  - El adaptador no modifica `source/api/downloader.py` ni `source/api/assembler.py`.
  - El adaptador no descarga fichas individuales del buscador, conforme al alcance de la feature.
- **Prueba manual:**
  1. Invocar el adaptador con la URL real del PDF de difusión y comprobar que devuelve los bytes y que en el registro no aparece ninguna petición a `/parse`.

### [ ] TASK-007 Adaptador de parseo del PDF de difusión

- **Cubre:** REQ-003, REQ-004, SUP-003, SUP-005, DEC-002, ALT-004
- **Componente:** parser-adapter | source/api/integridad/parser_adapter.py
- **Módulo:** APP
- **Depende de:** TASK-006
- **Alcance:** Implementar el adaptador que extrae el recuento de ofertas del PDF descargado invocando **en proceso** el módulo de parseo existente (`source/api/parser.py`), sin reescribir la lógica de parseo ni llamar al endpoint `GET /parse`: devuelve el número de ofertas extraídas y la comunidad, y un error de parseo controlado cuando el PDF no es legible.
- **Hecho cuando:** con un PDF de difusión válido, el adaptador devuelve el número de ofertas extraídas y la comunidad; con bytes que no son un PDF legible, devuelve un error de parseo controlado distinguible; y el adaptador no emite ninguna petición HTTP a la propia API.
- **Pruebas automáticas:**
  - Con un PDF de prueba con ofertas conocidas, el adaptador devuelve el número exacto de ofertas extraídas y la comunidad, conforme a REQ-003.
  - Con un PDF ilegible o corrupto, el adaptador devuelve un error de parseo controlado, distinguible del error de descarga, conforme a ALT-004.
  - Con un PDF válido pero sin ninguna oferta, el adaptador devuelve un recuento de cero sin error, conforme a ALT-004.
  - El adaptador invoca el parser en proceso: no se realiza ninguna llamada HTTP a `GET /parse` ni a ningún otro endpoint de la API, conforme a SUP-005.
  - El adaptador no modifica `source/api/parser.py` ni `source/api/assembler.py`.
- **Prueba manual:**
  1. Invocar el adaptador con el PDF real de difusión y comprobar que devuelve un recuento cercano a 92 ofertas, el valor observado el 10/11/2026.

### [ ] TASK-008 Adaptador del estado del buscador

- **Cubre:** REQ-003, REQ-006, SUP-004, SUP-006, DEC-005, ALT-005, ALT-006
- **Componente:** buscador-status-adapter | source/api/integridad/buscador_client.py
- **Módulo:** APP
- **Depende de:** TASK-002
- **Alcance:** Implementar el cliente HTTP que consulta `GET /buscador/status` en la URL base configurada y normaliza la respuesta real del buscador (`in_progress`, `progreso`, `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global` y `errores_por_oferta`): expone el `total_listado` y distingue de forma explícita el error HTTP o de red, la `ultima_pasada` nula y el `error_global` no vacío. No lanza pasadas del buscador ni descarga fichas.
- **Hecho cuando:** el adaptador devuelve el estado publicado por el buscador con la estructura real de `GET /buscador/status` y, ante un error HTTP o de red, una `ultima_pasada` nula o un `error_global` no vacío, comunica un estado no utilizable que permite al comparador no emitir veredicto `concordante`, sin lanzar excepción.
- **Pruebas automáticas:**
  - Con un cliente de prueba que responde el cuerpo real de `GET /buscador/status`, el adaptador devuelve `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global` y `errores_por_oferta`, conforme a SUP-006.
  - La URL solicitada es la URL base configurada más `/buscador/status`.
  - Con `ultima_pasada` nula, el adaptador lo comunica de forma distinguible, conforme a ALT-005.
  - Con `error_global` no vacío, el adaptador lo comunica sin lanzar excepción, conforme a ALT-006.
  - Con un error HTTP o un fallo de red, el adaptador devuelve un error controlado, conforme a ALT-005.
  - El cliente solo emite peticiones a `/buscador/status`: no solicita ningún otro endpoint del buscador ni lanza una pasada.
  - El cliente no modifica `source/api/buscador/` ni su contrato, conforme a SUP-004.
- **Prueba manual:**
  1. Con la aplicación arrancada, consultar el adaptador contra `http://localhost:8000` y comprobar que devuelve el mismo `total_listado` que muestra `GET /buscador/status`.

### [ ] TASK-009 Comparador de recuentos y emisión del veredicto

- **Cubre:** REQ-003, REQ-004, REQ-006, NFR-002, SUP-001, SUP-006, DEC-005, ALT-004, ALT-005, ALT-006
- **Componente:** comparador-veredicto | source/api/integridad/comparador.py
- **Módulo:** APP
- **Depende de:** TASK-007, TASK-008
- **Alcance:** Implementar el comparador que recibe el recuento del PDF y el `total_listado` del buscador junto con la tolerancia absoluta, la tolerancia relativa y el umbral de cordura configurados, y emite el veredicto `concordante` o `divergente` aplicando la regla más permisiva de las dos tolerancias (diferencia absoluta o diferencia relativa), y `divergente` siempre que el recuento del PDF quede por debajo del umbral de cordura o el estado del buscador no sea utilizable, con el motivo concreto de cada caso.
- **Hecho cuando:** dos recuentos cuya diferencia no supere la tolerancia absoluta ni la relativa producen `concordante`; una diferencia que supere ambas produce `divergente`; un recuento del PDF por debajo del umbral de cordura produce `divergente` con independencia del `total_listado`; y el resultado del comparador incluye los dos recuentos, la diferencia y los umbrales aplicados.
- **Pruebas automáticas:**
  - Recuento del PDF `92` y `total_listado` `93` con tolerancias `1` y `5` % producen `concordante`, conforme a SUP-001 y NFR-002.
  - Una diferencia de `1` se acepta por la tolerancia absoluta aunque la relativa no se cumpla, conforme a DEC-005.
  - Una diferencia que solo cabe en la tolerancia relativa se acepta, conforme a DEC-005.
  - Una diferencia que no cabe ni en la absoluta ni en la relativa produce `divergente`, conforme a REQ-004.
  - Recuento del PDF `65` con umbral de cordura `70` produce `divergente` aunque la diferencia sea cero, conforme a NFR-002 y ALT-004.
  - Recuento del PDF `70` con umbral de cordura `70` no produce divergencia por umbral, conforme a NFR-002.
  - Un recuento del PDF de `0` produce `divergente` con el motivo del umbral, conforme a ALT-004.
  - Con el buscador no utilizable (error HTTP, `ultima_pasada` nula o `error_global` no vacío) el resultado no es `concordante` y el motivo identifica la causa, conforme a ALT-005 y ALT-006.
  - El resultado del comparador incluye ambos recuentos, la diferencia y los umbrales aplicados, conforme a REQ-005.
  - Con tolerancias y umbral configurados a otros valores, se aplican esos valores y no los de `1`, `5` % y `70`, conforme a NFR-002.
- **Prueba manual:**
  1. Comparar el par `92`/`93` y después el par `65`/`93` y comprobar que el primer caso es `concordante` y el segundo `divergente` por el umbral.

### [ ] TASK-010 Almacén de avisos de fallo y divergencia

- **Cubre:** REQ-007, REQ-008, SUP-007, DEC-001, DEC-002, ALT-003, ALT-006
- **Componente:** avisos-store | source/api/integridad/avisos.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el almacén que registra como aviso consultable, en la entrada de avisos del `.meta.json` del día, cada fallo de descarga, cada fallo de parseo y cada divergencia de recuentos, con la fecha, la comunidad, los recuentos disponibles, el umbral aplicado y el motivo; y que permite consultar los avisos de un rango de fechas. Los avisos son registros internos: no se envía ningún mensaje por Telegram ni por otro canal externo.
- **Hecho cuando:** tras una divergencia, el aviso registrado contiene la fecha, el recuento del PDF, el `total_listado`, la diferencia, el umbral aplicado y el motivo; tras un fallo de descarga o de parseo, el aviso contiene la fecha, la comunidad afectada y el motivo; y la consulta de avisos por rango de fechas devuelve los avisos de ese rango.
- **Pruebas automáticas:**
  - Una divergencia de recuentos genera un aviso con la fecha, el recuento del PDF, el `total_listado`, la diferencia, el umbral aplicado y el motivo, conforme a REQ-007.
  - Un fallo de descarga genera un aviso con la fecha, la comunidad afectada y el motivo, conforme a REQ-007 y ALT-003.
  - Un fallo de parseo genera un aviso con la fecha, la comunidad afectada y el motivo, conforme a REQ-007 y ALT-003.
  - La consulta de avisos por rango de fechas devuelve los avisos de ese rango y excluye los de fuera, conforme a REQ-009.
  - Los avisos quedan asociados al `.meta.json` del día correspondiente, conforme a DEC-001.
  - El almacén no envía ningún mensaje por Telegram ni invoca ningún cliente de notificación externo, conforme a SUP-007.
  - El almacén no crea ni abre ningún fichero SQLite, conforme a DEC-001.
- **Prueba manual:**
  1. Provocar una divergencia y revisar la entrada de avisos del `.meta.json` del día: aparecen fecha, recuentos, diferencia, umbral y motivo.

### [ ] TASK-011 Índice de ejecuciones del último mes

- **Cubre:** REQ-005, REQ-008, REQ-009, NFR-001, NFR-004, DEC-001, ALT-008
- **Componente:** avisos-store | source/api/integridad/ejecuciones.py
- **Módulo:** APP
- **Depende de:** TASK-003
- **Alcance:** Implementar el índice de ejecuciones en un fichero JSON ligero bajo la ruta base de PDFs (por ejemplo `data/pdfs/ejecuciones.json`) que apunta por fecha y comunidad a los `.meta.json` correspondientes: registra cada ejecución con su marca de tiempo, el resultado global, los errores por comunidad y el veredicto agregado, y permite consultar las ejecuciones de los últimos 30 días ordenadas de más reciente a más antigua. No se añade ningún fichero SQLite.
- **Hecho cuando:** tras una ejecución registrada, el índice contiene una entrada con su marca de tiempo, su resultado global, sus errores por comunidad y su veredicto agregado; la consulta de las ejecuciones del último mes devuelve únicamente las de esa ventana y en orden de más reciente a más antigua; y el índice sobrevive a un reinicio de la aplicación porque está en disco.
- **Pruebas automáticas:**
  - Tras registrar una ejecución, el índice contiene una entrada con marca de tiempo, resultado global, errores por comunidad y veredicto agregado, conforme a REQ-008.
  - La consulta de las ejecuciones del último mes devuelve solo las de la ventana de 30 días, conforme a REQ-009.
  - La consulta devuelve las ejecuciones ordenadas de más reciente a más antigua, conforme a REQ-009.
  - Una ejecución con errores parciales registra la comunidad afectada y su mensaje de error, conforme a REQ-008.
  - El índice se escribe de forma atómica (fichero temporal y `rename`) y tras la escritura no queda ningún fichero temporal, conforme a DEC-001.
  - Tras releer el índice desde disco se obtienen las mismas entradas, conforme a DEC-001.
  - Un índice ilegible o corrupto se comunica como tal y no impide que la tarea del día registre una ejecución nueva, conforme al riesgo de metadatos corruptos de `design@3`.
  - El índice no crea ni abre ningún fichero SQLite, conforme a DEC-001.
  - La marca de tiempo de las ejecuciones corresponde a la zona horaria configurada y no a la del sistema, conforme a NFR-004.
- **Prueba manual:**
  1. Registrar dos ejecuciones simuladas y consultar las del último mes: aparecen las dos ordenadas de más reciente a más antigua.

### [ ] TASK-012 Tarea programada diaria de integridad

- **Componente:** integridad-task | source/api/integridad/task.py
- **Módulo:** APP
- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, NFR-002, NFR-003, NFR-004, SUP-001, SUP-003, SUP-004, SUP-005, SUP-007, DEC-001, DEC-002, DEC-004, DEC-005, DEC-006, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008
- **Depende de:** TASK-005, TASK-006, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011
- **Alcance:** Implementar la tarea programada propia que orquesta la comprobación diaria a la hora configurada en la zona horaria configurada, sin modificar el planificador de `api-buscador`: determina el día actual según la zona horaria y, para cada comunidad configurada, consulta el almacén; si ya existe un `.meta.json` válido para esa comunidad y fecha (estado `ok` o `fallido`) no vuelve a descargar ni parsear; si no existe, pide la descarga, la guarda de forma atómica con su hash, pide el parseo, consulta el estado del buscador, calcula el veredicto con el comparador, completa el `.meta.json` con los umbrales aplicados y la marca de tiempo, registra el aviso si el veredicto no es `concordante`, y al finalizar todas las comunidades registra la ejecución global en el índice y lanza la purga.
- **Hecho cuando:** la tarea se dispara a la hora configurada en la zona horaria configurada; con un `.meta.json` previo de la misma comunidad y fecha omite la descarga, el parseo y la comparación; con una descarga fallida deja el día en estado `fallido` sin PDF y con el error registrado; con un parseo fallido conserva el PDF y deja el veredicto `fallido`; con una comparación correcta deja el veredicto y los recuentos en el `.meta.json`; y al terminar registra la ejecución global con sus errores por comunidad.
- **Pruebas automáticas:**
  - Con el reloj controlado, la tarea se dispara una vez al llegar la hora configurada y no se solapa con una ejecución en curso, conforme a NFR-001 y DEC-006.
  - Con un `.meta.json` de hoy en estado `ok`, la tarea omite la descarga, el parseo y la comparación y no genera un segundo veredicto, conforme a ALT-001, REQ-005 y NFR-003.
  - Con un `.meta.json` de hoy en estado `fallido`, la tarea no reintenta ni descarga de nuevo y el veredicto `fallido` permanece, conforme a ALT-002 y NFR-003.
  - Con la descarga en error, el día queda en estado `fallido`, no se conserva PDF y se registra el aviso, conforme a ALT-003, REQ-004 y REQ-007.
  - Con el parseo en error, el PDF se conserva y el `.meta.json` queda con veredicto `fallido` y el error, conforme a DEC-002.
  - Con un PDF del día sin `.meta.json`, la tarea lo trata como huérfano, lo reprocesa y deja el día completo, conforme a ALT-007.
  - Con dos comunidades configuradas, cada una tiene su `.meta.json` y su veredicto, y el veredicto global es el más grave (`fallido` > `divergente` > `concordante`), conforme a ALT-008.
  - La tarea calcula el día actual con la zona horaria configurada y no con la del sistema, conforme a NFR-004.
  - La tarea no lanza ni modifica el comportamiento de `api-buscador`, `api-persistencia` ni `api-historico`, conforme a SUP-004.
  - La tarea no envía ningún aviso por Telegram ni por otro canal externo, conforme a SUP-007.
  - La tarea cancela limpiamente sin dejar ejecuciones en curso.
- **Prueba manual:**
  1. Arrancar la tarea con el reloj controlado a la hora configurada y comprobar que se ejecuta una vez y que una segunda ejecución del mismo día no vuelve a descargar el PDF.

### [ ] TASK-013 Recuperación del día en curso con margen de catch-up

- **Cubre:** REQ-001, REQ-005, NFR-001, NFR-003, DEC-007, ALT-009
- **Componente:** integridad-task | source/api/integridad/task.py
- **Módulo:** APP
- **Depende de:** TASK-012
- **Alcance:** Implementar la lógica de catch-up de la tarea diaria al arrancar, apoyada en el `.meta.json` del día y no en memoria: si ya existe `.meta.json` de hoy (éxito o fallo) no se hace nada; si la hora aún no ha llegado, se espera a la ejecución programada normal; si se arranca dentro de la ventana entre `hora` y `hora + margen` y falta el `.meta.json` de hoy, se programa una única ejecución para `hora + margen` (y si al llegar ese instante sigue sin metadatos, se ejecuta la comprobación del día); si se arranca después de `hora + margen` y falta el `.meta.json` de hoy, se ejecuta inmediatamente; y nunca se procesan días anteriores.
- **Hecho cuando:** el arranque antes de la hora configurada no dispara ninguna ejecución inmediata; el arranque dentro del margen programa una única ejecución para `hora + margen`; el arranque posterior al margen ejecuta de inmediato; y en los tres casos sin `.meta.json` previo se comprueba exactamente una vez el día en curso, sin procesar días anteriores.
- **Pruebas automáticas:**
  - Arranque antes de la hora configurada: no se ejecuta nada de inmediato y queda programada la ejecución normal, conforme a DEC-007.
  - Arranque dentro de la ventana `hora` a `hora + margen` sin `.meta.json`: se programa una única ejecución para `hora + margen`, conforme a DEC-007 y ALT-009.
  - Al llegar a `hora + margen` y seguir sin `.meta.json`, se ejecuta la comprobación del día, conforme a DEC-007.
  - Arranque después de `hora + margen` sin `.meta.json`: la comprobación del día se ejecuta de inmediato, conforme a DEC-007.
  - Arranque con `.meta.json` de hoy existente, en estado `ok` o `fallido`: no se ejecuta nada, conforme a ALT-009 y ALT-002.
  - Con el margen configurado a `0`, un arranque posterior a la hora ejecuta de inmediato, conforme a DEC-007.
  - La recuperación nunca procesa días anteriores: con directorios de días pasados y sin `.meta.json` de hoy, esos días no se tocan, conforme a DEC-007.
  - La idempotencia se apoya en el `.meta.json` del día y no en memoria: tras reiniciar la aplicación, un día ya procesado no se vuelve a procesar, conforme a DEC-007 y ALT-009.
  - La ejecución programada dentro del margen no se duplica con la ejecución normal de la misma hora configurada, conforme a ALT-009.
- **Prueba manual:**
  1. Arrancar la aplicación dentro de la ventana de margen y comprobar que no se ejecuta de inmediato y que a `hora + margen` se ejecuta una sola vez.

### [ ] TASK-014 Arranque y apagado de la integridad en la aplicación

- **Cubre:** REQ-001, REQ-006, NFR-001, NFR-004, SUP-002, SUP-003, DEC-001, DEC-006, ALT-009
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-012, TASK-013
- **Alcance:** Integrar en el ciclo de vida de la aplicación FastAPI existente (`source/api/main.py`, con su `lifespan` y su `app_state`) la carga de la configuración de la integridad, la instanciación del almacén, los adaptadores, el comparador, el almacén de avisos y el índice de ejecuciones, el registro del router de consulta y el arranque de la tarea diaria propia, de modo que convivan en el mismo proceso el planificador de `api-buscador`, la `ingestion-task` y la `purge-task` de `api-persistencia`, la `historico-task` y la nueva `integridad-task`, sin modificar ninguno de esos módulos; y ordenar el apagado de modo que la tarea de la integridad se cancele antes de detener el planificador del buscador y antes de cerrar cualquier recurso compartido.
- **Hecho cuando:** al arrancar la aplicación, la tarea diaria de la integridad queda activa junto al planificador del buscador, la ingesta, la purga y la tarea del histórico; si la configuración de la integridad falla, el error se registra y el resto de la API sigue arrancando sin la feature; al apagar, la tarea de la integridad queda cancelada sin dejar ejecuciones en curso; y los endpoints existentes de `api-buscador`, `api-persistencia` y `api-historico` siguen respondiendo igual.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, están activas la tarea de la integridad, la ingesta, la purga, la tarea del histórico y el planificador del buscador, conforme a DEC-006.
  - Con una configuración de la integridad ausente o malformada, el arranque registra el error y la aplicación sigue disponible sin la feature, sin abortar el arranque de las demás.
  - Al apagar la aplicación, la tarea de la integridad queda cancelada y no se inician nuevas ejecuciones.
  - Al apagar, la cancelación de la tarea de la integridad ocurre antes de la detención del planificador del buscador.
  - Los endpoints de `api-buscador`, `api-persistencia` y `api-historico` siguen respondiendo igual después de integrar la integridad.
  - La integración no modifica `source/api/buscador/`, `source/api/persistencia/`, `source/api/historico/` ni `source/api/parser.py`, conforme a SUP-002.
  - La integración no crea ni abre ningún fichero SQLite propio de la integridad, conforme a DEC-001.
  - El arranque no altera el contenido ni la marca de modificación de `data/job_emcan.db`, conforme a SUP-003.
- **Prueba manual:**
  1. Arrancar la aplicación y comprobar que la tarea de la integridad queda programada junto a las demás tareas del proceso.
  2. Detener la aplicación y comprobar que no queda viva ninguna tarea de la integridad.

### [ ] TASK-015 Endpoint del último veredicto de integridad

- **Cubre:** REQ-006, REQ-009, SUP-002, SUP-006, DEC-001, DEC-005, ALT-008
- **Componente:** integridad-api | source/api/integridad/routes.py
- **Módulo:** APP
- **Depende de:** TASK-009, TASK-011
- **Alcance:** Implementar el endpoint de consulta del último veredicto de integridad, que lee el `.meta.json` más reciente y devuelve el veredicto global junto con el desglose por comunidad (fecha, comunidad, recuento del PDF, recuento del buscador, diferencia, umbrales y resultado) e indica si los cierres del día están recomendados. El veredicto es informativo: el endpoint no bloquea ni modifica los cierres de `api-historico`. Los endpoints no exigen autenticación, como el resto de la API.
- **Hecho cuando:** con un veredicto almacenado, el endpoint devuelve el más reciente con su fecha, comunidad, recuentos, diferencia y resultado; con un veredicto `divergente` o `fallido` de hoy, la respuesta indica que no se recomienda cerrar ofertas; sin veredicto de hoy, la respuesta indica igualmente que no se recomienda cerrar ofertas; y con un veredicto `concordante` de hoy, la respuesta indica que cerrar ofertas es recomendable.
- **Pruebas automáticas:**
  - Con al menos un veredicto almacenado, la respuesta devuelve el más reciente con fecha, comunidad, recuentos, diferencia y resultado, conforme a REQ-009.
  - Con un veredicto `divergente` de hoy, la respuesta indica que no es recomendable cerrar ofertas, conforme a REQ-006.
  - Con un veredicto `fallido` de hoy, la respuesta indica que no es recomendable cerrar ofertas, conforme a REQ-006.
  - Sin veredicto de hoy, la respuesta indica que no es recomendable cerrar ofertas, conforme a REQ-006.
  - Con un veredicto `concordante` de hoy, la respuesta indica que es recomendable cerrar ofertas, conforme a REQ-006.
  - Con varias comunidades, la respuesta incluye el veredicto global y el desglose por comunidad, conforme a ALT-008.
  - Un `.meta.json` ilegible se omite de la respuesta sin producir error, conforme al riesgo de metadatos corruptos de `design@3`.
  - El endpoint no escribe en ningún sitio y no modifica `data/job_emcan.db`, conforme a SUP-002.
  - El endpoint no exige cabeceras de autenticación ni devuelve 401 o 403.
- **Prueba manual:**
  1. Consultar el endpoint con un día `divergente` y con un día `concordante` y comprobar que la recomendación de cierre cambia en consecuencia.

### [ ] TASK-016 Endpoint de las ejecuciones del último mes

- **Cubre:** REQ-008, REQ-009, SUP-002, SUP-007, DEC-001
- **Componente:** integridad-api | source/api/integridad/routes.py
- **Módulo:** APP
- **Depende de:** TASK-011
- **Alcance:** Implementar el endpoint de consulta de las ejecuciones del último mes, que lee el índice de ejecuciones y devuelve las ejecuciones de la ventana de 30 días con su marca de tiempo, su resultado global, sus errores por comunidad y su veredicto agregado, incluyendo los avisos registrados en esas ejecuciones.
- **Hecho cuando:** con ejecuciones en los últimos 30 días, el endpoint las devuelve con su marca de tiempo y su resultado; con ejecuciones más antiguas, no las devuelve; y una ejecución con errores parciales expone la comunidad afectada y su mensaje.
- **Pruebas automáticas:**
  - La consulta devuelve las ejecuciones de los últimos 30 días con su marca de tiempo y su resultado, conforme a REQ-009.
  - Una ejecución con errores parciales devuelve la comunidad afectada y el mensaje de error, conforme a REQ-008.
  - Las ejecuciones con más de 30 días no aparecen en la respuesta, conforme a REQ-009.
  - Las ejecuciones se devuelven ordenadas de más reciente a más antigua, conforme a REQ-009.
  - Los avisos registrados en las ejecuciones son consultables a través de la respuesta, conforme a REQ-007.
  - Un índice de ejecuciones ilegible o ausente devuelve una lista vacía sin error, conforme al riesgo de metadatos corruptos de `design@3`.
  - El endpoint no escribe en ningún sitio y no modifica `data/job_emcan.db`, conforme a SUP-002.
  - El endpoint no envía ni expone integraciones con canales de notificación externos, conforme a SUP-007.
- **Prueba manual:**
  1. Consultar el endpoint con un índice de ejecuciones de prueba y comprobar que devuelve solo las ejecuciones del último mes con sus avisos.

### [ ] TASK-017 Endpoint de los PDFs conservados

- **Cubre:** REQ-002, REQ-009, SUP-003, DEC-001, DEC-004
- **Componente:** integridad-api | source/api/integridad/routes.py
- **Módulo:** APP
- **Depende de:** TASK-004
- **Alcance:** Implementar el endpoint de consulta de los PDFs conservados, que lista los ficheros `data/pdfs/<comunidad>/<aaaa-mm-dd>.pdf` y devuelve por cada uno su fecha, su comunidad y su ruta identificable, junto con la información disponible de sus metadatos (hash, recuento y veredicto cuando el `.meta.json` existe).
- **Hecho cuando:** con PDFs conservados, el endpoint los devuelve con su fecha, su comunidad y su ruta identificable; los PDF sin `.meta.json` aparecen igualmente listados; y el listado refleja lo que queda tras la purga.
- **Pruebas automáticas:**
  - La consulta devuelve un elemento por cada PDF conservado con su fecha, su comunidad y su ruta identificable, conforme a REQ-009.
  - Cada elemento incluye el hash, el recuento y el veredicto cuando existe su `.meta.json`, conforme a REQ-005.
  - Un PDF sin `.meta.json` aparece en el listado sin datos de metadatos y sin producir error, conforme a ALT-007.
  - Un `.meta.json` ilegible se omite del listado de metadatos sin impedir listar los PDFs, conforme al riesgo de metadatos corruptos de `design@3`.
  - Sin directorio de PDFs la respuesta es una lista vacía sin error, conforme a REQ-009.
  - La respuesta no incluye PDFs cuya fecha supere la ventana de retención tras la purga, conforme a REQ-002 y DEC-004.
  - El endpoint no escribe ni borra ningún fichero y no modifica `data/job_emcan.db`, conforme a SUP-003.
  - El endpoint no exige cabeceras de autenticación ni devuelve 401 o 403.
- **Prueba manual:**
  1. Consultar el endpoint con varios PDFs conservados y comprobar que fecha, comunidad y ruta son correctos en cada elemento.

### [ ] TASK-018 Verificación de integración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, NFR-001, NFR-002, NFR-003, NFR-004, SUP-001, SUP-003, SUP-004, SUP-005, SUP-007, DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, ALT-001, ALT-002, ALT-003, ALT-004, ALT-005, ALT-006, ALT-007, ALT-008, ALT-009
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-014, TASK-015, TASK-016, TASK-017
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, la configuración, el almacén, los tres adaptadores, el comparador, el almacén de avisos, el índice de ejecuciones, la tarea diaria y los endpoints, montando la aplicación con `GET /buscador/status` simulado, un descargador y un parser del PDF simulados y un directorio temporal de PDFs, y cubriendo los casos de concordancia, divergencia por tolerancia, divergencia por umbral, fallo de descarga, fallo de parseo, buscador sin datos, doble ejecución diaria, arranque dentro del margen de catch-up y purga por antigüedad.
- **Hecho cuando:** con una pasada simulada válida y recuentos concordantes, el día queda con veredicto `concordante` y los tres endpoints devuelven el veredicto, las ejecuciones y los PDFs esperados; con una divergencia o un fallo, el día queda `divergente` o `fallido`, existe el aviso correspondiente y la recomendación de cierre es negativa; y la segunda ejecución del mismo día no vuelve a descargar ni a generar un segundo veredicto, sin excepciones no controladas.
- **Pruebas automáticas:**
  - Con recuentos `92` y `93`, el día queda `concordante` y el endpoint del último veredicto indica que es recomendable cerrar ofertas, conforme a REQ-004 y REQ-006.
  - Con recuentos `92` y `80`, el día queda `divergente`, existe el aviso con los recuentos, la diferencia, el umbral y el motivo, y el endpoint indica que no es recomendable cerrar ofertas, conforme a REQ-003, REQ-007 y REQ-006.
  - Con un recuento del PDF de `65`, el día queda `divergente` por umbral aunque los recuentos coincidan, conforme a NFR-002 y ALT-004.
  - Con la descarga en error, el día queda `fallido`, no hay PDF conservado para esa fecha y existe el aviso con la comunidad y el motivo, conforme a ALT-003 y REQ-007.
  - Con el parseo en error, el PDF se conserva, el día queda `fallido` y existe el aviso, conforme a DEC-002.
  - Con el buscador sin `ultima_pasada` o con `error_global`, el día queda `divergente` con el motivo correspondiente y no `concordante`, conforme a ALT-005, ALT-006 y REQ-003.
  - Con una segunda ejecución el mismo día, no se vuelve a descargar el PDF ni se genera un segundo veredicto para la comunidad y la fecha, conforme a ALT-001, REQ-005 y NFR-003.
  - Con un día fallido previo, no se reintenta ese día, conforme a ALT-002.
  - Con un arranque dentro de la ventana de margen, se programa una única ejecución para `hora + margen` y el día se comprueba una sola vez, conforme a ALT-009 y DEC-007.
  - Tras la purga, el endpoint de PDFs no devuelve los ficheros con más de la ventana de retención y sí los del día en curso, conforme a REQ-002 y DEC-004.
  - El endpoint de ejecuciones devuelve las ejecuciones del último mes con sus avisos, conforme a REQ-008 y REQ-009.
  - El directorio de datos de la prueba contiene los `.meta.json` y los PDFs esperados y ningún fichero SQLite nuevo, conforme a DEC-001.
  - La base de datos de `api-persistencia` conserva su contenido y su marca de modificación tras toda la integración, conforme a SUP-003.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio de datos tras la prueba: aparecen los PDFs y los `.meta.json` esperados, sin ficheros SQLite nuevos.

### [ ] TASK-019 Contrato: openapi - endpoints de consulta de la integridad

- **Cubre:** REQ-006, REQ-009, SUP-002, SUP-007, DEC-001, DEC-005
- **Componente:** integridad-api | source/api/integridad/routes.py
- **Módulo:** APP
- **Depende de:** TASK-015, TASK-016, TASK-017, TASK-018
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-integridad.yaml` que formaliza los endpoints de consulta del último veredicto, de las ejecuciones del último mes y de los PDFs conservados tal como quedaron implementados, con sus esquemas de entrada y salida (fecha, comunidad, recuentos, diferencia, umbrales, veredicto y recomendación de cierre) y sus respuestas de error.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-integridad.yaml`, describe las tres operaciones con sus esquemas y sus respuestas 200, y coincide con la implementación verificada en TASK-018.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las tres operaciones con sus respuestas 200.
  - El esquema del veredicto incluye fecha, comunidad, recuento del PDF, recuento del buscador, diferencia, umbrales y veredicto, conforme a REQ-009.
  - El esquema de las ejecuciones incluye marca de tiempo, resultado global, errores por comunidad y veredicto agregado, conforme a REQ-008.
  - El esquema de los PDFs incluye fecha, comunidad y ruta identificable, conforme a REQ-009.
  - El contrato documenta que el veredicto es informativo y que no bloquea los cierres de `api-historico`, conforme a REQ-006.
  - Las rutas y los campos del contrato coinciden con los que devuelve la implementación en la prueba de integración.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las tres interfaces de la fila de contratos afectados.
  2. Comparar el contrato con las respuestas JSON reales obtenidas en TASK-018 y confirmar que no hay campos divergentes.

### [ ] TASK-020 Contrato: configuración - fichero de configuración de la integridad

- **Cubre:** REQ-001, REQ-002, REQ-003, NFR-001, NFR-002, NFR-004, SUP-001, SUP-003, DEC-005, DEC-007
- **Componente:** config-integridad | config/integridad.yaml
- **Módulo:** APP
- **Depende de:** TASK-002, TASK-014
- **Alcance:** Formalizar el contrato de configuración de la integridad: documentar el formato exacto del fichero `config/integridad.yaml` (zona horaria, hora de ejecución, margen de catch-up en minutos, días de retención, tolerancia absoluta, tolerancia relativa, umbral de cordura, ruta base de PDFs, URL base del buscador y comunidades) y sus valores por defecto, dejándolo alineado con lo que la carga de TASK-002 interpreta y con lo que la aplicación aplica en TASK-014.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga y se aplica sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/integridad.yaml` se carga con el formato documentado y devuelve la zona horaria, la hora, el margen de catch-up, los días de retención, las dos tolerancias, el umbral de cordura, la ruta base y las comunidades.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Una configuración con un tipo incorrecto, con una hora fuera de rango o con una zona horaria inválida se rechaza con un error controlado, conforme a NFR-001 y NFR-004.
  - Un margen de catch-up negativo se rechaza con un error controlado, conforme a DEC-007.
  - Los valores por defecto documentados (zona `Europe/Madrid`, hora `2`, margen `60`, retención `30`, tolerancia absoluta `1`, tolerancia relativa `5`, umbral `70` y ruta base `data/pdfs`) coinciden con los que aplica la implementación.
  - El contrato documenta que los PDFs se guardan en `<ruta_base>/<comunidad>/<aaaa-mm-dd>.pdf` con su `<aaaa-mm-dd>.meta.json` asociado, conforme a SUP-003.
  - El contrato no documenta ninguna ruta de servidor de base de datos ni credenciales.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración de la integridad) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la aplicación arranca con la nueva configuración.

### [ ] TASK-021 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007
- **Componente:** api-service | source/api
- **Módulo:** APP
- **Depende de:** TASK-018, TASK-019, TASK-020
- **Alcance:** Actualizar `.sdd/architecture.md` en tres puntos y solo en esos tres: (a) la línea del módulo `API`, cuya responsabilidad pasa a incluir también la integridad y la comprobación de recuentos con el PDF de difusión; (b) añadir a la sección de contratos la entrada `openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad`; y (c) añadir a la sección de contratos la entrada `configuracion | config/integridad.yaml | api-integridad -> config-integridad`. El mapa **no** gana entradas de módulo para los componentes internos de la integridad, que son detalle de implementación dentro del módulo `API` y no reciben identificador propio en el mapa.
- **Hecho cuando:** la línea del módulo `API` de `.sdd/architecture.md` menciona la integridad en su responsabilidad; la sección de contratos contiene las dos entradas nuevas (`openapi` de la integridad y `configuracion` de `config/integridad.yaml`); y la sección de módulos no contiene ninguna entrada nueva para los componentes internos de la integridad.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que la línea del módulo `API` incluye la integridad en su descripción de responsabilidad.
  - Una comprobación confirma que la sección de contratos incluye la entrada `openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad`.
  - Una comprobación confirma que la sección de contratos incluye la entrada `configuracion | config/integridad.yaml | api-integridad -> config-integridad`.
  - Una comprobación confirma que la sección de módulos no ha ganado entradas para los componentes internos de la integridad (almacén, adaptadores, comparador, avisos, índice, purga, tarea programada y endpoints) ni para el subpaquete `source/api/integridad`.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que la línea del módulo `API` incluye la integridad en su responsabilidad y que la sección de contratos contiene las dos entradas nuevas.
  2. Revisar la sección de módulos del mapa y comprobar que no se ha añadido ninguna entrada para los componentes internos de la integridad.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-001, TASK-002, TASK-006, TASK-012, TASK-013, TASK-014, TASK-020 |
| REQ-002 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-012, TASK-017, TASK-018, TASK-020 |
| REQ-003 | TASK-002, TASK-007, TASK-008, TASK-009, TASK-012, TASK-018, TASK-020 |
| REQ-004 | TASK-007, TASK-009, TASK-012, TASK-018 |
| REQ-005 | TASK-003, TASK-004, TASK-009, TASK-010, TASK-011, TASK-012, TASK-013, TASK-017, TASK-018 |
| REQ-006 | TASK-008, TASK-009, TASK-012, TASK-014, TASK-015, TASK-018, TASK-019 |
| REQ-007 | TASK-010, TASK-012, TASK-016, TASK-018, TASK-019 |
| REQ-008 | TASK-010, TASK-011, TASK-012, TASK-016, TASK-018, TASK-019 |
| REQ-009 | TASK-004, TASK-011, TASK-012, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-002, TASK-012, TASK-013, TASK-014, TASK-018, TASK-020 |
| NFR-002 | TASK-002, TASK-009, TASK-018, TASK-020 |
| NFR-003 | TASK-003, TASK-012, TASK-013, TASK-018 |
| NFR-004 | TASK-002, TASK-011, TASK-012, TASK-014, TASK-018, TASK-020 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-010, TASK-011, TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-020, TASK-021 |
| DEC-002 | TASK-003, TASK-005, TASK-006, TASK-007, TASK-010, TASK-012, TASK-018, TASK-021 |
| DEC-003 | TASK-001, TASK-003, TASK-018, TASK-021 |
| DEC-004 | TASK-005, TASK-012, TASK-017, TASK-018, TASK-021 |
| DEC-005 | TASK-002, TASK-008, TASK-009, TASK-012, TASK-015, TASK-018, TASK-019, TASK-020, TASK-021 |
| DEC-006 | TASK-012, TASK-014, TASK-018, TASK-021 |
| DEC-007 | TASK-002, TASK-013, TASK-018, TASK-020, TASK-021 |

| Supuesto | Tareas |
|---|---|
| SUP-001 | TASK-002, TASK-003, TASK-009, TASK-012, TASK-018, TASK-020 |
| SUP-002 | TASK-014, TASK-015, TASK-016, TASK-018, TASK-019 |
| SUP-003 | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-012, TASK-014, TASK-017, TASK-018, TASK-020 |
| SUP-004 | TASK-008, TASK-012, TASK-018 |
| SUP-005 | TASK-001, TASK-006, TASK-007, TASK-012, TASK-018 |
| SUP-006 | TASK-008, TASK-009, TASK-015, TASK-018 |
| SUP-007 | TASK-010, TASK-012, TASK-016, TASK-018, TASK-019 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-012, TASK-018 |
| ALT-002 | TASK-012, TASK-013, TASK-018 |
| ALT-003 | TASK-003, TASK-006, TASK-010, TASK-012, TASK-018 |
| ALT-004 | TASK-007, TASK-009, TASK-012, TASK-018 |
| ALT-005 | TASK-008, TASK-009, TASK-012, TASK-018 |
| ALT-006 | TASK-008, TASK-009, TASK-010, TASK-012, TASK-018 |
| ALT-007 | TASK-003, TASK-004, TASK-012, TASK-017, TASK-018 |
| ALT-008 | TASK-009, TASK-011, TASK-012, TASK-015, TASK-018 |
| ALT-009 | TASK-013, TASK-014, TASK-018 |

## Avisos

- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-019 depende de TASK-015, TASK-016, TASK-017 y TASK-018, y TASK-020 depende de TASK-002 y TASK-014.
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
- Los componentes de la integridad (`integridad-task`, `config-integridad`, `pdf-store`, `downloader-adapter`, `parser-adapter`, `buscador-status-adapter`, `comparador-veredicto`, `pdf-purger`, `avisos-store` e `integridad-api`) son **detalle de implementación interno del módulo `API`**: no reciben identificador propio en `.sdd/architecture.md` y no se proponen como módulos nuevos del mapa, conforme a `design@3`. Las tareas que los implementan los citan en su línea `Componente` (con la ruta interna dentro de `source/api/integridad/`) y llevan su línea `Módulo` con el identificador `APP`, que es la etiqueta del trabajo; el código permanece en `source/api/integridad/`.
- TASK-021 no registra módulos nuevos de la integridad. Su alcance se limita a actualizar la línea del módulo `API` de `.sdd/architecture.md` para que su responsabilidad incluya la integridad, a añadir las dos entradas de contrato (`openapi | docs/contracts/openapi/api-integridad.yaml | cliente -> api-integridad` y `configuracion | config/integridad.yaml | api-integridad -> config-integridad`) y a comprobar que el mapa no gana entradas de módulo para los componentes internos de la integridad.
- `api-buscador`, `api-persistencia`, `api-pdf-parser` y `api-historico` no se modifican en ninguna tarea. La compatibilidad se resuelve solo desde `api-integridad`: lectura del contrato `GET /buscador/status` (TASK-008), invocación en proceso de `source/api/downloader.py` y `source/api/parser.py` (TASK-006 y TASK-007) y convivencia de tareas programadas en el mismo proceso FastAPI (TASK-014), conforme a SUP-002, SUP-004, SUP-005 y DEC-006.
- La fila "HTTP/OpenAPI / `docs/contracts/openapi/api-buscador.yaml` (existente)" de "Contratos afectados" declara que el contrato no se modifica: ninguna tarea toca `api-buscador` ni su contrato; TASK-008 documenta el consumo del contrato tal como está publicado. La fila "Llamada interna / Uso de `source/api/downloader.py`, `source/api/parser.py` y `source/api/assembler.py` (existentes)" se cubre con TASK-006 y TASK-007, que fijan el contrato de uso en proceso como dependencia interna y no generan fichero de contrato nuevo. Solo las dos filas de contratos nuevos (OpenAPI de la integridad y `config/integridad.yaml`) generan tareas de contrato: TASK-019 y TASK-020.
- La hora por defecto se fija en `2` (02:00) porque `config/buscador.yaml` programa la pasada del buscador a la `1` (01:00) y `config/historico.yaml` usa ya las 02:00; el valor por defecto de 60 minutos para `margen_catchup` deja margen a que termine la pasada del buscador antes de leer su `total_listado`. Ambos valores son configurables sin cambios de código, conforme a NFR-001 y DEC-007.
- La idempotencia y la recuperación por catch-up se apoyan en la existencia del `.meta.json` del día, no en memoria: TASK-012 comprueba el `.meta.json` antes de descargar o parsear y TASK-013 decide el comportamiento de arranque con el mismo fichero, de modo que un reinicio de la aplicación no rompe la frecuencia máxima diaria, conforme a NFR-003 y DEC-007.
- El diseño no fija el nombre concreto del fichero del índice de ejecuciones (`data/pdfs/ejecuciones.json` o similar) ni el prefijo de las rutas de los endpoints. TASK-011 y TASK-015..TASK-017 adoptan por defecto `data/pdfs/ejecuciones.json` y el prefijo `/integridad`; si la capa técnica adopta otro, el cambio queda limitado a TASK-011, TASK-015, TASK-016, TASK-017, TASK-018 y TASK-019.
- El diseño no fija la granularidad de los avisos dentro del `.meta.json` (una entrada por aviso o una lista por día). TASK-010 los registra como entradas consultables asociadas al día, con fecha, comunidad, recuentos, umbral y motivo, conforme a REQ-007.
- La escritura del PDF y la del `.meta.json` son atómicas en TASK-003 (fichero temporal en el mismo directorio y `rename` al nombre definitivo) y en TASK-011 para el índice de ejecuciones; las pruebas de TASK-003 verifican que no queda ningún fichero temporal ni un PDF con nombre definitivo incompleto.
- El diseño no fija el mecanismo concreto del planificador en proceso (biblioteca o temporizador propio). TASK-012 y TASK-014 se limitan al comportamiento exigible: ejecución diaria a la hora configurada, una sola vez por día, catch-up con margen, cancelación limpia al apagar y convivencia con el planificador de `api-buscador`, la `ingestion-task`, la `purge-task` y la `historico-task` en el mismo proceso FastAPI sin modificarlos.
- `api-historico` y `api-integridad` quedan programados por defecto a la misma hora (02:00) y pueden ejecutarse concurrentemente. Hoy el veredicto es informativo y `api-historico` no lo consume, por lo que la concurrencia no afecta a la corrección, conforme al aviso de `design@3`.
- El documento contiene 21 tareas (TASK-001..TASK-021); la numeración es continua y no hay huecos. El apartado "Orden de implementación" los agrupa en 10 pasos numerados, cada uno con las tareas que encadenan.
