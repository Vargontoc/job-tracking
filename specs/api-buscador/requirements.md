# Requisitos: api-buscador

Estado: aprobado
Revisión: 5
Verificación: correcta

## Contexto

Esta feature implementa el rastreador del buscador HTML de Emplea Cantabria, fuente principal del producto según PDEC-013. La API permanece levantada y ejecuta una pasada diaria que recorre el listado paginado, identifica las ofertas cuyo código no se ha visto todavía, descarga la ficha de cada una, extrae sus campos y devuelve el resultado estructurado. La programación es interna y se configura por una única hora del día. Cubre **FUN-001**.

## Referencias

- Contratos HTML de referencia en `docs/contracts/html/empleacantabria/`:
  - `listado_pagina_1.html`, `listado_pagina_2.html`: estructura real del listado paginado con tamaño 75, código de oferta (12 dígitos), descripción, municipio y fecha de inicio.
  - `listado_vacio.html`: estructura del listado sin resultados.
  - `ficha_062026003633.html`: estructura real de la ficha de oferta.
- La ficha publica los campos: número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto. La decisión DEC-009 (18/11/2026) establece que `sector`, `nivel` y `contrato` se mantienen en el modelo pero se devuelven vacíos, porque la ficha no los publica y no existe otra fuente.

## Fuera de alcance

- Persistencia en SQLite u otra base de datos; la feature no guarda ofertas ni histórico.
- Envío de notificaciones (Telegram) o generación del digest.
- Detección de ofertas cerradas ni histórico de altas y bajas; corresponde a `api-historico`.
- Puntuación de encaje, embeddings o inferencia con modelos locales.
- Ampliación a comunidades distintas de Cantabria; el modelo incluye comunidad/provincia para no rehacer datos en el futuro, pero el comportamiento de esta feature se limita a Cantabria.
- Parseo o descarga del PDF de difusión; cubierto por `api-pdf-parser`.
- Empaquetado de la aplicación en ventana de escritorio.

## Requisitos funcionales

### REQ-001 Horario de pasada configurable por hora

- **Requisito:** El sistema deberá permitir configurar el horario de la pasada automática como una única hora entera del día (0-23).
- **Criterios de aceptación:**
  - Dado que la API está levantada, cuando se consulta su configuración, entonces se muestra la hora configurada como un entero entre 0 y 23.
  - Dada una instalación nueva, cuando se inicia la API por primera vez, entonces la hora por defecto es 01:00.
  - Dado un administrador, cuando modifica la hora mediante la configuración, entonces la programación se ajusta sin necesidad de reiniciar el proceso.
  - Dado un intento de configurar una lista de horas, minutos, fracciones de hora o expresiones cron completas, cuando se valida la configuración, entonces el sistema las rechaza.

### REQ-002 Ejecución automática diaria a la hora configurada

- **Requisito:** Mientras la API esté en ejecución, el sistema deberá lanzar automáticamente una única pasada al día al comienzo de la hora configurada.
- **Criterios de aceptación:**
  - Dada una API en ejecución con la hora 01:00 configurada, cuando el reloj del sistema alcanza las 01:00:00, entonces se inicia una pasada.
  - Dada una API en ejecución con una hora configurada, cuando transcurren 24 horas completas, entonces se lanza exactamente una pasada automática.

### REQ-003 Prevención de solapamiento de pasadas

- **Requisito:** Si una pasada anterior sigue en curso cuando toca iniciar una nueva, el sistema deberá omitir la nueva ejecución, mantener la actual hasta su finalización y dejar constancia de la omisión.
- **Criterios de aceptación:**
  - Dado que una pasada está en curso, cuando llega el momento programado para la siguiente, entonces no se inicia una segunda pasada simultánea.
  - Dado que se omite una ejecución por solapamiento, cuando finaliza la pasada en curso, entonces el sistema registra o informa que la ejecución programada fue omitida.
  - Dado que se omite una ejecución por solapamiento, cuando termina la pasada en curso, entonces el sistema queda listo para la siguiente programación sin dejar procesos huérfanos.

### REQ-004 Mantener fichero local de códigos vistos

- **Requisito:** El sistema deberá mantener un fichero local mínimo (`data/seen_codes.json` o nombre equivalente) con los códigos de oferta cuya ficha se ha parseado correctamente en pasadas anteriores.
- **Criterios de aceptación:**
  - Dada una pasada automática que finaliza correctamente, cuando se actualiza el fichero local, entonces contiene todos los códigos de oferta cuya ficha se parseó correctamente, unidos a los ya registrados.
  - Dada una oferta cuya ficha falló en la descarga o el parseo, cuando finaliza la pasada, entonces su código no se añade al fichero local de códigos vistos.
  - Dado que existe un fichero local de códigos vistos, cuando se inicia la API, entonces el sistema lo lee al arrancar.
  - Dado que el fichero local no existe, cuando se inicia la API, entonces se crea vacío y se considera que no hay códigos previos.

### REQ-005 Usar códigos vistos para filtrar ofertas nuevas

- **Requisito:** El sistema deberá usar el fichero local de códigos vistos para identificar las ofertas nuevas durante las pasadas automáticas.
- **Criterios de aceptación:**
  - Dada una pasada automática, cuando se recorre el listado, entonces se consideran nuevas solo las ofertas cuyo código no esté en el fichero local de códigos vistos.
  - Dado un endpoint de pasada manual que recibe una lista de códigos históricos explícita, cuando se ejecuta, entonces usa esa lista en lugar del fichero local.
  - Dado un endpoint de pasada manual que no recibe lista de códigos históricos, cuando se ejecuta, entonces usa el fichero local de códigos vistos.

### REQ-006 Recorrer el listado paginado con tamaño 75

- **Requisito:** El sistema deberá recorrer todas las páginas del listado del buscador de Emplea Cantabria usando el tamaño de página 75.
- **Criterios de aceptación:**
  - Dado un listado con más de 75 ofertas, cuando se recorre el buscador, entonces se solicitan tantas páginas como sea necesario hasta cubrir el total.
  - Dado cualquier petición al listado, cuando se construye la URL, entonces el parámetro de tamaño de página es 75.
  - Dado un listado vacío, cuando se recorre el buscador, entonces se detecta la condición y se finaliza la fase de listado sin lanzar excepción.

### REQ-007 Identificar ofertas nuevas por código no visto

- **Requisito:** El sistema deberá identificar como oferta nueva cualquier código de oferta del listado que no esté presente en la lista de códigos ya vistos aplicable.
- **Criterios de aceptación:**
  - Dada una lista de códigos ya vistos, cuando el listado contiene códigos ausentes de esa lista, entonces esos códigos se marcan como nuevos.
  - Dada una lista de códigos ya vistos, cuando el listado solo contiene códigos presentes en la lista, entonces no se marca ninguna oferta como nueva y no se solicitan fichas.

### REQ-008 Extraer campos de la ficha

- **Requisito:** Para cada oferta nueva, el sistema deberá descargar su ficha y extraer los campos que publica: número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto. Los campos `sector`, `nivel` y `contrato` se mantienen en el modelo pero se devuelven vacíos, porque la ficha no los publica y no existe otra fuente para obtenerlos (DEC-009).
- **Criterios de aceptación:**
  - Dada una ficha accesible, cuando se parsea, entonces la oferta resultante contiene número de oferta, ocupación, municipio, provincia, fecha de inicio de difusión, fecha de fin de difusión, texto libre y contacto.
  - Dada una ficha accesible, cuando se parsea, entonces `sector`, `nivel` y `contrato` quedan vacíos y no se inventa ningún valor para ellos.
  - Dado el resultado de una oferta parseada, cuando se revisan los campos `sector`, `nivel` y `contrato`, entonces su valor es vacío o nulo y no se ha inferido del texto libre ni de ninguna otra fuente.

### REQ-009 Reintentar fichas fallidas

- **Requisito:** Si la descarga o el parseo de una ficha falla, el sistema deberá reintentarla una vez dentro de la misma pasada, respetando siempre la pausa de cortesía, y no marcará su código como visto hasta que la ficha se parsee correctamente.
- **Criterios de aceptación:**
  - Dada una ficha que falla en su primera solicitud, cuando se reintenta tras la pausa de 10 s, entonces se procesa de nuevo como parte de la misma pasada.
  - Dada una ficha que falla también en el reintento, cuando finaliza la pasada, entonces se incluye en el resultado como fallo persistente y su código no se añade al fichero local de códigos vistos.
  - Dado que una ficha falló en una pasada anterior, cuando comienza una nueva pasada, entonces se vuelve a solicitar esa ficha como si fuera nueva si su código sigue apareciendo en el listado.

### REQ-010 Guardar HTML de fichas fallidas

- **Requisito:** Si el parseo de una ficha falla, el sistema deberá conservar el HTML original en el sistema de archivos local.
- **Criterios de aceptación:**
  - Dada una ficha cuyo parseo falla, cuando finaliza el intento, entonces existe un fichero HTML con el contenido recibido del portal.
  - Dado el directorio de fichas fallidas, cuando se lista, entonces cada fichero sigue el formato `data/failed_htmls/<codigo_oferta>_<yyyy-mm-dd>.html`.
  - Dada una ficha parseada correctamente, cuando finaliza el procesamiento, entonces no se conserva su HTML original.

### REQ-011 Limpiar HTML fallido caducado

- **Requisito:** El sistema deberá eliminar los HTML originales de fichas fallidas que tengan más de 7 días de antigüedad.
- **Criterios de aceptación:**
  - Dado un fichero HTML de ficha fallida con más de 7 días, cuando se ejecuta la limpieza diaria, entonces el fichero se elimina.
  - Dado un fichero HTML de ficha fallida con 7 días o menos, cuando se ejecuta la limpieza diaria, entonces el fichero permanece.

### REQ-012 Manejar fallos del portal y del listado

- **Requisito:** Si el portal no responde, el listado cambia de estructura, una página a medio recorrer falla o el listado está vacío, el sistema deberá informar la situación en el resultado sin generar una excepción no controlada.
- **Criterios de aceptación:**
  - Dado que el portal devuelve un error HTTP o no responde, cuando se intenta la pasada, entonces el resultado indica el fallo global y no se devuelven ofertas como si la pasada hubiera tenido éxito.
  - Dado que el HTML del listado ha cambiado y no se reconoce la estructura esperada, cuando se intenta recorrerlo, entonces el resultado indica un fallo de parseo del listado.
  - Dado que una página intermedia del listado falla, cuando se intenta continuar, entonces se detiene el recorrido y se informa del punto alcanzado.
  - Dado un listado vacío válido, cuando se procesa, entonces se devuelve un resultado vacío sin marcar ofertas previas como cerradas.

### REQ-013 Devolver resultado estructurado de la pasada

- **Requisito:** El sistema deberá devolver el resultado de cada pasada en una estructura JSON que incluya metadatos de la ejecución, los errores por fase y por oferta, y la lista de ofertas nuevas parseadas.
- **Criterios de aceptación:**
  - Dada una pasada completada, cuando se consulta el resultado, entonces se incluyen el timestamp, la comunidad (Cantabria), el total de ofertas encontradas en el listado, los errores global y por oferta, y las ofertas nuevas parseadas.
  - Dado el resultado de una pasada, cuando se revisa, entonces no contiene persistencia en SQLite ni escritura en base de datos por parte de `api-buscador`.

### REQ-014 Disparar pasada manual

- **Requisito:** El sistema deberá exponer un endpoint que permita lanzar una pasada de forma manual, aceptando opcionalmente una lista de códigos históricos y usando `data/seen_codes.json` cuando no se proporcione.
- **Criterios de aceptación:**
  - Dado un endpoint de pasada manual, cuando se invoca sin lista de códigos históricos, entonces la pasada usa el fichero local `data/seen_codes.json` para filtrar ofertas nuevas.
  - Dado un endpoint de pasada manual, cuando se invoca con una lista de códigos históricos explícita, entonces la pasada usa esa lista en lugar del fichero local.
  - Dada una pasada manual completada, cuando se recibe la respuesta, entonces su estructura JSON es la misma que la definida en REQ-013.
  - Dada una pasada manual en curso, cuando se invoca otra pasada manual, entonces se aplica la misma prevención de solapamiento que en REQ-003.

### REQ-015 Consultar estado de la última pasada

- **Requisito:** El sistema deberá exponer un endpoint que devuelva el estado de la última pasada, indicando si hay una pasada en curso, los datos de la última ejecución, un resumen de su resultado y los errores registrados.
- **Criterios de aceptación:**
  - Dado que no hay ninguna pasada en curso, cuando se consulta el endpoint de estado, entonces indica explícitamente que no hay pasada en curso y muestra los datos de la última pasada finalizada.
  - Dado que hay una pasada en curso, cuando se consulta el endpoint de estado, entonces indica explícitamente que hay una pasada en curso, la hora de inicio y el progreso disponible.
  - Dado el resultado del endpoint de estado, cuando se revisa, entonces incluye un resumen de la última ejecución (timestamp, total de ofertas en listado, ofertas nuevas, errores global y por oferta).

## Requisitos no funcionales

### NFR-001 User-Agent identificable

- **Requisito:** El sistema deberá usar un User-Agent que identifique claramente a la aplicación y proporcione un medio de contacto o enlace.
- **Criterios de aceptación:**
  - Dada una petición HTTP saliente, cuando se inspecciona la cabecera `User-Agent`, entonces contiene el nombre del proyecto y una referencia de contacto (por ejemplo, URL del repositorio o correo).

### NFR-002 Frecuencia máxima de peticiones

- **Requisito:** El sistema deberá respetar un intervalo mínimo de 10 segundos entre peticiones consecutivas al portal de Emplea Cantabria.
- **Criterios de aceptación:**
  - Dado un registro de timestamps de peticiones salientes, cuando se comprueba el intervalo entre dos peticiones consecutivas, entonces dicho intervalo es igual o mayor a 10 segundos.

### NFR-003 Sin autenticación

- **Requisito:** La API de esta feature no deberá requerir autenticación.
- **Criterios de aceptación:**
  - Dado un cliente que invoca cualquier endpoint de la API, cuando no incluye credenciales, entonces la API responde sin exigir autenticación.

### NFR-004 Tamaño de página fijo

- **Requisito:** El sistema deberá usar siempre el tamaño de página 75 en las peticiones al listado del buscador.
- **Criterios de aceptación:**
  - Dada cualquier petición al listado del buscador, cuando se verifica el parámetro de paginación, entonces el valor es 75.

### NFR-005 Frecuencia de pasadas automáticas por defecto

- **Requisito:** El sistema deberá ejecutar como máximo una pasada automática por día con la configuración por defecto.
- **Criterios de aceptación:**
  - Dada una API con la configuración por defecto, cuando transcurren 24 horas completas, entonces se lanza exactamente una pasada automática.

## Supuestos

### SUP-001 Configuración por hora del día

- **Tipo:** decisional
- **Descripción:** El horario de la pasada automática se configura como una única hora entera entre 0 y 23. El valor por defecto es 1 (01:00). No se admiten listas de horas, minutos, fracciones de hora ni expresiones cron completas.
- **Impacto:** REQ-001, REQ-002, REQ-003, NFR-005.
- **Estado:** validado

### SUP-002 Disparo manual y estado de la última pasada

- **Tipo:** decisional
- **Descripción:** Además de la ejecución automática, la API expone un endpoint para lanzar una pasada manualmente y otro para consultar el estado de la última pasada. El endpoint manual acepta una lista opcional de códigos históricos; si no se envía, usa `data/seen_codes.json`. La respuesta del manual sigue la misma estructura JSON que la pasada automática.
- **Impacto:** REQ-014, REQ-015.
- **Estado:** validado

### SUP-003 Alcance Cantabria

- **Tipo:** contextual
- **Descripción:** Esta feature se limita a Cantabria según PDEC-017. El identificador de comunidad y provincia viaja en el resultado para facilitar futuras ampliaciones, pero el comportamiento no se adapta a otras fuentes.
- **Impacto:** REQ-006, REQ-008, REQ-013.
- **Estado:** validado

### SUP-004 Fichero local mínimo de códigos vistos

- **Tipo:** decisional
- **Descripción:** `api-buscador` conserva un único fichero local (`data/seen_codes.json` o nombre equivalente) con los códigos de oferta cuya ficha se ha parseado correctamente. El cron interno lo lee para filtrar ofertas nuevas y lo actualiza tras cada pasada añadiendo solo los códigos de las fichas parseadas correctamente. Los códigos de fichas fallidas no se añaden. Este es el único estado de la feature; no se usa SQLite ni se consulta `api-persistencia`.
- **Impacto:** REQ-004, REQ-005, REQ-007, REQ-009, REQ-013.
- **Estado:** validado

### SUP-005 Directorio de HTML fallidos

- **Tipo:** decisional
- **Descripción:** Los HTML de fichas fallidas se guardan en el sistema de archivos local bajo `data/failed_htmls/<codigo_oferta>_<yyyy-mm-dd>.html`. Un proceso diario elimina los ficheros con más de 7 días.
- **Impacto:** REQ-010, REQ-011.
- **Estado:** validado

### SUP-006 Campos no publicados por la ficha (DEC-009)

- **Tipo:** decisional
- **Descripción:** La ficha de oferta de Emplea Cantabria no publica los campos `sector`, `nivel` ni `contrato`, y no existe otra fuente fiable para obtenerlos. Estos campos se mantienen en el modelo de datos pero siempre se devuelven vacíos. Evidencia: muestra `ficha_062026003633.html` en `docs/contracts/html/empleacantabria/` y decisión DEC-009 del 18/11/2026.
- **Impacto:** REQ-008.
- **Estado:** validado

## Preguntas abiertas

Ninguna.
