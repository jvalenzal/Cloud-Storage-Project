# Servicio de almacenamiento de archivos

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
```

Para cambiar MinIO por otro proveedor compatible con S3 basta con ajustar `S3_ENDPOINT_URL` y
las credenciales. Para un sistema no compatible con S3, se implementa el protocolo
`ObjectStorage` de `app/storage/s3_storage.py` y se devuelve desde `get_storage()`.
