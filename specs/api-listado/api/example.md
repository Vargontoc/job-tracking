# Ejemplos de uso: api-listado

## Componente: `listado-filter-builder` (`source/api/listado/filter_builder.py`)

Constructor de la cláusula `WHERE` del listado. `construir(filtros)` traduce los filtros recibidos a una `ClausulaFiltros` con cuatro datos: `where` (condiciones unidas por `AND`, sin la palabra clave `WHERE`, que añade quien compone la consulta), `parametros` (valores posicionales de los marcadores `?`, en el mismo orden), `texto` y `municipio` (los filtros textuales que se aplican en memoria). El estado entra siempre como primera condición (`estado = ?` con `vigente`; `estado IN (?, ?)` con `vigente` y `cerrada` si `incluir_cerradas` está activo) y `sin_ficha` no aparece nunca. El `sector` genera su condición aunque hoy el campo se almacene vacío. El rango de fechas compara la expresión ISO de `listado-date-parser` con valores `aaaa-mm-dd` convertidos desde `dd/mm/aaaa`; un rango invertido se valida antes, en el parser. El texto libre y el municipio no entran en SQL porque el `lower()` de SQLite no cubre las tildes: se informan para que el repositorio los aplique en memoria. No hay ninguna condición sobre `oficina`, y ningún valor se concatena en el texto de la consulta.

## Ejemplo: construir la cláusula con visibilidad por defecto

```python
from source.api.listado.filter_builder import construir

# Sin filtros del cliente solo queda la visibilidad por defecto (REQ-006).
clausula = construir({})

print(clausula.where)         # "estado = ?"
print(clausula.parametros)    # ["vigente"]
print(clausula.filtrado_en_memoria)  # False
```

## Ejemplo: combinar estado, sector y rango de fechas

```python
from source.api.listado.filter_builder import construir

clausula = construir(
    {
        "sector": "informatica",
        "fecha_desde": "10/11/2026",
        "fecha_hasta": "20/11/2026",
        "incluir_cerradas": True,
    }
)

# Una condición por filtro, todas unidas por AND.
print(clausula.where)
# estado IN (?, ?) AND sector = ? AND CASE WHEN fecha_inicio_difusion GLOB ...
# >= ? AND CASE WHEN fecha_inicio_difusion GLOB ... <= ?

# Los valores viajan como parámetros, en el orden de los marcadores.
print(clausula.parametros)
# ["vigente", "cerrada", "informatica", "2026-11-10", "2026-11-20"]

# Así se compone la consulta sin concatenar ningún valor (REQ-010).
consulta = f"SELECT * FROM ofertas WHERE {clausula.where}"
print(consulta)
```

## Ejemplo: filtrar por texto libre y municipio en memoria

```python
from source.api.listado.filter_builder import construir
from source.api.listado.text_normalizer import coincide, contiene

clausula = construir({"texto": "tecnico", "municipio": "santander"})

# Ni el texto ni el municipio aparecen en el SQL (DEC-002).
print(clausula.where)            # "estado = ?"
print(clausula.filtrado_en_memoria)  # True

# El repositorio aplica los filtros textuales sobre cada fila candidata.
oferta = {"ocupacion": "Técnico de sistemas", "municipio": "SANTANDER"}
pasa_texto = (
    contiene(oferta["ocupacion"], "tecnico")
    or contiene(oferta["municipio"], clausula.texto)
)
pasa_municipio = coincide(oferta["municipio"], clausula.municipio)
print(pasa_texto, pasa_municipio)  # True True
```

## Ejemplo: un valor con comillas viaja como parámetro

```python
from source.api.listado.filter_builder import construir

clausula = construir({"sector": "'; DROP TABLE ofertas; --"})

# El SQL no cambia de estructura y el valor queda en los parámetros.
print(clausula.where)         # "estado = ? AND sector = ?"
print(clausula.parametros)    # ["vigente", "'; DROP TABLE ofertas; --"]
```

## Componente: `listado-query-repository` (`source/api/listado/repository.py`)

Ejecuta la consulta del listado sobre el adaptador de solo lectura y devuelve un `ResultadoListado` con las ofertas de la página, el `total`, la `pagina`, el `tamano_pagina` y los `filtros_aplicados`. Sin filtros textuales, el total se calcula con `COUNT` en SQL y la página se recupera con `LIMIT ? OFFSET ?`. Cuando hay filtro de texto libre o de municipio, SQL no pagina: devuelve todas las filas candidatas ya ordenadas por fecha de inicio descendente y código ascendente, y el repositorio normaliza y filtra en memoria; el `total` es el número de filas que quedan después de ese filtrado y la página se recorta con `[offset:offset+tamano]` (DEC-002). Cada oferta incluye `comunidad`, `codigo`, `ocupacion`, `municipio`, `provincia`, `sector`, `fecha_inicio_difusion`, `fecha_fin_difusion`, `estado`, `contacto` y `texto_libre`, con la cadena vacía en los campos purgados (REQ-008, ALT-006). El repositorio es de solo lectura: reutiliza `AdaptadorLecturaListado` (`mode=ro`) y nunca escribe.

## Ejemplo: consultar una página sin filtros textuales

```python
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado

adaptador = AdaptadorLecturaListado("data/job_emcan.db")
repositorio = RepositorioListado(adaptador)

# Por defecto solo aparecen las ofertas `vigente`; el total lo cuenta SQL.
resultado = repositorio.consultar({}, offset=0, tamano_pagina=20)

print(resultado.total)          # p. ej. 42
print(resultado.pagina)         # 1
print(resultado.tamano_pagina)  # 20
for oferta in resultado.items:
    print(oferta.codigo, oferta.ocupacion, oferta.fecha_inicio_difusion)
```

## Ejemplo: filtrar por texto libre con tildes y paginar el conjunto filtrado

```python
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado

repositorio = RepositorioListado(AdaptadorLecturaListado("data/job_emcan.db"))

resultado = repositorio.consultar(
    {"texto": "tecnico", "fecha_desde": "10/11/2026"},
    offset=0,
    tamano_pagina=10,
)

# El texto se aplica en memoria: el total es el del conjunto ya filtrado.
print(resultado.total)
print(resultado.filtros_aplicados)
# {"texto": "tecnico", "fecha_desde": "10/11/2026"}

for oferta in resultado.items:
    print(oferta.codigo, oferta.ocupacion, oferta.municipio, oferta.estado)
```

## Ejemplo: página fuera del total y de solo lectura

```python
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado

repositorio = RepositorioListado(AdaptadorLecturaListado("data/job_emcan.db"))

# Un offset válido mayor o igual que el total devuelve una lista vacía con el
# total real, sin error (ALT-003).
resultado = repositorio.consultar({}, offset=1000, tamano_pagina=20)
print(resultado.items)  # []
print(resultado.total)  # el número real de coincidencias

# Ninguna consulta modifica el SQLite de api-persistencia (REQ-010).
```

## Componente: `listado-api` (`source/api/listado/routes.py`)

Endpoints `GET /listado` y `GET /listado/filtros` del router `APIRouter(prefix="/listado", tags=["listado"])`. Acepta los filtros opcionales `texto`, `sector`, `municipio`, `fecha_desde`, `fecha_hasta`, `incluir_cerradas`, `offset` y `tamano_pagina`, y devuelve la lista de ofertas con los once campos de REQ-008 más los metadatos `total`, `pagina`, `tamano_pagina` y `filtros_aplicados`. Antes de tocar la base de datos valida las fechas con `listado-date-parser` (formato `dd/mm/aaaa` y rango no invertido), exige `offset` no negativo y `tamano_pagina` mayor que cero, y recorta un tamaño superior al máximo de la configuración (`100` por defecto). Un parámetro inválido devuelve `400` identificando el parámetro; un fallo de acceso a los datos, `503` sin detalles internos. La configuración y el repositorio se leen de `app_state` (`config_listado` y `repositorio_listado`), donde los deja el arranque de la aplicación; si faltan, responde `503`. `GET /listado/filtros` devuelve los seis filtros que admite `GET /listado` (`texto`, `sector`, `municipio`, `fecha_desde`, `fecha_hasta` e `incluir_cerradas`), cada uno con su nombre, tipo, formato y ejemplo; es una respuesta estática: no consulta la base de datos ni depende de `app_state`, anuncia `sector` aunque hoy no haya datos y no anuncia `oficina` porque el campo no existe en el esquema. Ninguno de los dos endpoints exige autenticación. Los modelos Pydantic son `SolicitudListado` (entrada ya validada), `OfertaListadoRespuesta`, `RespuestaListado`, `FiltroDisponible` y `RespuestaFiltrosDisponibles` (salida).

## Ejemplo: consultar el listado con filtros y paginación

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.listado.config import ConfigListado
from source.api.listado.read_adapter import AdaptadorLecturaListado
from source.api.listado.repository import RepositorioListado
from source.api.listado.routes import router
from source.api.main import app_state

# El arranque de la aplicación deja la configuración y el repositorio en el
# estado compartido; aquí se inyectan a mano para el ejemplo.
app_state["config_listado"] = ConfigListado(ruta_bd="data/job_emcan.db")
app_state["repositorio_listado"] = RepositorioListado(
    AdaptadorLecturaListado("data/job_emcan.db")
)

app = FastAPI()
app.include_router(router)
cliente = TestClient(app)

respuesta = cliente.get(
    "/listado",
    params={
        "municipio": "santander",
        "fecha_desde": "10/11/2026",
        "fecha_hasta": "20/11/2026",
        "tamano_pagina": 10,
        "offset": 20,
    },
)
print(respuesta.status_code)  # 200
print(respuesta.json())
```

La respuesta tiene esta forma:

```json
{
  "items": [
    {
      "comunidad": "Cantabria",
      "codigo": "061234567890",
      "ocupacion": "Técnico de sistemas",
      "municipio": "SANTANDER",
      "provincia": "Cantabria",
      "sector": "",
      "fecha_inicio_difusion": "15/11/2026",
      "fecha_fin_difusion": "31/12/2026",
      "estado": "vigente",
      "contacto": "rrhh@test.com",
      "texto_libre": "Buscamos desarrollador Python"
    }
  ],
  "total": 21,
  "pagina": 3,
  "tamano_pagina": 10,
  "filtros_aplicados": {
    "municipio": "santander",
    "fecha_desde": "10/11/2026",
    "fecha_hasta": "20/11/2026"
  }
}
```

## Ejemplo: tamaño de página fuera del máximo

```python
# El tamaño se recorta al máximo configurado (100 por defecto); no es un error.
datos = cliente.get("/listado", params={"tamano_pagina": 150}).json()
print(datos["tamano_pagina"])  # 100
```

## Ejemplo: parámetros inválidos y base inaccesible

```python
# Una fecha mal formada se rechaza antes de consultar la base (400).
respuesta = cliente.get("/listado", params={"fecha_desde": "32/13/2026"})
print(respuesta.status_code)  # 400
print(respuesta.json()["detail"])
# "El parámetro 'fecha_desde' debe ser una fecha con formato dd/mm/aaaa; ..."

# Un tamaño de página no positivo también es un 400 que identifica el parámetro.
print(cliente.get("/listado", params={"tamano_pagina": 0}).status_code)  # 400

# Si el SQLite no existe o no tiene la tabla `ofertas`, el error es controlado.
app_state["repositorio_listado"] = RepositorioListado(
    AdaptadorLecturaListado("data/no_existe.db")
)
respuesta = cliente.get("/listado")
print(respuesta.status_code)  # 503
print(respuesta.json()["detail"])  # "No se puede acceder a los datos del listado."
```

## Ejemplo: consultar los filtros disponibles

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from source.api.listado.routes import router

# La respuesta es estática: no hace falta configurar ni preparar la base de datos.
app = FastAPI()
app.include_router(router)
cliente = TestClient(app)

respuesta = cliente.get("/listado/filtros")
print(respuesta.status_code)  # 200
print(respuesta.json())
```

La respuesta tiene esta forma (seis filtros, cada uno con tipo, formato y ejemplo):

```json
{
  "filtros": [
    {"nombre": "texto", "tipo": "texto", "formato": "texto libre", "ejemplo": "tecnico"},
    {
      "nombre": "sector",
      "tipo": "texto",
      "formato": "texto (igualdad exacta)",
      "ejemplo": "Informática"
    },
    {
      "nombre": "municipio",
      "tipo": "texto",
      "formato": "texto (igualdad, sin distinguir mayúsculas ni tildes)",
      "ejemplo": "Santander"
    },
    {"nombre": "fecha_desde", "tipo": "fecha", "formato": "dd/mm/aaaa", "ejemplo": "10/11/2026"},
    {"nombre": "fecha_hasta", "tipo": "fecha", "formato": "dd/mm/aaaa", "ejemplo": "20/11/2026"},
    {
      "nombre": "incluir_cerradas",
      "tipo": "booleano",
      "formato": "true | false",
      "ejemplo": "true"
    }
  ]
}
```

`sector` aparece aunque hoy no haya ofertas con ese valor (REQ-003, ALT-007) y
`oficina` no se anuncia porque el campo no existe en el esquema (SUP-002).

