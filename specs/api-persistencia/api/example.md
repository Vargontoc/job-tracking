# Ejemplos de uso: migrations

## Componente: `schema-migrator` (`source/api/persistencia/migrations.py`)

Migrador del esquema SQLite. Expone la función `migrar(conexion)` que aplica las migraciones numeradas de la lista `MIGRACIONES` sobre una conexión ya abierta, creando y manteniendo la tabla `schema_version`.

## Ejemplo: aplicar migraciones al arrancar

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar, ErrorMigracion

# Abrir la conexión (crea el fichero y el directorio si faltan).
conexion = abrir_conexion("data/job_emcan.db")
try:
    version = migrar(conexion)
    print(f"Esquema en versión {version}")
except ErrorMigracion as exc:
    print(f"No se pudo migrar: {exc}")
    raise
finally:
    conexion.close()
```

## Ejemplo: consultar la versión tras migrar

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar

conexion = abrir_conexion("data/job_emcan.db")
version = migrar(conexion)

fila = conexion.execute(
    "SELECT version, applied_at FROM schema_version ORDER BY version DESC LIMIT 1"
).fetchone()
print(f"Última migración: versión {fila[0]}, aplicada en {fila[1]}")
conexion.close()
```

## Ejemplo: gestionar versión futura

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar, ErrorMigracion

conexion = abrir_conexion("data/job_emcan.db")
try:
    migrar(conexion)
except ErrorMigracion as exc:
    # La base de datos está en una versión superior a las migraciones disponibles.
    print(f"Abortando arranque: {exc}")
    conexion.close()
    raise
```

## Componente: `ofertas-repository` (`source/api/persistencia/repository.py`)

Repositorio de ofertas con upsert por clave natural `(comunidad, codigo)`, consulta, listado de vigentes y lista de códigos vistos.

## Ejemplo: listar ofertas vigentes

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)

vigentes = repo.listar_vigentes()
for oferta in vigentes:
    print(f"{oferta.codigo} - {oferta.ocupacion} ({oferta.municipio}) "
          f"hasta {oferta.fecha_fin_difusion}")

conexion.close()
```

## Ejemplo: obtener códigos vistos de una comunidad

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)

codigos_vistos = repo.listar_codigos_vistos("Cantabria")
print(f"Códigos vistos: {len(codigos_vistos)}")

# Un código ausente de la lista se considera oferta nueva
codigo_nuevo = "062026099999"
if codigo_nuevo not in codigos_vistos:
    print(f"El código {codigo_nuevo} es una oferta nueva")

conexion.close()
```

## Componente: `seen-codes-importer` (`source/api/persistencia/importer.py`)

Importador idempotente de códigos vistos desde `data/seen_codes.json`. Expone la función `importar_codigos_vistos(conexion, ruta_json)` que lee el JSON como lista plana de códigos y crea un registro con comunidad `Cantabria`, estado `sin_ficha` y el resto de campos vacíos por cada código que no exista en la base de datos. No modifica el fichero de origen.

## Ejemplo: importar códigos vistos al arrancar

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.importer import importar_codigos_vistos

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)

resultado = importar_codigos_vistos(conexion, "data/seen_codes.json")
print(
    f"Importación completada: {resultado.importados} importados, "
    f"{resultado.existentes} ya existentes"
)

conexion.close()
```

## Ejemplo: importación idempotente

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.importer import importar_codigos_vistos

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)

# Primera importación: crea los registros nuevos
r1 = importar_codigos_vistos(conexion, "data/seen_codes.json")
print(f"Primera vez: {r1.importados} importados, {r1.existentes} existentes")

# Segunda importación: no crea duplicados, todos son "existentes"
r2 = importar_codigos_vistos(conexion, "data/seen_codes.json")
print(f"Segunda vez: {r2.importados} importados, {r2.existentes} existentes")

conexion.close()
```

## Ejemplo: fichero ausente o malformado

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.importer import importar_codigos_vistos

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)

# Si el fichero no existe o está malformado, se registra y continúa sin fallar
resultado = importar_codigos_vistos(conexion, "data/seen_codes.json")
if resultado.importados == 0 and resultado.existentes == 0:
    print("No se importaron códigos (fichero ausente, vacío o malformado)")

conexion.close()
```

## Componente: `buscador-client` (`source/api/persistencia/client.py`)

Cliente HTTP que consulta `GET /buscador/status` y devuelve el estado publicado en memoria por el rastreador: `in_progress`, `progreso` y `ultima_pasada` con `timestamp`, `comunidad`, `total_listado`, `error_global`, `errores_por_oferta` y `ofertas_nuevas`. No lanza peticiones de pasada ni descarga fichas. Ante errores HTTP o de red devuelve un resultado controlado sin lanzar excepciones.

## Ejemplo: consultar el estado del buscador

```python
from source.api.persistencia.client import ClienteBuscador

buscador = ClienteBuscador("http://localhost:8000")
resultado = buscador.consultar_estado()

if resultado.error:
    print(f"No se pudo consultar el buscador: {resultado.error}")
else:
    estado = resultado.estado
    print(f"Pasada en curso: {estado.in_progress}")

    if estado.ultima_pasada is None:
        print("No hay última pasada disponible (el buscador se ha reiniciado)")
    else:
        ultima = estado.ultima_pasada
        print(f"Última pasada: {ultima.timestamp}")
        print(f"Ofertas en el listado: {ultima.total_listado}")
        print(f"Ofertas nuevas: {len(ultima.ofertas_nuevas)}")
        if ultima.error_global:
            print(f"Error global: {ultima.error_global}")
```

## Ejemplo: detectar error global o última pasada nula

```python
from source.api.persistencia.client import ClienteBuscador

buscador = ClienteBuscador("http://localhost:8000")
resultado = buscador.consultar_estado()

if resultado.error:
    # Error HTTP o de red: no se puede confiar en el estado
    print(f"Buscador no accesible: {resultado.error}")
elif resultado.estado.ultima_pasada is None:
    # El buscador se ha reiniciado y aún no ha completado una pasada
    print("Esperando a que el buscador complete su primera pasada")
elif resultado.estado.ultima_pasada.error_global:
    # La pasada terminó con error: no hay ofertas fiables
    print(f"Pasada con error: {resultado.estado.ultima_pasada.error_global}")
else:
    # Estado válido con ofertas nuevas disponibles
    nuevas = resultado.estado.ultima_pasada.ofertas_nuevas
    print(f"Ofertas nuevas disponibles: {len(nuevas)}")
```

## Componente: `ingestion-task` (`source/api/persistencia/ingestion.py`)

Tarea periódica que consulta `GET /buscador/status` mediante el cliente, compara el `timestamp` de `ultima_pasada` con el último importado almacenado en `ingesta_log`, y solo cuando difiere envía cada oferta de `ofertas_nuevas` al repositorio para su persistencia. Expone la clase `TareaIngesta` con `iniciar()` y `detener()`, un hilo daemon con `threading.Event` de parada, reloj inyectable (`RelojProtocol`/`RelojReal`) y protección contra solapamiento de ciclos (`threading.Lock`). Ante `ultima_pasada` nula, `error_global` o buscador caído no persiste nada ni avanza el `timestamp`.

## Ejemplo: arrancar y detener la tarea de ingesta

```python
from source.api.persistencia.client import ClienteBuscador
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas
from source.api.persistencia.ingestion import TareaIngesta

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)
buscador = ClienteBuscador("http://localhost:8000")

# Arrancar la ingesta: cada 300 s consulta el estado del buscador
tarea_ingesta = TareaIngesta(
    cliente_buscador=buscador,
    repositorio=repo,
    conexion=conexion,
    cadencia_segundos=300,
)
tarea_ingesta.iniciar()

# ... la aplicación funciona ...

# Al apagar: detener la ingesta limpiamente
tarea_ingesta.detener()
conexion.close()
```

## Ejemplo: ejecutar un solo ciclo de ingesta (sin hilo)

```python
from source.api.persistencia.client import ClienteBuscador
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas
from source.api.persistencia.ingestion import TareaIngesta

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)
buscador = ClienteBuscador("http://localhost:8000")

tarea = TareaIngesta(
    cliente_buscador=buscador,
    repositorio=repo,
    conexion=conexion,
    cadencia_segundos=300,
)
# Ejecutar un solo ciclo de ingesta directamente (sin arrancar el hilo)
resultado = tarea._ejecutar_ciclo()
if resultado.ejecutado:
    print(f"Timestamp procesado: {resultado.timestamp_procesado}")
    print(f"Ofertas persistidas: {resultado.ofertas_procesadas}")
else:
    print(f"Omitido: {resultado.motivo_omision}")

conexion.close()
```

## Componente: `purge-task` (`source/api/persistencia/purge.py`)

Tarea periódica que reduce a registro mínimo las ofertas cerradas no interesadas tras el plazo de retención. Expone la clase `TareaPurga` con `iniciar()` y `detener()`, un hilo daemon con `threading.Event` de parada y reloj inyectable (`RelojProtocol`/`RelojReal`). No modifica `ingesta_log` ni el estado de las ofertas.

## Ejemplo: arrancar y detener la tarea de purga

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas
from source.api.persistencia.purge import TareaPurga

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)

# Arrancar la purga: cada 86400 s, retención de 7 días
tarea_purga = TareaPurga(
    repositorio=repo,
    conexion=conexion,
    dias_retencion=7,
    frecuencia_segundos=86400,
)
tarea_purga.iniciar()

# ... la aplicación funciona ...

# Al apagar: detener la purga limpiamente
tarea_purga.detener()
conexion.close()
```

## Ejemplo: purga manual de un ciclo (sin hilo)

```python
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas
from source.api.persistencia.purge import TareaPurga

conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
repo = RepositorioOfertas(conexion)

tarea = TareaPurga(
    repositorio=repo,
    conexion=conexion,
    dias_retencion=7,
    frecuencia_segundos=86400,
)
# Ejecutar un solo ciclo de purga directamente (sin arrancar el hilo)
tarea._purgar()

conexion.close()
```

## Componente: `persistencia-api` (`source/api/persistencia/routes.py`)

Router FastAPI con los endpoints de persistencia: crear/actualizar ofertas, consultar por clave natural, listar vigentes y listar códigos vistos. Consume el `RepositorioOfertas` de `app_state` sin que el cliente ejecute SQL. El embedding se expone en JSON como base64 y se convierte a/desde `bytes` en el borde de la API. Sin autenticación.

## Ejemplo: crear una oferta y consultarla

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from source.api.persistencia.routes import router as persistencia_router
from source.api.persistencia.connection import abrir_conexion
from source.api.persistencia.migrations import migrar
from source.api.persistencia.repository import RepositorioOfertas
from source.api.main import app_state

# Preparar la BD y el repositorio
conexion = abrir_conexion("data/job_emcan.db")
migrar(conexion)
app_state["repositorio"] = RepositorioOfertas(conexion)

# Montar la app con el router de persistencia
app = FastAPI()
app.include_router(persistencia_router)
client = TestClient(app)

# Crear una oferta
respuesta = client.post("/persistencia/ofertas", json={
    "comunidad": "Cantabria",
    "codigo": "062026099999",
    "ocupacion": "Ingeniero informático",
    "municipio": "Santander",
    "estado": "vigente",
})
print(respuesta.json())  # {"comunidad": "Cantabria", "codigo": "062026099999", ...}

# Consultar la oferta
respuesta = client.get("/persistencia/ofertas/Cantabria/062026099999")
print(respuesta.json())  # Oferta completa con estado, embedding, fechas...

# Oferta inexistente → 404
respuesta = client.get("/persistencia/ofertas/Cantabria/999999999999")
print(respuesta.status_code)  # 404

conexion.close()
```

## Ejemplo: listar vigentes y códigos vistos

```python
from fastapi.testclient import TestClient
from source.api.persistencia.routes import router as persistencia_router

# ... (app y client montados como en el ejemplo anterior)

# Listar ofertas vigentes
respuesta = client.get("/persistencia/ofertas/vigentes")
for oferta in respuesta.json():
    print(f"{oferta['codigo']} - {oferta['ocupacion']}")

# Obtener códigos vistos de una comunidad
respuesta = client.get("/persistencia/codigos-vistos/Cantabria")
print(f"Códigos vistos: {respuesta.json()['codigos']}")
```

## Componente: `api-service` (`source/api/main.py`)

Integración del ciclo de vida de la persistencia en la aplicación FastAPI. El `lifespan` gestiona el arranque ordenado (configuración, conexión WAL, migraciones, importación de códigos vistos, tareas de ingesta y purga) y el apagado ordenado (ingesta → purga → conexión → scheduler). Los errores críticos de configuración o migración abortan el arranque; un `seen_codes.json` corrupto se registra como warning y no bloquea.

## Ejemplo: la aplicación arranca con persistencia integrada

```python
from fastapi.testclient import TestClient
from source.api.main import app

# Al entrar en el contexto, el lifespan arranca:
# - Carga configuración de persistencia
# - Abre SQLite con WAL
# - Aplica migraciones
# - Importa códigos vistos
# - Arranca TareaIngesta y TareaPurga
with TestClient(app) as client:
    # Los endpoints de persistencia están disponibles
    respuesta = client.get("/persistencia/ofertas/vigentes")
    print(f"Vigentes: {respuesta.json()}")

    # Los endpoints del buscador siguen respondiendo
    respuesta = client.get("/buscador/status")
    print(f"Estado: {respuesta.json()}")

# Al salir del contexto, el lifespan apaga en orden:
# 1. TareaIngesta.detener()
# 2. TareaPurga.detener()
# 3. Conexión SQLite cerrada
# 4. Scheduler del buscador detenido
```
