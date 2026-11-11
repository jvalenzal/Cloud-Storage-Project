"""Endpoints REST de archivos."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_file_service
from app.schemas.file import ErrorResponse, FileList, FileMetadata, IntegrityCheck
from app.services.file_service import GENERIC_CONTENT_TYPE, FileService

router = APIRouter(prefix="/files", tags=["files"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "El archivo no existe"}}
_UNAVAILABLE = {503: {"model": ErrorResponse, "description": "Base de datos o almacenamiento no disponible"}}


@router.post(
    "",
    response_model=FileMetadata,
    status_code=status.HTTP_201_CREATED,
    summary="Subir un archivo",
    responses={
        400: {"model": ErrorResponse, "description": "Entrada no válida"},
        413: {"model": ErrorResponse, "description": "Archivo demasiado grande"},
        415: {"model": ErrorResponse, "description": "Tipo de contenido no permitido"},
        **_UNAVAILABLE,
    },
)
def upload_file(
    response: Response,
    file: UploadFile = File(..., description="Archivo a subir"),
    service: FileService = Depends(get_file_service),
):
    record = service.upload(file.filename, file.file, file.content_type)
    response.headers["Location"] = f"/files/{record.id}"
    return record


@router.get("", response_model=FileList, summary="Listar archivos", responses=_UNAVAILABLE)
def list_files(
    limit: int = Query(50, ge=1, le=500, description="Número máximo de resultados"),
    offset: int = Query(0, ge=0, description="Resultados a saltar"),
    name: str | None = Query(None, max_length=255, description="Filtra por nombre (contiene, sin distinguir mayúsculas)"),
    content_type: str | None = Query(None, max_length=255, description="Filtra por tipo MIME exacto"),
    service: FileService = Depends(get_file_service),
):
    items, total = service.list(limit=limit, offset=offset, name=name, content_type=content_type)
    return FileList(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/{file_id}",
    response_model=FileMetadata,
    summary="Consultar metadatos",
    responses={**_NOT_FOUND, **_UNAVAILABLE},
)
def get_file(file_id: uuid.UUID, service: FileService = Depends(get_file_service)):
    return service.get(file_id)


@router.get(
    "/{file_id}/download",
    summary="Descargar un archivo",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}, **_NOT_FOUND, **_UNAVAILABLE},
)
def download_file(file_id: uuid.UUID, service: FileService = Depends(get_file_service)):
    download = service.download(file_id)
    record = download.record
    headers = {
        "Content-Disposition": _content_disposition(record.original_name),
        "Content-Length": str(record.size),
        "X-Content-SHA256": record.sha256,
        "ETag": f'"{record.sha256}"',
    }
    return StreamingResponse(
        download.content,
        media_type=record.content_type or GENERIC_CONTENT_TYPE,
        headers=headers,
    )


@router.get(
    "/{file_id}/verify",
    response_model=IntegrityCheck,
    summary="Comprobar integridad (SHA-256)",
    description="Recalcula el SHA-256 del contenido almacenado y lo compara con el registrado al subirlo.",
    responses={**_NOT_FOUND, **_UNAVAILABLE},
)
def verify_file(file_id: uuid.UUID, service: FileService = Depends(get_file_service)):
    record, actual = service.verify(file_id)
    return IntegrityCheck(
        file_id=record.id,
        expected_sha256=record.sha256,
        actual_sha256=actual,
        valid=actual == record.sha256,
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un archivo",
    responses={**_NOT_FOUND, **_UNAVAILABLE},
)
def delete_file(file_id: uuid.UUID, service: FileService = Depends(get_file_service)):
    service.delete(file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "replace").decode().replace('"', "_").replace("?", "_")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
