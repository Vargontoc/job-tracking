# Requisitos: api-listado

Estado: aprobado
Revisión: 2
Verificación: correcta (actualizada tras validación de supuestos)

## Contexto

Esta feature expone la consulta del listado de ofertas para la interfaz futura, cubriendo **FUN-002** (listado filtrable por texto libre, sector, municipio, oficina y fecha, ordenado por fecha descendente) y **FUN-007** (ocultar las ofertas descartadas y cerradas por defecto). El listado es de solo lectura: no crea ni modifica ofertas.

Dado que `api-persistencia` ya está aprobado e implementado, `api-listado` se alimenta del mismo esquema de ofertas documentado en `specs/api-persistencia/design.md`. Algunos filtros que pide FUN-002 no tienen datos hoy: `sector` se almacena siempre vacío (DEC-009), `oficina` no existe en el esquema, y el estado `descartada` pertenece a `api-candidaturas`, que aún no está especificada. Estos puntos se resuelven como decisiones validadas en la sección de supuestos.

## Fuera de alcance

- Interfaz de usuario (`app-interfaz`).
- Exportación a CSV (**FUN-008**).
- Estadísticas (**FUN-009**).
- Puntuación de encaje explicado (**FUN-010**).
- Búsqueda semántica sobre el histórico (**FUN-011**).
- Perfil de búsqueda editable (**FUN-012**).
- Estados de candidatura (`me interesa`, `inscrito`, `entrevista`, `descartada`), notas y recordatorios (`api-candidaturas`).
- Envío de avisos por Telegram o cualquier canal externo.
- Modificación de `api-buscador`, `api-persistencia`, `api-pdf-parser`, `api-historico` o `api-integridad`.
- Persistencia propia: `api-listado` no escribe en base de datos ni en ficheros.

## Requisitos funcionales

### REQ-001 Consultar listado de ofertas con filtros combinables

- **Requisito:** Cuando un cliente solicita el listado de ofertas, el sistema deberá devolver las ofertas que cumplan todos los filtros aplicados de forma conjunta (AND), considerando los valores vacíos como "sin filtro".
- **Criterios de aceptación:**
  - Dado un listado con ofertas de distintos municipios y fechas, cuando se aplica un filtro por municipio, entonces solo se devuelven las ofertas de ese municipio.
  - Dado un listado con ofertas de distintos estados, cuando no se indica filtro de estado, entonces se aplican las reglas por defecto de visibilidad definidas en REQ-006.
  - Dados varios filtros activos simultáneamente, cuando se consulta el listado, entonces solo se devuelven las ofertas que cumplen todos ellos.

### REQ-002 Filtrar por texto libre

- **Requisito:** El sistema deberá permitir filtrar por texto libre sobre los campos `ocupacion`, `municipio` y `texto_libre`, de forma insensible a mayúsculas y, si es viable, a tildes.
- **Criterios de aceptación:**
  - Dada una oferta cuya ocupación contiene "desarrollador", cuando se filtra por texto "desarrollador", entonces la oferta aparece en el resultado.
  - Dada una oferta cuyo municipio contiene "Torrelavega", cuando se filtra por texto "torrelavega", entonces la oferta aparece en el resultado.
  - Dada una oferta cuyo texto_libre contiene "Python", cuando se filtra por texto "python", entonces la oferta aparece en el resultado.
  - Dada una oferta cuyo texto_libre ha sido purgado y está vacío, cuando se filtra por un término que solo aparecía en el texto, entonces la oferta no aparece en el resultado.

### REQ-003 Filtrar por sector

- **Requisito:** El sistema deberá exponer el filtro por sector, aunque hoy el campo `sector` se almacena siempre vacío conforme a DEC-009.
- **Criterios de aceptación:**
  - Dado que ninguna oferta vigente tiene valor en el campo `sector`, cuando se filtra por cualquier sector, entonces el resultado está vacío.
  - Dado que el filtro existe en la API, cuando se consulta la lista de filtros disponibles, entonces `sector` figura como filtro soportado.

### REQ-004 Filtrar por municipio

- **Requisito:** El sistema deberá permitir filtrar por municipio de forma exacta e insensible a mayúsculas.
- **Criterios de aceptación:**
  - Dadas ofertas de "Santander" y "Torrelavega", cuando se filtra por municipio "Santander", entonces solo aparecen las ofertas de Santander.
  - Dado un filtro por municipio en minúsculas, cuando se consulta, entonces coincide con el valor almacenado en mayúsculas.

### REQ-005 Filtrar por rango de fechas

- **Requisito:** El sistema deberá permitir filtrar por rango de fechas (desde y hasta, inclusive) sobre la fecha de inicio de difusión, usando el formato `dd/mm/aaaa`.
- **Criterios de aceptación:**
  - Dadas ofertas con fechas de inicio 01/11/2026, 15/11/2026 y 30/11/2026, cuando se filtra desde 10/11/2026 hasta 20/11/2026, entonces solo aparece la oferta del 15/11/2026.
  - Dado un filtro con solo fecha "desde", cuando se consulta, entonces se incluyen las ofertas con fecha de inicio igual o posterior a ese valor.
  - Dado un filtro con solo fecha "hasta", cuando se consulta, entonces se incluyen las ofertas con fecha de inicio igual o anterior a ese valor.

### REQ-006 Visibilidad por estado

- **Requisito:** El listado deberá mostrar por defecto solo las ofertas en estado `vigente`; deberá existir un parámetro para incluir también las ofertas en estado `cerrada`. Las ofertas en estado `sin_ficha` nunca se mostrarán en el listado.
- **Criterios de aceptación:**
  - Dadas ofertas `vigente`, `cerrada` y `sin_ficha`, cuando se consulta el listado por defecto, entonces solo aparecen las `vigente`.
  - Dadas ofertas `vigente` y `cerrada`, cuando se activa el parámetro para incluir cerradas, entonces aparecen ambas.
  - Dadas ofertas `sin_ficha`, cuando se consulta el listado con cualquier configuración de visibilidad, entonces nunca aparecen.

### REQ-007 Orden y paginación

- **Requisito:** El sistema deberá ordenar el listado por fecha de inicio de difusión descendente; en caso de empate, desempatará por código de oferta ascendente. Además, deberá paginar los resultados usando tamaño de página y desplazamiento (offset).
- **Criterios de aceptación:**
  - Dadas tres ofertas con fechas de inicio 30/11/2026, 15/11/2026 y 20/11/2026, cuando se consulta el listado, entonces aparecen en el orden 30/11/2026, 20/11/2026, 15/11/2026.
  - Dadas dos ofertas con la misma fecha de inicio y códigos `061234567890` y `061234567891`, cuando se consulta el listado, entonces `061234567890` aparece antes.
  - Dado un listado de 50 ofertas y un tamaño de página de 20, cuando se solicita la página 1 (offset 20), entonces se devuelven las ofertas 21 a 40.
  - Dado un listado de 50 ofertas, cuando se solicita una página cuyo offset supera el total, entonces se devuelve una lista vacía.

### REQ-008 Respuesta del listado

- **Requisito:** El sistema deberá devolver, para cada oferta, los campos necesarios para la interfaz: comunidad, código, ocupación, municipio, provincia, sector, fechas de inicio y fin de difusión, estado, contacto y texto libre cuando estén disponibles. Además, deberá incluir metadatos del resultado: total de ofertas que cumplen los filtros, página actual, tamaño de página y filtros aplicados.
- **Criterios de aceptación:**
  - Dado el resultado de una consulta, cuando se revisa una oferta, entonces incluye comunidad, código, ocupación, municipio, provincia, sector, fecha_inicio_difusion, fecha_fin_difusion, estado, contacto y texto_libre.
  - Dada una oferta cuyo texto y contacto han sido purgados, cuando se devuelve en el listado, entonces esos campos aparecen vacíos y el resto de campos se mantienen.
  - Dado el resultado de una consulta, cuando se revisan los metadatos, entonces incluyen total, página, tamaño de página y los filtros aplicados.

### REQ-009 Manejo de parámetros inválidos y ausencia de resultados

- **Requisito:** El sistema deberá detectar y rechazar parámetros inválidos (fecha mal formada, rango invertido, página fuera de rango) y deberá devolver una respuesta clara cuando no haya resultados.
- **Criterios de aceptación:**
  - Dado un filtro con fecha "32/13/2026", cuando se consulta, entonces se devuelve un error indicando que el formato debe ser `dd/mm/aaaa`.
  - Dado un filtro con fecha "desde" posterior a "hasta", cuando se consulta, entonces se devuelve un error indicando que el rango es inválido.
  - Dado un listado vacío para los filtros aplicados, cuando se consulta, entonces se devuelve una lista vacía con total 0 y sin errores.
  - Dada una base de datos inexistente o no inicializada, cuando se consulta el listado, entonces se devuelve un error controlado indicando que no se puede acceder a los datos.

### REQ-010 Sin estado propio y solo lectura

- **Requisito:** El sistema no deberá crear, modificar ni eliminar ofertas; únicamente deberá leer del origen de datos de `api-persistencia`.
- **Criterios de aceptación:**
  - Dada una consulta al listado, cuando finaliza, entonces no se han creado ni modificado registros en la base de datos.
  - Dado el código de la feature, cuando se revisa, entonces no contiene operaciones de escritura sobre ofertas.

## Requisitos no funcionales

### NFR-001 Paginación máxima

- **Requisito:** El sistema no deberá permitir solicitar más de 100 ofertas por página.
- **Criterios de aceptación:**
  - Dada una solicitud con tamaño de página 150, cuando se valida, entonces se rechaza o se limita a 100.
  - Dada una solicitud con tamaño de página 50, cuando se consulta, entonces se respeta el valor solicitado.

### NFR-002 Tiempo de respuesta del listado

- **Requisito:** El sistema deberá devolver el listado filtrado en menos de 2 segundos para hasta 500 ofertas vigentes.
- **Criterios de aceptación:**
  - Dada una base con 500 ofertas vigentes, cuando se consulta el listado sin filtros, entonces la respuesta llega en menos de 2 segundos.

### NFR-003 Normalización de texto

- **Requisito:** La búsqueda por texto libre y por municipio deberá ser insensible a mayúsculas, minúsculas y, si es viable, a tildes.
- **Criterios de aceptación:**
  - Dada una oferta con ocupación "Técnico", cuando se filtra por "tecnico", entonces la oferta aparece en el resultado.
  - Dada una oferta con municipio "Santander", cuando se filtra por "santander", entonces la oferta aparece en el resultado.

## Supuestos

### SUP-001 Filtrar por sector sin datos disponibles

- **Tipo:** decisional
- **Descripción:** Se mantiene el filtro por `sector` en la API de listado para alinear la API con FUN-002. Hoy el campo `sector` se almacena siempre vacío (DEC-009), por lo que cualquier filtro por sector devolverá un resultado vacío hasta que exista una fuente que persista el sector (por ejemplo, desde el PDF de difusión). La alternativa descartada es excluir el filtro de esta feature y añadirlo cuando el dato esté disponible.
- **Impacto:** REQ-003, REQ-008. FUN-002 queda cubierta en la API de forma parcial: el filtro existe, pero no aporta valor funcional hasta que se persista el dato.
- **Estado:** validado

### SUP-002 Excluir filtro por oficina

- **Tipo:** decisional
- **Descripción:** Se excluye el filtro por `oficina` de esta feature. El dato no existe en el esquema de `api-persistencia` ni en el modelo `OfertaBuscador`; solo aparece en el PDF de difusión, que hoy no se persiste. La alternativa descartada es añadir el campo `oficina` al esquema y a la ingesta, lo que obligaría a revisar `api-persistencia` y `api-buscador`, features aprobadas que no se modifican. Se cubrirá cuando la oficina se persista como campo de la oferta.
- **Impacto:** REQ-001, REQ-008. FUN-002 queda cubierta parcialmente: se soportan texto libre, sector, municipio y fecha, pero no oficina.
- **Estado:** validado

### SUP-003 Ocultar descartadas preparando api-candidaturas

- **Tipo:** decisional
- **Descripción:** Por defecto se ocultan las ofertas `cerrada` y las `sin_ficha` nunca se muestran. Hoy no existe el estado "descartada": `api-candidaturas` aún no está especificada y el esquema solo tiene el booleano reservado `interesada` (que significa "me interesa", no "descartada"). El parámetro de visibilidad queda preparado para que, cuando exista `api-candidaturas`, se pueda añadir la opción de ocultar también las ofertas marcadas como `descartada`.
- **Impacto:** REQ-006, REQ-010. FUN-007 queda cubierto parcialmente: se ocultan las cerradas; la ocultación de descartadas depende de `api-candidaturas`.
- **Estado:** validado

### SUP-004 Fecha de referencia para filtro y orden

- **Tipo:** decisional
- **Descripción:** El filtro de rango de fechas y el orden descendente se aplican sobre `fecha_inicio_difusion`. El desempate se resuelve por `codigo` ascendente. Las ofertas sin `fecha_inicio_difusion` informada aparecen al final del listado y quedan fuera de los filtros de fecha explícitos. La alternativa descartada es usar `fecha_fin_difusion` como referencia principal.
- **Impacto:** REQ-005, REQ-007.
- **Estado:** validado

### SUP-005 Lectura sobre el origen de datos de api-persistencia

- **Tipo:** contextual
- **Descripción:** `api-listado` lee el origen de datos de `api-persistencia` (`data/job_emcan.db` por defecto) sin escribir en él; la técnica concreta (endpoint de `persistencia-api`, conexión de solo lectura `mode=ro` u otra) se decide en diseño. Este supuesto no altera el comportamiento exigido por REQ-010.
- **Impacto:** REQ-001, REQ-010.
- **Estado:** validado

## Avisos

- **Cobertura parcial de FUN-002:** la API de listado soporta filtros por texto libre, sector, municipio y rango de fechas. El filtro por `sector` existe pero es inerte mientras el campo se almacene vacío (DEC-009); empezará a devolver resultados cuando una feature futura persista el sector. El filtro por `oficina` queda fuera del alcance porque el dato no existe en el esquema de `api-persistencia` ni en el modelo de la ficha del buscador.
- **Cobertura parcial de FUN-007:** el listado oculta por defecto las ofertas `cerrada` y nunca muestra las `sin_ficha`. La ocultación de ofertas `descartada` queda pendiente de `api-candidaturas`; el parámetro de visibilidad se ha diseñado para admitir esa ampliación sin cambiar la interfaz actual.
- **Técnica de lectura:** `api-listado` lee del origen de datos de `api-persistencia` (`data/job_emcan.db`) sin escribir en él. La elección entre consumir `persistencia-api` o abrir una conexión de solo lectura (`mode=ro`) se deja para la fase de diseño.

## Preguntas abiertas

Ninguna.

## Trazabilidad

| Requisito / Supuesto | Funcionalidad de producto | Decisión de producto |
|---|---|---|
| REQ-001 | FUN-002 | PDEC-013 |
| REQ-002 | FUN-002 | PDEC-016 |
| REQ-003 | FUN-002 | DEC-009, SUP-001 |
| REQ-004 | FUN-002 | - |
| REQ-005 | FUN-002 | SUP-004 |
| REQ-006 | FUN-007 | PDEC-014, SUP-003 |
| REQ-007 | FUN-002 | SUP-004 |
| REQ-008 | FUN-002 | PDEC-016 |
| REQ-009 | FUN-002 | - |
| REQ-010 | FUN-007 | PDEC-003 |
| NFR-001 | FUN-002 | - |
| NFR-002 | FUN-002 | - |
| NFR-003 | FUN-002 | - |
| SUP-001 | FUN-002 | DEC-009 |
| SUP-002 | FUN-002 | DEC-009 |
| SUP-003 | FUN-007 | PDEC-016 |
| SUP-004 | FUN-002 | - |
| SUP-005 | FUN-002 | PDEC-003 |
