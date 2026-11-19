# Proyecto de CIMSI

API REST (FastAPI) para subir, listar, consultar, descargar, verificar y eliminar archivos.
El contenido binario se guarda en un almacenamiento de objetos compatible con S3 (MinIO) y los
metadatos en PostgreSQL.

## Endpoints

| Método | Ruta                         | Finalidad                                   | Éxito |
|--------|------------------------------|---------------------------------------------|-------|
| POST   | `/files`                     | Subir un archivo (`multipart/form-data`, campo `file`) | 201 |
| GET    | `/files`                     | Listar (`limit`, `offset`, `name`, `content_type`)     | 200 |
| GET    | `/files/{file_id}`           | Consultar metadatos                         | 200 |
| GET    | `/files/{file_id}/download`  | Descargar el contenido                      | 200 |
| GET    | `/files/{file_id}/verify`    | Recalcular SHA-256 y compararlo con el registrado | 200 |
| DELETE | `/files/{file_id}`           | Eliminar contenido y metadatos              | 204 |
| GET    | `/health`                    | Comprobación de vida                        | 200 |

Documentación interactiva: `http://localhost:8000/docs` (Swagger UI).

La descarga incluye las cabeceras `Content-Disposition` (nombre original, compatible con UTF-8),
`Content-Length`, `X-Content-SHA256` y `ETag`.

### Errores

Todos los errores de aplicación tienen la forma `{"error": {"code": "...", "message": "..."}}`.

| HTTP | `code`                   | Cuándo |
|------|--------------------------|--------|
| 400  | `invalid_input`          | Nombre vacío, demasiado largo o con caracteres de control |
| 404  | `file_not_found`         | Identificador inexistente |
| 413  | `payload_too_large`      | Supera `MAX_UPLOAD_SIZE` |
| 415  | `unsupported_media_type` | Tipo no incluido en `ALLOWED_CONTENT_TYPES` |
| 422  | —                        | Petición mal formada (UUID inválido, falta el campo `file`, paginación fuera de rango) |
| 500  | `inconsistent_state`     | Hay metadatos pero falta el objeto |
| 503  | `storage_unavailable` / `database_unavailable` | Fallo de MinIO o de PostgreSQL |

## Reglas de validación (configurables)

- Tamaño máximo: `MAX_UPLOAD_SIZE` (100 MiB por defecto). Se comprueba mientras se lee el archivo.
- Tipos permitidos: `ALLOWED_CONTENT_TYPES`, lista separada por comas; vacía = cualquiera.
- Tipo MIME: el declarado por el cliente; si falta o es `application/octet-stream`, se deduce de la extensión.
- Nombre: se descarta cualquier ruta enviada por el cliente; máximo `MAX_FILENAME_LENGTH` caracteres.
- Se admiten archivos vacíos.

## Consistencia entre almacenes

- **Subida**: se guarda primero el objeto y después los metadatos. Si falla la base de datos,
  se elimina el objeto para no dejar huérfanos.
- **Eliminación**: el borrado del registro se prepara en una transacción, se elimina el objeto
  y sólo entonces se confirma. Si falla el almacenamiento, se deshace y el archivo sigue intacto.
- Si una limpieza falla, queda registrada en el log con la clave afectada.

## Puesta en marcha con Docker Compose (todo en contenedores)

```bash
cp .env.example .env          # y cambia las credenciales
docker compose up -d --build
```

Levanta `postgres`, `minio`, `migrate` (ejecuta `alembic upgrade head` y termina) y `api`.
La API arranca sólo cuando PostgreSQL y MinIO están sanos y las migraciones han terminado.

- API: `http://localhost:8000` (Swagger en `/docs`)
- Consola de MinIO: `http://localhost:9001`
- Puertos configurables con `API_PORT`, `POSTGRES_PORT`, `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`.

Dentro de Compose la API se conecta por nombre de servicio (`postgres`, `minio`) usando las
credenciales `POSTGRES_*` y `MINIO_ROOT_*`; `DATABASE_URL` y `S3_ENDPOINT_URL` del `.env` sólo
se usan al ejecutar la API fuera de Docker.

> MinIO ya no publica imágenes en Docker Hub; se usa `pgsty/minio`, una build comunitaria del
> mismo servidor. Puede cambiarse con la variable `MINIO_IMAGE`.

Parar: `docker compose down` (añade `-v` para borrar también los datos).

## Despliegue multinodo

Para repartir el servicio entre varios servidores, `deploy/` contiene un Compose independiente
por función. Cada servidor físico ejecuta uno o varios de ellos:

```
deploy/
├── database/   compose.yaml + .env   → PostgreSQL (metadatos)
├── minio/      compose.yaml + .env   → MinIO (contenido binario)
└── api/        compose.yaml + .env   → API FastAPI (uno o varios nodos)
```

Cada Compose tiene su propio nombre de proyecto (`file-storage-database`, `file-storage-minio`,
`file-storage-api`), así que pueden convivir en el mismo servidor. Los servicios no comparten
red de Docker: la API llega a PostgreSQL y a MinIO por **IP (o nombre DNS) y puerto**, igual
que si estuvieran en máquinas distintas.

Ejemplo de reparto:

| Servidor   | IP de ejemplo | Ejecuta |
|------------|---------------|---------|
| nodo-1     | `10.0.0.11`   | `database` + `api` |
| nodo-2     | `10.0.0.12`   | `minio` + `api` |

### 1. Preparar la configuración

En cada servidor, copia el repositorio (o sólo la carpeta `deploy/` del servicio que vaya a
ejecutar) y edita el `.env` correspondiente. Los `.env` no se suben al repositorio.

Las credenciales deben coincidir entre archivos:

| En `deploy/api/.env`                | Debe coincidir con |
|-------------------------------------|--------------------|
| usuario, clave y base de `DATABASE_URL` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` de `deploy/database/.env` |
| host y puerto de `DATABASE_URL`     | IP del nodo de base de datos y `POSTGRES_PORT` |
| `S3_ENDPOINT_URL`                   | `http://<IP del nodo MinIO>:<MINIO_API_PORT>` |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY`    | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` de `deploy/minio/.env` |

Ejemplo de `deploy/api/.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://files:<clave>@10.0.0.11:5432/files
S3_ENDPOINT_URL=http://10.0.0.12:9000
S3_ACCESS_KEY=<usuario de MinIO>
S3_SECRET_KEY=<clave de MinIO>
```

### 2. Arrancar la base de datos y el almacenamiento

En el nodo de base de datos:

```bash
cd deploy/database
docker compose up -d --wait
```

En el nodo de MinIO:

```bash
cd deploy/minio
docker compose up -d --wait
```

El bucket no hace falta crearlo: lo crea la API al arrancar (`S3_AUTO_CREATE_BUCKET=true`).

### 3. Construir la imagen de la API

En un nodo con el código fuente, `docker compose build` construye la imagen desde la raíz
del repositorio:

```bash
cd deploy/api
docker compose build
```

Para nodos de API sin el código, publica la imagen en un registro (por ejemplo GitHub
Container Registry), indica su nombre en `API_IMAGE` y descárgala con `docker compose pull`:

```bash
docker tag file-storage-service:latest ghcr.io/<usuario>/file-storage-service:1.0.0
docker push ghcr.io/<usuario>/file-storage-service:1.0.0
```

### 4. Aplicar las migraciones (una sola vez, desde un solo nodo)

Las migraciones no se ejecutan con `up`, para que varios nodos de API no modifiquen el
esquema a la vez. Lánzalas a mano desde **un** nodo de API antes del primer arranque y cada
vez que una versión nueva incluya migraciones:

```bash
cd deploy/api
docker compose --profile migrate run --rm migrate
```

El contenedor espera a que PostgreSQL acepte conexiones (hasta unos 60 s), ejecuta
`alembic upgrade head` y termina. Repetirlo sin migraciones pendientes no tiene efecto.

### 5. Arrancar la API

En cada nodo de API:

```bash
cd deploy/api
docker compose up -d --wait
```

Comprueba que responde:

```bash
curl http://<IP del nodo>:8000/health
```

Con varios nodos de API, pon delante un balanceador o proxy inverso (nginx, HAProxy, Traefik…)
que reparta las peticiones entre `http://<IP de cada nodo>:8000`. La API no guarda estado
propio, así que cualquier nodo puede atender cualquier petición.

### Variables de despliegue

| Variable | Archivo | Uso |
|----------|---------|-----|
| `POSTGRES_BIND_ADDRESS`, `POSTGRES_PORT` | `database/.env` | Interfaz y puerto donde se publica PostgreSQL |
| `MINIO_BIND_ADDRESS`, `MINIO_API_PORT` | `minio/.env` | Interfaz y puerto de la API S3 |
| `MINIO_CONSOLE_BIND_ADDRESS`, `MINIO_CONSOLE_PORT` | `minio/.env` | Interfaz y puerto de la consola web |
| `API_BIND_ADDRESS`, `API_PORT` | `api/.env` | Interfaz y puerto de la API |
| `API_WORKERS` | `api/.env` | Procesos de uvicorn por nodo (2 por defecto) |
| `FORWARDED_ALLOW_IPS` | `api/.env` | IP del balanceador cuyas cabeceras `X-Forwarded-*` se aceptan |
| `API_IMAGE` | `api/.env` | Imagen de la API (local o de un registro) |
| `POSTGRES_IMAGE`, `MINIO_IMAGE` | `database/.env`, `minio/.env` | Cambiar la imagen de PostgreSQL o MinIO |

`*_BIND_ADDRESS` vale `0.0.0.0` (todas las interfaces) por defecto; pon la IP de la red
interna del servidor para no publicar el servicio en las demás.

### Seguridad

- Restringe con el cortafuegos el acceso a PostgreSQL (5432) y MinIO (9000) a los nodos de API.
- Deja la consola de MinIO (9001) sólo en la red interna.
- Usa contraseñas largas y distintas en cada `.env`. Las de ejemplo deben cambiarse.
- En producción, crea en MinIO una clave de acceso propia para la API en lugar de usar la del
  administrador (`MINIO_ROOT_*`).
- `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` sólo se aplican la primera vez, con el
  volumen vacío. Cambiarlos después no tiene efecto sin recrear el volumen (y perder los datos).

### Operación

| Acción | Comando (en la carpeta del servicio) |
|--------|--------------------------------------|
| Ver estado | `docker compose ps` |
| Ver logs | `docker compose logs -f` |
| Actualizar la API | `docker compose build` (o `pull`), migraciones si las hay, `docker compose up -d` |
| Parar | `docker compose down` |
| Parar y borrar los datos | `docker compose down -v` (¡irreversible!) |

Los datos viven en los volúmenes `file-storage-database_pgdata` y `file-storage-minio_miniodata`
de cada servidor; inclúyelos en las copias de seguridad.

## Puesta en marcha (desarrollo, API en local)

Requisitos: Python 3.10+ y, para PostgreSQL y MinIO en local, Docker.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env          # y cambia las credenciales
docker compose up -d postgres minio
alembic upgrade head
uvicorn app.main:app --reload
```

Al arrancar, la aplicación crea el bucket si no existe (`S3_AUTO_CREATE_BUCKET=true`).
La consola de MinIO queda en `http://localhost:9001`.

## Pruebas

```bash
pytest
```

No necesitan servicios externos: los metadatos usan SQLite en memoria y el almacenamiento usa
el módulo `S3Storage` real contra un S3 simulado con [moto](https://github.com/getmoto/moto).
Cubren los criterios de aceptación y los casos de error (404, 413, 415, caídas de base de
datos o de almacenamiento y limpieza de huérfanos).

> En Windows, si el proyecto está en una ruta muy larga, `pip`/`moto` pueden fallar al cargar
> la DLL de `cryptography` ("nombre de archivo demasiado largo"). Crea el entorno virtual en
> una ruta más corta o activa las rutas largas de Windows.

## Estructura

```
app/
├── main.py                  # creación de la app y gestión de errores
├── config.py                # configuración por variables de entorno
├── exceptions.py            # errores de aplicación → códigos HTTP
├── api/
│   ├── dependencies.py      # inyección de servicio, BD y almacenamiento
│   └── routes/files.py      # endpoints
├── services/file_service.py # lógica de negocio y consistencia
├── storage/s3_storage.py    # acceso a S3/MinIO (sustituible)
├── database/
│   ├── connection.py
│   └── models.py
└── schemas/file.py          # modelos Pydantic
alembic/                     # migraciones del esquema
tests/
deploy/                      # despliegue multinodo: un Compose por servicio
├── api/
├── database/
└── minio/
```

Para cambiar MinIO por otro proveedor compatible con S3 basta con ajustar `S3_ENDPOINT_URL` y
las credenciales. Para un sistema no compatible con S3, se implementa el protocolo
`ObjectStorage` de `app/storage/s3_storage.py` y se devuelve desde `get_storage()`.
