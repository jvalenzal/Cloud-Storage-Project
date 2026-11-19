# Proyecto de CIMSI

API REST (FastAPI) para subir, listar, consultar, descargar, verificar y eliminar archivos.
El contenido binario se guarda en un almacenamiento de objetos compatible con S3 (MinIO) y los
metadatos en MySQL.

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
| 503  | `storage_unavailable` / `database_unavailable` | Fallo de MinIO o de MySQL |

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

## Base de datos (MySQL)

- Driver: `PyMySQL` (Python puro). URL: `mysql+pymysql://usuario:clave@host:3306/base?charset=utf8mb4`.
  El `charset=utf8mb4` es necesario para guardar bien nombres con tildes, eñes o emojis.
- Las fechas se guardan en UTC, sin zona horaria, como `DATETIME(6)` (con microsegundos); la API
  las devuelve siempre con zona (`...Z`).
- Los identificadores se guardan como `CHAR(32)`.
- La colación por defecto de MySQL 8 (`utf8mb4_0900_ai_ci`) no distingue mayúsculas ni acentos:
  el filtro `?name=ano` encuentra `año.txt`, y `?content_type=` tampoco distingue mayúsculas.
- La conexión se renueva cada hora (`pool_recycle`) para que MySQL no la cierre por inactividad.

## Puesta en marcha con Docker Compose (todo en contenedores)

```bash
cp .env.example .env          # y cambia las credenciales
docker compose up -d --build
```

Levanta `mysql`, `minio`, `migrate` (ejecuta `alembic upgrade head` y termina) y `api`.
La API arranca sólo cuando MySQL y MinIO están sanos y las migraciones han terminado.

- API: `http://localhost:8000` (Swagger en `/docs`)
- Consola de MinIO: `http://localhost:9001`
- Puertos configurables con `API_PORT`, `MYSQL_PORT`, `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`.

Dentro de Compose la API se conecta por nombre de servicio (`mysql`, `minio`) usando las
credenciales `MYSQL_*` y `MINIO_ROOT_*`; `DATABASE_URL` y `S3_ENDPOINT_URL` del `.env` sólo
se usan al ejecutar la API fuera de Docker.

> MinIO ya no publica imágenes en Docker Hub; se usa `pgsty/minio`, una build comunitaria del
> mismo servidor. Puede cambiarse con la variable `MINIO_IMAGE`.

Parar: `docker compose down` (añade `-v` para borrar también los datos).

## Despliegue en Kubernetes (k3s)

`k8s/` contiene los manifiestos para el clúster k3s de 5 nodos: el nodo 5 (máster) aloja la
monitorización y los nodos 1–4 la aplicación. El reparto se hace con la etiqueta `nodo=1..5`
de cada nodo y los namespaces `core`, `storage` y `monitoring`.

```
k8s/
├── storage/                 # namespace "storage"
│   ├── mysql-secret.yaml    # PLANTILLA de credenciales de MySQL
│   ├── mysql.yaml           # StatefulSet (1 réplica) + Service "mysql" + volumen
│   ├── minio-secret.yaml    # PLANTILLA de credenciales de MinIO
│   └── minio.yaml           # StatefulSet distribuido (4 réplicas, una por nodo) + Services
├── core/                    # namespace "core"
│   ├── api-config.yaml      # ConfigMap: bucket, URL de MinIO, reglas de validación
│   ├── api-secret.yaml      # PLANTILLA: DATABASE_URL y claves S3
│   ├── migrate-job.yaml     # Job: alembic upgrade head
│   ├── api.yaml             # Deployment (4 réplicas) + Service
│   └── ingress.yaml         # entrada HTTP desde fuera del clúster
├── ingress/
│   └── traefik-values.yaml  # valores de Helm de Traefik (balanceador de entrada)
└── monitoring/
    └── values.yaml          # valores de Helm de Prometheus + Grafana (nodo 5)
```

| Componente | Dónde se ejecuta | Cómo se llega a él |
|------------|------------------|--------------------|
| MySQL | 1 pod en uno de los nodos 1–4 | `mysql.storage.svc.cluster.local:3306` |
| MinIO | 4 pods, uno en cada nodo 1–4 | `minio.storage.svc.cluster.local:9000` |
| API | 4 pods repartidos en los nodos 1–4 | `file-storage-api.core.svc.cluster.local` |
| Traefik | 2 pods en nodos 1–4 distintos | Puerto 80 de las IP de los nodos |
| Prometheus, Grafana, Alertmanager | Nodo 5 | Grafana: `http://<IP del nodo 5>:30300` |

Todos los comandos se lanzan desde un equipo con `kubectl` y `helm`, usando el kubeconfig del
clúster (`export KUBECONFIG=k3s-cluster.yaml`).

### 1. Publicar la imagen de la API

Los nodos descargan la imagen de un registro. Con GitHub Container Registry (el nombre debe ir
en minúsculas):

```bash
docker login ghcr.io -u <usuario de GitHub>        # con un token con permiso write:packages
docker build -t ghcr.io/78spicy/file-storage-service:1.0.0 .
docker push ghcr.io/78spicy/file-storage-service:1.0.0
```

Si usas otro nombre o versión, cámbialo en `k8s/core/api.yaml` y `k8s/core/migrate-job.yaml`.
Si el paquete es privado, crea el Secret de acceso y descomenta `imagePullSecrets` en esos dos
archivos:

```bash
kubectl create secret docker-registry ghcr -n core \
  --docker-server=ghcr.io --docker-username=<usuario> --docker-password=<token de lectura>
```

### 2. Crear los Secrets

Los `*-secret.yaml` del repositorio son **plantillas** con claves de ejemplo: no pongas en ellos
las claves reales. Crea los Secrets directamente con `kubectl` (las credenciales deben coincidir
entre los tres):

```bash
kubectl create secret generic mysql-secret -n storage \
  --from-literal=MYSQL_ROOT_PASSWORD='<clave de root>' \
  --from-literal=MYSQL_DATABASE=files \
  --from-literal=MYSQL_USER=files \
  --from-literal=MYSQL_PASSWORD='<clave>'

kubectl create secret generic minio-secret -n storage \
  --from-literal=MINIO_ROOT_USER='<usuario>' \
  --from-literal=MINIO_ROOT_PASSWORD='<clave de 8+ caracteres>'

kubectl create secret generic api-secret -n core \
  --from-literal=DATABASE_URL='mysql+pymysql://files:<clave>@mysql.storage.svc.cluster.local:3306/files?charset=utf8mb4' \
  --from-literal=S3_ACCESS_KEY='<usuario de MinIO>' \
  --from-literal=S3_SECRET_KEY='<clave de MinIO>'
```

> No ejecutes `kubectl apply -f k8s/storage/` ni `-f k8s/core/` sobre la carpeta entera: aplicaría
> también las plantillas y sustituiría tus Secrets por las claves de ejemplo. Aplica los archivos
> uno a uno, como en los pasos siguientes.

### 3. Desplegar MySQL y MinIO

```bash
kubectl apply -f k8s/storage/mysql.yaml -f k8s/storage/minio.yaml
kubectl rollout status statefulset/mysql -n storage
kubectl rollout status statefulset/minio -n storage
```

MinIO necesita los 4 nodos de aplicación disponibles para arrancar por primera vez.

### 4. Aplicar las migraciones

```bash
kubectl apply -f k8s/core/api-config.yaml
kubectl apply -f k8s/core/migrate-job.yaml
kubectl wait --for=condition=complete job/migrate -n core --timeout=300s
kubectl logs job/migrate -n core
```

### 5. Desplegar la API

```bash
kubectl apply -f k8s/core/api.yaml
kubectl rollout status deployment/file-storage-api -n core
```

### 6. Instalar Traefik y publicar la API

k3s se instaló con `--disable traefik`, así que Traefik se instala con Helm:

```bash
helm repo add traefik https://traefik.github.io/charts
helm upgrade --install traefik traefik/traefik -n core -f k8s/ingress/traefik-values.yaml
kubectl apply -f k8s/core/ingress.yaml
```

La API queda disponible en el puerto 80 de cualquier nodo, por ejemplo
`http://192.168.120.141/docs`. El ServiceLB de k3s publica ese puerto en las IP de los nodos.

### 7. Instalar la monitorización

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
kubectl create secret generic grafana-admin -n monitoring \
  --from-literal=admin-user=admin --from-literal=admin-password='<clave>'
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f k8s/monitoring/values.yaml
```

Grafana queda en `http://<IP del nodo 5>:30300`; por Tailscale, `http://100.97.131.86:30300`.
Prometheus recoge CPU, memoria, disco y el estado de los pods de todos los nodos. Para métricas
propias de la API (peticiones, latencias, errores) habría que añadirle un endpoint `/metrics`.

### Comprobación

```bash
kubectl get pods -A -o wide        # qué pod está en qué nodo
curl http://192.168.120.141/health
```

### Actualizar la API

1. Publica la imagen con una versión nueva (`:1.0.1`) y cámbiala en `api.yaml` y `migrate-job.yaml`.
2. Si la versión incluye migraciones, repite el paso 4 borrando antes el Job anterior:
   `kubectl delete job migrate -n core --ignore-not-found`.
3. `kubectl apply -f k8s/core/api.yaml`. El Deployment reemplaza las réplicas de una en una,
   sin cortar el servicio.

### Limitaciones de esta primera versión

- **MySQL tiene una sola réplica.** Si cae su nodo, la API devuelve 503 hasta que vuelva. Para
  alta disponibilidad hace falta un operador (p. ej. MySQL Operator o Percona); no basta con
  subir `replicas`.
- **Volúmenes `local-path`.** Los datos están en el disco del nodo donde se creó cada pod, y ese
  pod queda atado a ese nodo. Longhorn replicaría los volúmenes entre nodos.
- **MinIO distribuido** tolera la caída de un nodo, pero sus pods no se reubican: el pod de ese
  nodo vuelve cuando el nodo vuelve.

## Puesta en marcha (desarrollo, API en local)

Requisitos: Python 3.10+ y, para MySQL y MinIO en local, Docker.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env          # y cambia las credenciales
docker compose up -d mysql minio
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
k8s/                         # despliegue en Kubernetes (k3s)
├── storage/                 # MySQL y MinIO
├── core/                    # API, migraciones e Ingress
├── ingress/                 # valores de Helm de Traefik
└── monitoring/              # valores de Helm de Prometheus + Grafana
```

Para cambiar MinIO por otro proveedor compatible con S3 basta con ajustar `S3_ENDPOINT_URL` y
las credenciales. Para un sistema no compatible con S3, se implementa el protocolo
`ObjectStorage` de `app/storage/s3_storage.py` y se devuelve desde `get_storage()`.
