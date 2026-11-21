# Tareas: api-buscador

Estado: aprobado
Revisión: 2
Basado en: requirements@5, design@2
Verificación: correcta

## Resumen

El trabajo se divide en veintitrés tareas que siguen la cadena de dependencias del diseño: primero la estructura del paquete, los modelos de dominio y la configuración; luego los componentes independientes entre sí (fichero de estado, limitador de peticiones, incorporación de las muestras HTML del contrato); a continuación el recorrido del listado y el parseo de ficha contra la estructura real del portal, el archivo de HTML y la purga; después el ensamblado de la respuesta, el coordinador de pasada, el planificador y los dos endpoints; y por último la verificación de integración, las tres tareas de contrato y la actualización del mapa de arquitectura. Cada tarea de implementación incluye sus propias pruebas; solo la verificación de extremo a extremo se separa como tarea de integración.

Los tests no usan muestras inventadas: parten de las muestras reales del contrato HTML de `docs/contracts/html/empleacantabria/`, que el diseño fija como contrato de referencia del listado y de la ficha.

## Orden de implementación

1. TASK-001 Estructura del paquete y dependencias → TASK-002 Modelos de dominio.
2. TASK-003 Configuración del buscador.
3. En paralelo: TASK-004 Fichero de códigos vistos, TASK-005 Limitador de peticiones, TASK-006 Muestras del contrato.
4. TASK-007 Recorrido del listado → TASK-008 Parseo de la ficha.
5. TASK-009 Archivo de HTML fallidos → TASK-010 Purga de HTML caducados.
6. TASK-011 Ensamblado de la respuesta → TASK-012 Coordinador de pasada.
7. TASK-013 Planificador diario → TASK-014 Endpoint de pasada manual → TASK-015 Endpoint de estado.
8. TASK-016 Arranque y apagado de la API.
9. TASK-017 Verificación de integración.
10. TASK-018..TASK-020 Contratos (implementation-first).
11. TASK-021 Variantes derivadas de las muestras, TASK-022 Pruebas de frecuencia y solapamiento, TASK-023 Actualización del mapa.

## Tareas

### [x] TASK-001 Estructura del paquete del buscador y dependencias

- **Cubre:** DEC-001, DEC-004
- **Componente:** api-service | source/api/buscador
- **Módulo:** API
- **Depende de:** -
- **Alcance:** Crear el subpaquete `source/api/buscador/` con su `__init__.py` y declarar en `pyproject.toml` las dependencias que exige el diseño (`selectolax` para el parseo HTML y el mecanismo de planificación en proceso), de modo que los componentes nuevos sean importables y la suite de pruebas los recorra sin fallos de colección.
- **Hecho cuando:** el subpaquete `source/api/buscador` se importa sin errores, las dependencias declaradas cubren las que usa el diseño (parseo HTML con `selectolax` y planificación en proceso) y el runner de pruebas recorre `tests/` sin fallos de colección.
- **Pruebas automáticas:**
  - La suite arranca sin errores de importación de `source.api.buscador` ni de ninguna dependencia declarada.
  - Una comprobación confirma que el lector de HTML con `selectolax` y el planificador en proceso están disponibles en el entorno de pruebas.
  - El paquete `source/api/buscador` no importa ni referencia un motor de base de datos (SQLite, SQLAlchemy ni similar), conforme a DEC-002.
- **Prueba manual:**
  1. Instalar el proyecto en un entorno virtual limpio y ejecutar la suite de pruebas: termina sin fallos por dependencias ausentes.

### [x] TASK-002 Modelos de dominio del rastreador

- **Cubre:** REQ-008, REQ-013, SUP-003, SUP-006, DEC-009
- **Componente:** response-assembler | source/api/buscador/models.py
- **Módulo:** response-assembler
- **Depende de:** TASK-001
- **Alcance:** Definir las entidades lógicas `ConfigBuscador`, `OfertaBuscador`, `CodigoVisto`, `HtmlFallido` y `ResultadoPasada` con los campos que exige el modelo de datos lógico del diseño, sin ninguna dependencia de base de datos ni de persistencia más allá del fichero JSON de códigos vistos.
- **Hecho cuando:** existen las cinco entidades con los campos de `OfertaBuscador` que la ficha publica (número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto) más la comunidad de la propia feature, y con `sector`, `nivel` y `contrato` presentes en el modelo pero siempre vacíos, conforme a DEC-009 y SUP-006; y `ResultadoPasada` tiene timestamp, comunidad, total de ofertas del listado, errores globales, errores por oferta y ofertas nuevas.
- **Pruebas automáticas:**
  - Se instancia una `OfertaBuscador` con todos los campos publicados y se comprueba que conserva los valores originales.
  - Se instancia una `OfertaBuscador` con `sector`, `nivel` y `contrato` sin rellenar y se comprueba que esos tres campos quedan vacíos y que no se ha inferido ningún valor a partir de otros campos.
  - Se instancia una `OfertaBuscador` sin contacto y se comprueba que ese campo queda vacío, sin inventar valor y sin que aparezca ningún campo de empresa o de persistencia en la entidad.
  - `ResultadoPasada` puede construirse con lista de errores vacía y con un error global más un error por oferta.
  - La comunidad está presente en `OfertaBuscador` con el valor por defecto Cantabria, conforme a SUP-003, y la provincia es el dato publicado por la ficha, no una copia de la comunidad.
- **Prueba manual:**
  1. Revisar las entidades y comprobar que cubren exactamente el modelo de datos lógico del diseño, con `sector`, `nivel` y `contrato` como campos reservados y vacíos, y sin campos de persistencia en base de datos.

### [x] TASK-003 Fichero de configuración del buscador y validación de la hora

- **Cubre:** REQ-001, NFR-001, NFR-004, SUP-001, ALT-005
- **Componente:** config-buscador | config/buscador.yaml + source/api/buscador/config.py
- **Módulo:** config-buscador
- **Depende de:** TASK-001, TASK-002
- **Alcance:** Crear el fichero de configuración `config/buscador.yaml` con la URL del listado, la URL de la ficha, la hora de pasada por defecto (01:00), el User-Agent identificable, el delay entre peticiones, el tamaño de página (75) y las rutas de `seen_codes.json` y `failed_htmls/`, e implementar su carga con validación de la hora como entero único entre 0 y 23.
- **Hecho cuando:** la carga devuelve la configuración completa con la hora por defecto 01:00 cuando no se indica otra, el tamaño de página es 75 y el User-Agent incluye el nombre del proyecto y una referencia de contacto; un valor de hora que no sea un entero único entre 0 y 23 se rechaza con un error controlado que identifica la causa.
- **Pruebas automáticas:**
  - La carga del fichero `config/buscador.yaml` devuelve hora, URLs, User-Agent, delay, tamaño de página y rutas de datos.
  - Sin fichero de configuración, la hora por defecto es 1 (01:00), el tamaño de página es 75 y el delay es 10 segundos.
  - Una hora con valor 0 se acepta y una hora con valor 23 se acepta.
  - Una hora con valor 24 o con valor negativo se rechaza con un error controlado.
  - Una lista de horas, un valor con minutos, una fracción de hora y una expresión cron se rechazan todos con un error controlado, sin dejar la configuración en un estado inválido.
  - El User-Agent cargado contiene el nombre del proyecto y una URL o correo de contacto, conforme a NFR-001.
  - Un fichero ausente o malformado produce un error controlado que identifica la configuración como origen, en lugar de una excepción no controlada.
- **Prueba manual:**
  1. Abrir `config/buscador.yaml` y comprobar que contiene la URL del listado, la URL de la ficha, la hora, el User-Agent, el delay, el tamaño de página y las rutas de datos.
  2. Cambiar la hora a 23, recargar la configuración y comprobar que la nueva hora es la que se muestra y que el tamaño de página sigue siendo 75.

### [x] TASK-004 Fichero local de códigos vistos

- **Cubre:** REQ-004, REQ-005, SUP-004, DEC-002
- **Componente:** state-store | source/api/buscador/state.py
- **Módulo:** state-store
- **Depende de:** TASK-002
- **Alcance:** Implementar la lectura y escritura de `data/seen_codes.json` como único estado persistente de la feature: carga del conjunto de códigos al arrancar, creación del fichero vacío cuando no existe y persistencia de los códigos nuevos unidos a los ya registrados, sin tocar SQLite ni `api-persistencia`.
- **Hecho cuando:** el fichero se lee al arrancar devolviendo el conjunto de códigos registrados, si no existe se crea vacío y se considera que no hay códigos previos, y la escritura añade los códigos nuevos conservando los anteriores.
- **Pruebas automáticas:**
  - Con un fichero que contiene tres códigos, la carga devuelve esos tres códigos.
  - Con un fichero inexistente, la carga devuelve el conjunto vacío y deja creado el fichero vacío.
  - Tras guardar un código nuevo, el fichero contiene los códigos anteriores más el nuevo y la recarga devuelve los cuatro.
  - Guardar un código ya presente no lo duplica en el fichero.
  - Un fichero con contenido JSON inválido produce un error controlado que identifica el fichero, en lugar de una excepción no controlada.
  - El módulo no abre ni escribe ninguna base de datos.
- **Prueba manual:**
  1. Arrancar sin `data/seen_codes.json` y comprobar que el fichero aparece vacío tras el arranque.
  2. Añadir un código a mano, reiniciar y comprobar que la carga lo reconoce.

### [x] TASK-005 Limitador global de peticiones al portal

- **Cubre:** NFR-001, NFR-002, DEC-003
- **Componente:** rate-limiter | source/api/buscador/rate_limiter.py
- **Módulo:** rate-limiter
- **Depende de:** TASK-003
- **Alcance:** Implementar un único componente que regula todas las peticiones salientes al portal, compartidas entre listado, fichas y reintentos, garantizando al menos 10 segundos entre peticiones consecutivas y aplicando el User-Agent identificable de la configuración.
- **Hecho cuando:** toda petición que pasa por el limitador espera lo que quede del intervalo mínimo desde la petición anterior, y ninguna petición se emite con menos de 10 s de diferencia respecto a la anterior; el User-Agent aplicado es el configurado.
- **Pruebas automáticas:**
  - Con reloj controlado, dos peticiones consecutivas quedan separadas por un intervalo igual o mayor a 10 segundos.
  - Con reloj controlado, tres peticiones consecutivas quedan separadas por intervalos iguales o mayores a 10 segundos cada uno.
  - La primera petición no espera ningún intervalo previo.
  - El limitador es compartido: tras una petición del listado, la siguiente ficha también espera el intervalo restante.
  - La cabecera `User-Agent` enviada contiene el nombre del proyecto y una referencia de contacto.
  - Ninguna petición incluye credenciales ni cabeceras de autenticación.
- **Prueba manual:**
  1. Registrar las marcas de tiempo de una secuencia de peticiones al portal y comprobar que ninguna separación es inferior a 10 segundos.

### [x] TASK-006 Muestras HTML del contrato como fixtures de los tests

- **Cubre:** REQ-006, REQ-008, REQ-012, SUP-006, DEC-009, ALT-001, ALT-002
- **Componente:** api-buscador | tests/fixtures/buscador
- **Módulo:** api-buscador
- **Depende de:** TASK-001
- **Alcance:** Incorporar en `tests/fixtures/buscador/` las muestras reales del contrato HTML de `docs/contracts/html/empleacantabria/` (`listado_pagina_1.html`, `listado_pagina_2.html`, `listado_vacio.html` y `ficha_062026003633.html`), por copia o por referencia al contrato, y comprobar que cubren los casos que necesitan los tests: primera página con el rango `1 - 75 de 93` y enlace a la página 2, última página con el rango `76 - 93 de 93`, listado sin resultados y ficha de oferta real.
- **Hecho cuando:** los cuatro ficheros del contrato están disponibles en `tests/fixtures/buscador/` y conservan su estructura: el listado paginado con `table.table` → `tbody.table-data` → filas con el código en `a[href*="/ofertas-cantabria/-/oferta/"]`, el total y rango en `small.search-results` ("Mostrando el intervalo 1 - 75 de 93 resultados."), la paginación en `ul.lfr-pagination-buttons` con `_..._delta=75` y `_..._cur=N`, el estado vacío con `.lfr-search-container.hide` y el mensaje "No hay resultados", y la ficha con sus `input[readonly]` localizables por sufijo de `id`.
- **Pruebas automáticas:**
  - La página 1 del listado declara el rango `1 - 75 de 93` y conserva 3 filas de ejemplo con sus códigos de 12 dígitos.
  - La página 2 del listado declara el rango `76 - 93 de 93`, conserva 3 filas de ejemplo y su paginación no ofrece página siguiente.
  - El listado vacío no contiene `small.search-results` y sí contiene el mensaje de "No hay resultados".
  - La ficha contiene los seis `input[readonly]` localizables por sufijo (`_numeroOferta`, `_ocupacion`, `_municipio`, `_provincia`, `_fechaInicioDifusion`, `_fechaFinDifusion`) y los bloques de texto libre y contacto.
  - Los cuatro ficheros del contrato son idénticos a sus originales en `docs/contracts/html/empleacantabria/` si se han copiado, o se resuelven desde esa ruta si se referencian.
- **Prueba manual:**
  1. Comparar cada fixture con su fichero del contrato en `docs/contracts/html/empleacantabria/` y comprobar que conservan etiquetas, clases, ids y valores.
  2. Abrir la ficha y confirmar que no contiene ningún campo `sector`, `nivel` ni `contrato`, porque el portal no los publica.

### [x] TASK-007 Recorrido del listado paginado a 75 ofertas

- **Cubre:** REQ-006, REQ-007, REQ-012, NFR-004, DEC-004, DEC-006, ALT-001, ALT-002
- **Componente:** list-scraper | source/api/buscador/scraper.py
- **Módulo:** list-scraper
- **Depende de:** TASK-003, TASK-005, TASK-006
- **Alcance:** Implementar el recorrido del listado del buscador con `selectolax` siguiendo la estructura real del contrato HTML: extraer los códigos de las filas de `table.table` → `tbody.table-data` → `tr`, tomando el texto del enlace `a[href*="/ofertas-cantabria/-/oferta/"]` como código de 12 dígitos; leer el total y el rango en `small.search-results`; seguir la paginación de `ul.lfr-pagination-buttons` con `_..._delta=75` y `_..._cur=N`; y detectar el listado vacío por la clase `hide` en `.lfr-search-container` junto al mensaje de "No hay resultados".
- **Hecho cuando:** el recorrido devuelve el total de ofertas del listado, el rango mostrado y el conjunto de códigos extraídos, todas las peticiones al listado llevan el tamaño de página 75, la última página se reconoce por su rango y su paginación sin página siguiente, un listado vacío se resuelve como total cero sin excepción, y un error HTTP, una falta de respuesta o una estructura no reconocida se devuelven como error global con el punto alcanzado sin marcar ofertas como nuevas.
- **Pruebas automáticas:**
  - Con las dos páginas del contrato, se reconocen el rango `1 - 75 de 93` y el rango `76 - 93 de 93`, el total es 93 y se solicitan las dos páginas con el tamaño 75.
  - Los códigos extraídos son los de 12 dígitos del contrato y se conservan como texto, sin perder ceros por delante.
  - La URL de cada petición al listado incluye el parámetro de tamaño de página con valor 75, conforme a NFR-004.
  - Con la página 2 del contrato, el recorrido la reconoce como última página y no solicita una tercera.
  - Con el listado vacío del contrato, el recorrido devuelve total cero, lista de códigos vacía y ningún error.
  - Con la variante del listado sin `small.search-results`, el recorrido devuelve un error global de parseo del listado y ninguna lista de códigos.
  - Con un cliente de prueba que responde con código de error HTTP, el recorrido devuelve un error global con ese código y no lanza excepción.
  - Con un cliente de prueba que agota el timeout, el recorrido devuelve un error global controlado.
  - Con la segunda página fallida, el recorrido se detiene, informa de la página alcanzada y no devuelve los códigos de esa página.
  - Con un listado cuyos códigos están todos en la lista de códigos ya vistos, el recorrido no marca ninguna oferta como nueva.
- **Prueba manual:**
  1. Recorrer el buscador real con la herramienta y comprobar que el número de códigos extraídos coincide con el total que muestra el portal.

### [x] TASK-008 Descarga y parseo de la ficha de una oferta

- **Cubre:** REQ-008, REQ-009, NFR-002, SUP-006, DEC-004, DEC-007, DEC-009, ALT-003
- **Componente:** detail-parser | source/api/buscador/parser.py
- **Módulo:** detail-parser
- **Depende de:** TASK-005, TASK-006
- **Alcance:** Implementar la descarga de la ficha de un código de oferta a través del limitador de peticiones y la extracción de los campos que publica con `selectolax`, localizando los `input[readonly]` por sufijo de `id` (`_numeroOferta`, `_ocupacion`, `_municipio`, `_provincia`, `_fechaInicioDifusion`, `_fechaFinDifusion`) y el texto libre y el contacto en los `div` que siguen a `label.dAdicionales` y `label.dContacto`, dejando `sector`, `nivel` y `contrato` vacíos, con un único reintento tras la pausa de cortesía cuando la descarga o el parseo fallan.
- **Hecho cuando:** una ficha real devuelve los ocho campos que publica (número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto) y deja `sector`, `nivel` y `contrato` vacíos sin inferencia; los espacios y saltos de línea del texto libre y del contacto se normalizan; una ficha con campos ausentes devuelve los presentes sin inventar valores; y un fallo en la descarga o el parseo se reintenta una sola vez tras esperar la pausa de cortesía y, si persiste, se devuelve como error por oferta con el HTML recibido disponible para su archivado.
- **Pruebas automáticas:**
  - Con la ficha real del contrato, se extraen número de oferta `062026003633`, ocupación, municipio `SANTANDER`, provincia `CANTABRIA`, fecha de inicio `18/11/2026`, fecha de fin `03/12/2026`, texto libre y contacto.
  - Con la misma ficha, `sector`, `nivel` y `contrato` quedan vacíos y no se ha inferido ningún valor para ellos a partir del texto libre, conforme a DEC-009.
  - El texto libre y el contacto se devuelven normalizados, sin espacios sobrantes ni saltos de línea internos.
  - Las fechas se devuelven en formato `dd/mm/aaaa` y el número de oferta se conserva como texto de 12 dígitos.
  - Con la variante de ficha sin bloque de contacto, el campo de contacto queda vacío y el resto de campos se conserva.
  - Con la variante de ficha con los `input` vacíos, los campos correspondientes quedan vacíos y no se inventa ningún valor.
  - Con un cliente de prueba que falla en la primera petición y responde bien en la segunda, la ficha se procesa con éxito y se realizan dos peticiones separadas por al menos 10 segundos.
  - Con un cliente de prueba que falla siempre, se realizan exactamente dos peticiones, la segunda tras la pausa de cortesía, y el resultado es un error por oferta persistente.
  - Con una ficha descargada correctamente, el resultado no conserva ni devuelve el HTML original, conforme a REQ-010.
  - Todas las peticiones de ficha pasan por el limitador y el User-Agent enviado es el configurado.
- **Prueba manual:**
  1. Pedir la ficha real de una oferta del listado y comprobar que los campos extraídos coinciden con los que muestra el portal, con `sector`, `nivel` y `contrato` vacíos.

### [x] TASK-009 Archivo del HTML de las fichas fallidas

- **Cubre:** REQ-010, DEC-005, ALT-003, ALT-006
- **Componente:** html-archive | source/api/buscador/archive.py
- **Módulo:** html-archive
- **Depende de:** TASK-002
- **Alcance:** Implementar el guardado del HTML original de las fichas cuyo parseo falla en `data/failed_htmls/<codigo_oferta>_<yyyy-mm-dd>.html`, creando el directorio si no existe y registrando un error de escritura cuando el directorio no está disponible, sin interrumpir la pasada.
- **Hecho cuando:** tras un fallo de parseo existe un fichero HTML con el contenido recibido del portal cuyo nombre sigue el formato `<codigo>_<yyyy-mm-dd>.html`, el directorio se crea cuando falta y, si la escritura no es posible, se devuelve un error por oferta que lo indica sin detener el resto de fichas.
- **Pruebas automáticas:**
  - Con una ficha fallida de código `062026003484`, se crea `data/failed_htmls/062026003484_<fecha>.html` con el contenido recibido.
  - Con el directorio inexistente, el archivado lo crea y escribe el fichero.
  - Con el directorio no escribible, el archivado devuelve un error controlado que indica que no se pudo guardar el HTML y no lanza excepción.
  - El nombre del fichero usa la fecha en formato `yyyy-mm-dd` y el código de oferta sin transformaciones.
  - Archivar dos fichas fallidas del mismo código en el mismo día no produce ficheros con nombres ambiguos ni pérdida de contenido.
- **Prueba manual:**
  1. Provocar un fallo de parseo real y comprobar que el fichero aparece en `data/failed_htmls/` con el nombre esperado y que su contenido es el HTML recibido del portal.

### [x] TASK-010 Purga de los HTML fallidos caducados

- **Cubre:** REQ-011, DEC-005
- **Componente:** archive-purger | source/api/buscador/purger.py
- **Módulo:** archive-purger
- **Depende de:** TASK-009
- **Alcance:** Implementar la eliminación de los ficheros HTML de `data/failed_htmls/` con más de 7 días de antigüedad, calculando la antigüedad a partir de la fecha `yyyy-mm-dd` del nombre del fichero y sin tocar los más recientes.
- **Hecho cuando:** tras la limpieza, los ficheros con más de 7 días han desaparecido y los de 7 días o menos permanecen en el directorio.
- **Pruebas automáticas:**
  - Con un fichero fechado hace 8 días, la purga lo elimina.
  - Con un fichero fechado hace exactamente 7 días, la purga lo conserva.
  - Con un fichero fechado hace 1 día, la purga lo conserva.
  - Con un directorio de HTML fallidos vacío o inexistente, la purga no falla.
  - La purga solo afecta a ficheros `.html` del directorio de HTML fallidos y no toca el fichero `seen_codes.json`.
- **Prueba manual:**
  1. Crear a mano un HTML fallido con fecha antigua en el nombre, ejecutar la purga y comprobar que desaparece mientras los recientes siguen.

### [x] TASK-011 Ensamblado del resultado estructurado de la pasada

- **Cubre:** REQ-013, REQ-012, SUP-003, DEC-002, ALT-001, ALT-002
- **Componente:** response-assembler | source/api/buscador/assembler.py
- **Módulo:** response-assembler
- **Depende de:** TASK-002, TASK-007, TASK-008
- **Alcance:** Implementar el componente que construye el JSON de resultado de la pasada con los metadatos de ejecución (timestamp, comunidad, total de ofertas del listado), el error global, los errores por oferta y la lista de ofertas nuevas parseadas, sin persistencia en base de datos.
- **Hecho cuando:** el resultado de una pasada completada contiene el timestamp, la comunidad Cantabria, el total de ofertas del listado, el error global cuando existe, los errores por oferta y la lista de ofertas nuevas; un fallo global produce un resultado con lista de ofertas vacía y un listado vacío produce un resultado con total cero, sin errores y sin ofertas.
- **Pruebas automáticas:**
  - Con una pasada con dos ofertas nuevas y un error por oferta, el resultado incluye ambas ofertas, el total del listado, el timestamp y la lista de errores por oferta.
  - Con un error global, el resultado incluye ese error, la lista de ofertas queda vacía y el total de ofertas del listado refleja lo alcanzado.
  - Con un listado vacío, el resultado tiene total cero, ninguna lista de errores y ninguna oferta nueva.
  - El resultado incluye la comunidad con el valor Cantabria.
  - El resultado no contiene ningún campo de persistencia en base de datos ni referencia a SQLite.
- **Prueba manual:**
  1. Revisar un ejemplo de resultado con ofertas, error global y error por oferta y comprobar que se distingue el origen de cada dato.

### [x] TASK-012 Coordinador de una pasada y exclusión mutua

- **Cubre:** REQ-003, REQ-005, REQ-007, REQ-009, REQ-012, SUP-004, DEC-002, DEC-006, ALT-003, ALT-004
- **Componente:** run-coordinator | source/api/buscador/coordinator.py
- **Módulo:** run-coordinator
- **Depende de:** TASK-004, TASK-007, TASK-008, TASK-009, TASK-010, TASK-011
- **Alcance:** Implementar el ciclo completo de una pasada: cargar los códigos vistos, descartar del listado los códigos ya vistos, pedir la ficha de cada código nuevo, registrar los códigos correctamente parseados para persistir al final, ejecutar la purga de HTML fallidos y liberar el estado al terminar, manteniendo el flag de pasada en curso que se comparte con el planificador y el endpoint manual.
- **Hecho cuando:** una pasada completa devuelve el resultado ensamblado y persiste únicamente los códigos de las fichas parseadas correctamente; una solicitud de inicio mientras hay otra pasada en curso se rechaza, deja constancia de la omisión y mantiene la pasada en curso hasta su finalización.
- **Pruebas automáticas:**
  - Con un listado de tres códigos y un fichero de vistos que contiene uno, solo se piden las fichas de los dos códigos no vistos.
  - Al finalizar una pasada, el fichero de códigos vistos contiene los códigos parseados correctamente y no contiene los de las fichas fallidas.
  - Con una lista de códigos históricos explícita, la pasada filtra con esa lista en lugar del fichero local.
  - Sin lista explícita, la pasada filtra con el fichero local de códigos vistos.
  - Con una pasada en curso, una segunda solicitud de inicio se rechaza, no se lanza una segunda pasada y queda registrado que la ejecución fue omitida.
  - Tras finalizar la pasada en curso, el sistema queda listo para la siguiente programación sin procesos huérfanos ni flag residual.
  - Una ficha fallida en una pasada anterior se vuelve a solicitar en la pasada siguiente si su código sigue en el listado.
  - Al terminar una pasada, se ejecuta la purga de los HTML fallidos con más de 7 días.
  - Con un listado cuyo recorrido falla, la pasada termina con error global y no persiste ningún código nuevo.
- **Prueba manual:**
  1. Lanzar una pasada manual con un listado simulado y comprobar el fichero `seen_codes.json` al terminar: contiene exactamente los códigos parseados correctamente.

### [x] TASK-013 Planificador diario de la pasada automática

- **Cubre:** REQ-002, REQ-003, NFR-005, SUP-001, DEC-001, ALT-004
- **Componente:** scheduler | source/api/buscador/scheduler.py
- **Módulo:** scheduler
- **Depende de:** TASK-003, TASK-012
- **Alcance:** Implementar la tarea en proceso que programa la pasada automática al comienzo de la hora configurada: espera la siguiente ejecución al día siguiente, se cancela al apagar la API y delega en el coordinador el inicio de la pasada, saltándose la ejecución si ya hay una pasada en curso.
- **Hecho cuando:** con la hora 01:00 configurada, el planificador inicia una pasada al alcanzar las 01:00:00; al transcurrir 24 horas completas desde esa ejecución se produce exactamente una pasada automática más; y una solicitud del planificador durante una pasada en curso se omite sin iniciar una segunda.
- **Pruebas automáticas:**
  - Con el reloj controlado en las 00:59:59 y la hora 01:00, no se ha iniciado ninguna pasada.
  - Con el reloj controlado en las 01:00:00 y la hora 01:00, se inicia exactamente una pasada.
  - Tras avanzar 24 horas completas desde la ejecución, se ha iniciado exactamente una pasada automática más.
  - Con la hora 23, la pasada se dispara al llegar las 23:00:00.
  - Con una pasada en curso, el disparo del planificador no inicia una segunda pasada y queda constancia de la omisión.
  - Al cancelar el planificador, no se inicia ninguna pasada posterior y no quedan tareas en ejecución.
- **Prueba manual:**
  1. Arrancar la API con la hora configurada a un minuto próximo y observar que la pasada arranca sola a esa hora exacta.

### [x] TASK-014 Endpoint de pasada manual

- **Cubre:** REQ-014, REQ-005, REQ-013, SUP-002, DEC-008, ALT-004
- **Componente:** manual-trigger | source/api/buscador
- **Módulo:** manual-trigger
- **Depende de:** TASK-012
- **Alcance:** Implementar el endpoint HTTP que lanza una pasada de forma manual, con cuerpo JSON opcional que admite una lista de códigos históricos, delegando en el coordinador el inicio y devolviendo la misma estructura JSON de resultado que la pasada automática.
- **Hecho cuando:** el endpoint responde HTTP 200 con el resultado estructurado de la pasada; sin lista de códigos históricos en el cuerpo usa `data/seen_codes.json`; con lista explícita usa esa lista en lugar del fichero local; y una invocación durante una pasada en curso devuelve la respuesta de omisión sin iniciar una segunda pasada.
- **Pruebas automáticas:**
  - El endpoint está registrado con el método y la ruta del diseño y acepta un cuerpo JSON opcional.
  - Sin cuerpo, la pasada se filtra con los códigos del fichero local de vistos.
  - Con `historical_codes` explícita, la pasada se filtra con esa lista y no con el fichero local.
  - La respuesta tiene la misma estructura de resultado que la pasada automática: metadatos, error global, errores por oferta y ofertas nuevas.
  - Con una pasada en curso, la respuesta HTTP 200 indica que ya hay una pasada en curso y no se inicia una nueva.
  - El endpoint no exige credenciales ni cabeceras de autenticación, conforme a NFR-003.
- **Prueba manual:**
  1. Invocar el endpoint manual sin cuerpo y comprobar que devuelve el resultado de la pasada con la estructura de REQ-013.
  2. Invocar el endpoint manual con una lista de códigos históricos y comprobar que se filtran por esa lista.

### [x] TASK-015 Endpoint de estado de la última pasada

- **Cubre:** REQ-015, SUP-002
- **Componente:** status-endpoint | source/api/buscador
- **Módulo:** status-endpoint
- **Depende de:** TASK-012
- **Alcance:** Implementar el endpoint HTTP que devuelve el estado de la última pasada: si hay una pasada en curso, su hora de inicio y el progreso disponible, y el resumen de la última ejecución finalizada (timestamp, total de ofertas del listado, ofertas nuevas, error global y errores por oferta), leyendo el estado compartido del coordinador.
- **Hecho cuando:** sin pasada en curso, la respuesta indica explícitamente que no la hay y muestra el resumen de la última pasada finalizada; con pasada en curso, indica que la hay, su hora de inicio y el progreso; y el resumen incluye el timestamp, el total de ofertas del listado, el número de ofertas nuevas, el error global y los errores por oferta.
- **Pruebas automáticas:**
  - Sin ninguna pasada registrada, la respuesta indica que no hay pasada en curso y que no hay última pasada finalizada.
  - Con una pasada en curso, la respuesta incluye `in_progress` en true, la hora de inicio y el progreso disponible.
  - Con una pasada finalizada, la respuesta incluye `in_progress` en false y el resumen con timestamp, total de ofertas del listado, número de ofertas nuevas, error global y errores por oferta.
  - Tras una pasada con dos ofertas nuevas y un error por oferta, el resumen refleja esas dos ofertas nuevas y ese error por oferta.
  - El endpoint no exige credenciales ni cabeceras de autenticación, conforme a NFR-003.
- **Prueba manual:**
  1. Consultar el endpoint de estado con la aplicación en reposo y comprobar que indica que no hay pasada en curso.
  2. Lanzar una pasada manual larga y consultar el estado mientras se ejecuta: indica que hay pasada en curso con su hora de inicio.

### [x] TASK-016 Arranque y apagado de la API con el planificador

- **Cubre:** REQ-001, REQ-002, REQ-004, NFR-003, NFR-005, SUP-001, DEC-001
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-003, TASK-013
- **Alcance:** Integrar en la aplicación FastAPI existente la carga de la configuración del buscador, la lectura del fichero de códigos vistos al arrancar, el arranque del planificador con la hora configurada y su cancelación al apagar la API, sin exigir autenticación en ningún endpoint.
- **Hecho cuando:** al arrancar la API se lee la configuración, se lee `data/seen_codes.json` y queda activo el planificador con la hora configurada; al apagar la API el planificador se cancela sin dejar tareas en ejecución; y ningún endpoint exige credenciales.
- **Pruebas automáticas:**
  - Tras arrancar la aplicación, el fichero `data/seen_codes.json` se ha leído o creado y el planificador está activo con la hora de la configuración.
  - Al apagar la aplicación, el planificador queda cancelado y no se inician nuevas pasadas.
  - Una petición a cada endpoint sin credenciales ni cabeceras de autenticación recibe respuesta, sin 401 ni 403, conforme a NFR-003.
  - Con una configuración de hora inválida, la aplicación conserva la hora anterior o, en el primer arranque, la por defecto 01:00, sin cambiar la programación.
  - Tras atender peticiones, no se ha creado ni modificado ningún fichero de base de datos en el árbol del proyecto.
- **Prueba manual:**
  1. Levantar la aplicación, comprobar que el fichero `data/seen_codes.json` existe y que el endpoint de estado responde.
  2. Detener la aplicación y comprobar que no queda ninguna tarea de planificación viva.

### [x] TASK-017 Verificación de integración de la pasada completa

- **Cubre:** REQ-006, REQ-007, REQ-009, REQ-012, REQ-013, REQ-014, REQ-015, ALT-001, ALT-002, ALT-003, ALT-004
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-014, TASK-015, TASK-016
- **Alcance:** Verificar de extremo a extremo la comunicación entre la aplicación, el coordinador, el recorrido del listado, el parseo de ficha y el ensamblado, montando la aplicación con cliente de prueba y simulando el portal, y cubrir el caso de listado con ofertas nuevas, con fallo del portal y con listado vacío.
- **Hecho cuando:** una petición de pasada manual con el portal simulado devuelve HTTP 200 con un resultado que refleja los tres casos, el fichero de códigos vistos queda actualizado solo con las fichas correctas y la consulta de estado posterior muestra el resumen de esa pasada, sin excepciones no controladas.
- **Pruebas automáticas:**
  - Con un listado de dos códigos nuevos, la respuesta contiene dos ofertas parseadas y el fichero de vistos queda con esos dos códigos.
  - Con una de las dos fichas fallando de forma persistente, la respuesta incluye el error por oferta, el HTML fallido queda archivado y el fichero de vistos contiene solo el código correcto.
  - Con el portal devolviendo error HTTP, la respuesta incluye el error global, la lista de ofertas está vacía y el fichero de vistos no cambia.
  - Con un listado vacío, la respuesta tiene total cero y no modifica el fichero de vistos.
  - Con una pasada manual en curso, una segunda invocación devuelve la respuesta de omisión y la segunda pasada no se ejecuta.
  - Tras la pasada, el endpoint de estado muestra el resumen con el total, las ofertas nuevas y los errores.
  - Ninguno de los fallos por oferta ni el error global cambia el código HTTP de la respuesta, que sigue siendo 200.
  - La petición no deja ningún fichero de base de datos creado en el árbol del proyecto.
- **Prueba manual:**
  1. Ejecutar la prueba de integración y revisar el informe: todos los escenarios salen con el resultado esperado.
  2. Revisar el directorio `data/` tras la prueba: solo existen `seen_codes.json` y `failed_htmls/` con el HTML de la ficha fallida.

### [x] TASK-018 Contrato: openapi - endpoints de pasada manual y de estado

- **Cubre:** REQ-008, REQ-013, REQ-014, REQ-015, SUP-002, SUP-006, DEC-008, DEC-009
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-014, TASK-015, TASK-017
- **Alcance:** Crear el contrato OpenAPI `docs/contracts/openapi/api-buscador.yaml` que formaliza los endpoints de pasada manual (`POST /buscador/run`) y de estado (`GET /buscador/status`) tal como quedaron implementados, incluyendo el esquema de la respuesta de resultado, el modelo de error por oferta, el cuerpo opcional con `historical_codes` y la respuesta de omisión por solapamiento.
- **Hecho cuando:** el contrato existe en `docs/contracts/openapi/api-buscador.yaml`, describe las dos operaciones con sus cuerpos opcionales, el esquema de resultado de pasada con metadatos, error global, errores por oferta y ofertas nuevas, con el esquema de oferta incluyendo los campos que publica la ficha más `sector`, `nivel` y `contrato` como cadenas vacías, y coincide con la implementación verificada en TASK-017.
- **Pruebas automáticas:**
  - El YAML del contrato se carga correctamente y contiene las dos operaciones con su respuesta 200 y los esquemas de resultado de pasada, oferta y error por oferta.
  - El esquema de oferta del contrato incluye `sector`, `nivel` y `contrato` como campos presentes y opcionales, con la descripción de que la ficha no los publica y se devuelven vacíos.
  - El contrato documenta el cuerpo opcional con la lista de códigos históricos y la respuesta de omisión por solapamiento.
  - Los campos del esquema de oferta del contrato coinciden con los que devuelve la implementación en la prueba de integración.
  - Las rutas del contrato coinciden con las registradas en la aplicación.
- **Prueba manual:**
  1. Revisar el contrato y comprobar que aparecen las dos interfaces de la fila: el endpoint de pasada manual y el endpoint de estado.
  2. Comparar el contrato con la respuesta JSON real obtenida en TASK-017 y confirmar que no hay campos divergentes.

### [x] TASK-019 Contrato: configuración - fichero de configuración del buscador

- **Cubre:** REQ-001, NFR-001, NFR-002, NFR-004, SUP-001, DEC-003, DEC-005
- **Componente:** config-buscador | config/buscador.yaml
- **Módulo:** config-buscador
- **Depende de:** TASK-003
- **Alcance:** Formalizar el contrato de configuración del buscador: documentar el formato exacto del fichero `config/buscador.yaml` (URL del listado, URL de la ficha, hora de pasada como entero único, User-Agent, delay entre peticiones, tamaño de página, rutas de datos y días de purga) y las reglas de validación de la hora, dejándolo alineado con lo que la carga de TASK-003 interpreta.
- **Hecho cuando:** el formato queda documentado, el fichero real lo cumple sin ambigüedad y una configuración válida se carga sin cambios de código.
- **Pruebas automáticas:**
  - El fichero `config/buscador.yaml` se carga con el formato documentado y devuelve hora, URLs, User-Agent, delay, tamaño de página y rutas.
  - Una configuración con la hora fuera del rango 0-23 o con un tipo no entero se rechaza con un error controlado.
  - Una configuración sin los campos obligatorios se rechaza con un error controlado que identifica el campo ausente.
  - Los valores por defecto del contrato (hora 01:00, delay 10 s, tamaño de página 75, purga a 7 días) coinciden con los que aplica la implementación.
- **Prueba manual:**
  1. Revisar que la fila de contrato (configuración del buscador) queda descrita con el mismo formato que usa el fichero real.
  2. Modificar el fichero siguiendo solo el formato documentado y comprobar que la API arranca con la nueva configuración.

### [x] TASK-020 Contrato: configuración - URLs del buscador en el mapa de comunidades

- **Cubre:** REQ-006, SUP-003, DEC-004
- **Componente:** config-map | config/comunidades.yaml
- **Módulo:** CONFIG-MAP
- **Depende de:** TASK-003, TASK-007
- **Alcance:** Documentar y, si se opta por un único fichero de configuración por comunidad, modificar `config/comunidades.yaml` para añadir al caso de Cantabria las URLs del buscador HTML y de la ficha, dejando el formato alineado con lo que el recorrido del listado y el parseo de la ficha consumen.
- **Hecho cuando:** el formato de las URLs del buscador y de la ficha queda documentado en el contrato de configuración y, si se mantienen en `config/comunidades.yaml`, el caso de Cantabria las declara y la carga las devuelve sin ambigüedad.
- **Pruebas automáticas:**
  - El fichero de configuración de comunidades se carga y devuelve el caso de Cantabria con las URLs del listado y de la ficha.
  - Un caso de comunidad sin las URLs del buscador se rechaza o se marca como no apto para el buscador, con un error controlado.
  - La URL del listado devuelta es la que el recorrido del listado usa para construir sus peticiones.
- **Prueba manual:**
  1. Revisar que las URLs del buscador y de la ficha del caso de Cantabria coinciden con las del portal y con las usadas en la configuración del buscador.

### [x] TASK-021 Variantes derivadas de las muestras del contrato

- **Cubre:** REQ-006, REQ-008, REQ-012, ALT-001, ALT-002, ALT-003
- **Componente:** api-buscador | tests/fixtures/buscador
- **Módulo:** api-buscador
- **Depende de:** TASK-006, TASK-007, TASK-008
- **Alcance:** Derivar de las muestras reales del contrato las variantes mínimas que necesitan los tests sin inventar estructuras nuevas: una ficha derivada sin el bloque de contacto, una variante del listado sin `small.search-results` para representar una estructura no reconocida y una variante de la ficha con los `input` vacíos. Cada variante se genera a partir del fichero del contrato, de modo que el contrato siga siendo la única fuente de verdad.
- **Hecho cuando:** las variantes derivadas existen en `tests/fixtures/buscador/`, son copias modificables del fichero del contrato del que salen y cada una es consumida por al menos una prueba automática del recorrido del listado o del parseo de la ficha.
- **Pruebas automáticas:**
  - La ficha sin bloque de contacto se parsea con el campo de contacto vacío y sin error, y el resto de campos se conservan.
  - La variante del listado sin `small.search-results` se comunica como error global de estructura del listado, sin excepción no controlada.
  - La variante de la ficha con los `input` vacíos se parsea con los campos correspondientes vacíos y sin inventar valores.
  - Cada variante derivada se referencia desde al menos una prueba de la suite.
- **Prueba manual:**
  1. Comparar cada variante con el fichero del contrato del que deriva y comprobar que la única diferencia es la que la variante pretende provocar.

### [x] TASK-022 Pruebas de frecuencia de peticiones y de solapamiento

- **Cubre:** REQ-003, NFR-002, NFR-005, DEC-003, DEC-007, ALT-004
- **Componente:** rate-limiter | source/api/buscador/rate_limiter.py
- **Módulo:** rate-limiter
- **Depende de:** TASK-005, TASK-012, TASK-013
- **Alcance:** Verificar con reloj controlado la frecuencia global de peticiones en una pasada completa (listado, fichas y reintentos mezclados) y el comportamiento de solapamiento entre el planificador y el endpoint manual, de modo que ninguna pareja de peticiones consecutivas quede por debajo del intervalo mínimo y no se solapen pasadas.
- **Hecho cuando:** en una pasada simulada con listado, varias fichas y un reintento, el intervalo entre cualquier par de peticiones consecutivas es igual o mayor a 10 segundos, y una segunda solicitud de inicio durante una pasada en curso se rechaza dejando constancia de la omisión.
- **Pruebas automáticas:**
  - Con el reloj controlado, la secuencia completa de peticiones de una pasada (páginas del listado, fichas y reintento) respeta un intervalo mínimo de 10 segundos entre cada par consecutivo.
  - La primera petición de la pasada se emite sin espera previa.
  - Con una pasada en curso, la solicitud del planificador y la del endpoint manual se rechazan ambas.
  - Con el listado del contrato (93 ofertas en dos páginas de 75), el número de peticiones del listado es el esperado para cubrir el total con páginas de 75.
  - En 24 horas simuladas con la configuración por defecto, el número de pasadas automáticas es exactamente uno.
- **Prueba manual:**
  1. Revisar el informe de la prueba y confirmar que los intervalos medidos entre peticiones son todos mayores o iguales a 10 segundos.

### [ ] TASK-023 Actualización del mapa de arquitectura

- **Cubre:** DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, DEC-008, DEC-009
- **Componente:** api-service | source/api
- **Módulo:** API
- **Depende de:** TASK-017, TASK-018, TASK-019, TASK-020, TASK-021, TASK-022
- **Alcance:** Registrar en `.sdd/architecture.md` los módulos nuevos del buscador, el contrato OpenAPI del buscador, el contrato de configuración y las tres convenciones de rastreo, y actualizar la descripción del módulo `API` para que incluya también el rastreador del buscador, con los identificadores y rutas definitivos realmente implementados.
- **Hecho cuando:** el mapa contiene una entrada por cada módulo nuevo implementado con su identificador, ruta, responsabilidad y dependencias, la entrada del contrato OpenAPI del buscador, las tres convenciones de rastreo y el módulo `API` actualizado con las rutas reales del repositorio.
- **Pruebas automáticas:**
  - Una comprobación lee `.sdd/architecture.md` y confirma que aparecen los identificadores de todos los módulos nuevos del buscador con una ruta no vacía.
  - Una comprobación confirma que la sección de contratos incluye el OpenAPI del buscador y que la sección de convenciones incluye las tres convenciones de rastreo.
  - Una comprobación confirma que la descripción del módulo `API` ya no se limita al parseo de PDFs.
  - Todos los ficheros citados en el mapa existen en el repositorio.
- **Prueba manual:**
  1. Revisar `.sdd/architecture.md` y comprobar que cada módulo nuevo del buscador tiene su identificador, su ruta y sus dependencias, y que las rutas coinciden con los ficheros realmente creados.

## Cobertura

| Requisito | Tareas |
|---|---|
| REQ-001 | TASK-003, TASK-016, TASK-019 |
| REQ-002 | TASK-013, TASK-016, TASK-022 |
| REQ-003 | TASK-012, TASK-013, TASK-014, TASK-022 |
| REQ-004 | TASK-004, TASK-012, TASK-016 |
| REQ-005 | TASK-004, TASK-012, TASK-014 |
| REQ-006 | TASK-006, TASK-007, TASK-017, TASK-020, TASK-021 |
| REQ-007 | TASK-007, TASK-012, TASK-017 |
| REQ-008 | TASK-002, TASK-006, TASK-008, TASK-018, TASK-021 |
| REQ-009 | TASK-008, TASK-012, TASK-017 |
| REQ-010 | TASK-009 |
| REQ-011 | TASK-010 |
| REQ-012 | TASK-007, TASK-011, TASK-012, TASK-017, TASK-021 |
| REQ-013 | TASK-002, TASK-011, TASK-014, TASK-017, TASK-018 |
| REQ-014 | TASK-014, TASK-017, TASK-018 |
| REQ-015 | TASK-015, TASK-017, TASK-018 |

| Requisito no funcional | Tareas |
|---|---|
| NFR-001 | TASK-003, TASK-005, TASK-019 |
| NFR-002 | TASK-005, TASK-008, TASK-019, TASK-022 |
| NFR-003 | TASK-014, TASK-015, TASK-016 |
| NFR-004 | TASK-003, TASK-007, TASK-019 |
| NFR-005 | TASK-003, TASK-016, TASK-022 |

| Decisión | Tareas |
|---|---|
| DEC-001 | TASK-001, TASK-013, TASK-016, TASK-023 |
| DEC-002 | TASK-001, TASK-004, TASK-011, TASK-023 |
| DEC-003 | TASK-005, TASK-019, TASK-022, TASK-023 |
| DEC-004 | TASK-001, TASK-007, TASK-008, TASK-020, TASK-023 |
| DEC-005 | TASK-009, TASK-010, TASK-019, TASK-023 |
| DEC-006 | TASK-007, TASK-012, TASK-023 |
| DEC-007 | TASK-008, TASK-022, TASK-023 |
| DEC-008 | TASK-014, TASK-018, TASK-023 |
| DEC-009 | TASK-002, TASK-008, TASK-018, TASK-023 |

| Supuesto | Tareas |
|---|---|
| SUP-001 | TASK-003, TASK-013, TASK-016, TASK-019 |
| SUP-002 | TASK-014, TASK-015, TASK-018 |
| SUP-003 | TASK-002, TASK-011, TASK-020 |
| SUP-004 | TASK-004, TASK-012 |
| SUP-005 | TASK-009, TASK-010 |
| SUP-006 | TASK-002, TASK-006, TASK-008, TASK-018 |

| Escenario alternativo | Tareas |
|---|---|
| ALT-001 | TASK-006, TASK-007, TASK-011, TASK-017, TASK-021 |
| ALT-002 | TASK-006, TASK-007, TASK-011, TASK-017 |
| ALT-003 | TASK-008, TASK-009, TASK-012, TASK-017, TASK-021 |
| ALT-004 | TASK-012, TASK-013, TASK-014, TASK-017, TASK-022 |
| ALT-005 | TASK-003 |
| ALT-006 | TASK-009 |

## Avisos

- Las muestras HTML reales del contrato están en `docs/contracts/html/empleacantabria/` (`listado_pagina_1.html`, `listado_pagina_2.html`, `listado_vacio.html`, `ficha_062026003633.html` y su README). Son **muestras reducidas**: la página 1 conserva 3 de las 75 filas y la página 2, 3 de las 18. TASK-006 las incorpora o referencia en `tests/fixtures/buscador/`; las tareas ya no inventan una página con 75 filas reales.
- El total 93 y los rangos `1 - 75 de 93` y `76 - 93 de 93` salen del campo `small.search-results` de las muestras; el diseño indica que no hay otro campo de total, así que el scraper debe deducir el total de ese texto. TASK-007 refleja ese encadenamiento.
- Los casos de borde que el contrato real no permite suponer se han eliminado. TASK-021 ya no exige fixtures de "total que no cuadra" ni de "página intermedia con menos de 75 ofertas": ahora deriva de las muestras reales tres variantes (ficha sin bloque de contacto, listado sin `small.search-results` y ficha con `input` vacíos), dejando el contrato HTML como única fuente de verdad.
- `sector`, `nivel` y `contrato` no tienen fuente en la ficha del portal. DEC-009 fija que se mantengan en el modelo y se devuelvan vacíos: TASK-002 los conserva, TASK-006 verifica que las muestras no los contienen, TASK-008 no intenta extraerlos y TASK-018 los documenta en el contrato como campos presentes y vacíos.
- La estrategia de contratos aplicada es `implementation-first`, valor tomado de la opción `contract-strategy` de `.sdd/team.md`. Por eso TASK-018 depende de TASK-014, TASK-015 y TASK-017; TASK-019 depende de TASK-003; y TASK-020 depende de TASK-003 y TASK-007.
- Los módulos del buscador (`api-buscador`, `config-buscador`, `scheduler`, `run-coordinator`, `rate-limiter`, `state-store`, `list-scraper`, `detail-parser`, `html-archive`, `archive-purger`, `response-assembler`, `manual-trigger`, `status-endpoint`) **no existen todavía en `.sdd/architecture.md`**; sus identificadores y rutas proceden de la tabla "Cambios sugeridos al mapa" del diseño. Las tareas que los implementan llevan su `Componente` con la ruta propuesta en el diseño y su línea `Módulo` con el identificador del mapa; TASK-023 es la que fija las rutas definitivas y registra las entradas. Solo `API` y `CONFIG-MAP` constan hoy en el mapa.
- La fila "Configuración / `config/comunidades.yaml` (modificación sugerida)" del diseño es una sugerencia, no un requisito firme: el diseño propone `config/buscador.yaml` como fichero propio y menciona `config/comunidades.yaml` solo como alternativa. TASK-020 se ha creado porque la skill exige una tarea por fila de "Contratos afectados" y su alcance está redactado para que sea válida tanto si las URLs se mantienen en `config/comunidades.yaml` como si solo se documentan en el contrato. Si la capa técnica decide no tocar `config/comunidades.yaml`, basta con dejar TASK-020 en el contrato de configuración y su alcance ya lo permite.
- El diseño deja abierto el prefijo de las rutas (`/buscador/run` y `/buscador/status`, "o equivalente bajo el prefijo adoptado por `api-pdf-parser`"). Se adopta por defecto `/buscador/run` y `/buscador/status` por ser los propuestos en el propio diseño; si la capa técnica adopta otro prefijo, el cambio queda limitado a la ruta, al contrato OpenAPI (TASK-018) y a la prueba de integración (TASK-017).
- El diseño no fija el mecanismo concreto del planificador en proceso (biblioteca o temporizador propio). TASK-013 se limita al comportamiento exigible: dispara al comienzo de la hora configurada, una vez al día, salta la ejecución si hay solapamiento y se cancela al apagar. La elección técnica queda para el analista.
- La ubicación de los contratos de configuración sigue la convención del propio diseño (`config/buscador.yaml` y `config/comunidades.yaml`), fuera de `docs/contracts/`. Si la capa técnica prefiere `docs/contracts/<protocolo>/`, debe indicarlo antes de implementar TASK-019 y TASK-020.
- La URL concreta del listado y de la ficha del portal no está fijada en los requisitos ni en el diseño; TASK-003 y TASK-020 la toman de la configuración real del portal, que puede deducirse de las muestras del contrato (`https://empleacantabria.es/ofertas-cantabria` y `.../ofertas-cantabria/-/oferta/<codigo>`, según el README del contrato).
- No existe `.sdd/task-types.md`, así que no hay tipos de tarea propios del proyecto que generar.
