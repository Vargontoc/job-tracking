# Contrato HTML: buscador de Emplea Cantabria

Muestras **reducidas** del portal real (`https://empleacantabria.es`), capturadas el 18/11/2026. Conservan etiquetas, clases, ids y valores representativos; se ha eliminado el ruido de Liferay (navegación, CSS, JS y filas repetidas) para que un agente pueda leerlas completas con poco coste. No son copias byte a byte.

| Fichero | Qué representa |
|---|---|
| `listado_pagina_1.html` | Listado con resultados y enlace a la página 2. Conserva 3 de las 75 filas. |
| `listado_pagina_2.html` | Última página (`76 - 93 de 93`). Conserva 3 de las 18 filas. |
| `listado_vacio.html` | Búsqueda sin resultados. |
| `ficha_062026003633.html` | Ficha de oferta. |

## Listado

- Tabla: `table.table` → `tbody.table-data` → `tr` → 4 `td` en orden: **código**, **descripción**, **municipio**, **fecha de inicio** (`dd/mm/aaaa`).
- Código: `a[href*="/ofertas-cantabria/-/oferta/"]`; su texto son 12 dígitos que deben conservarse como texto.
- Total y rango: `small.search-results` → `Mostrando el intervalo 1 - 75 de 93 resultados.` No hay otro campo de total.
- Paginación: `ul.lfr-pagination-buttons` con `_..._delta=75` y `_..._cur=N` (1-based). Sin filtros, el listado y las fichas no requieren cookies.
- Sin resultados: `.lfr-search-container` lleva la clase `hide`; el aviso `#..._dtosSearchContainerEmptyResultsMessage` (`div.alert.alert-info`) no lleva `hide` y contiene `No hay resultados`. No aparece `small.search-results`.

## Ficha

- Datos en `div.buscador div.form`, como `input[readonly]` con el valor en el atributo `value`. El `id` lleva delante el namespace del portlet; seleccionar por sufijo:
  - `input[id$="_numeroOferta"]`
  - `input[id$="_ocupacion"]`
  - `input[id$="_municipio"]`
  - `input[id$="_provincia"]`
  - `input[id$="_fechaInicioDifusion"]`
  - `input[id$="_fechaFinDifusion"]`
- `Texto libre` y `Contacto` están en el `div` que sigue a `label.dAdicionales` y `label.dContacto`; contienen espacios y saltos de línea que hay que normalizar.
- Fechas en `dd/mm/aaaa`. Municipio y provincia en mayúsculas.

## Avisos

- **Decisión (18/11/2026):** `sector`, `nivel` y `contrato` se mantienen en el modelo como campos vacíos porque la ficha no los publica y no hay otra fuente; no se inventan valores (DEC-009).
- `robots.txt` declara `Crawl-delay: 10` y no bloquea estas rutas; coincide con la pausa de 10 s del diseño.
- Respuestas y ficheros en UTF-8.
- Para recapturar una página completa: `curl -sSL -A "<user-agent>" "https://empleacantabria.es/ofertas-cantabria"`; para una ficha, `https://empleacantabria.es/ofertas-cantabria/-/oferta/<codigo>`.
