""" Módulo de esquemas Pydantic de entrada/salida de FastAPI"""
""" Se definen los datos que salen y entran por 
los endpoints, se validan y se documenta la API """

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FileMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="Identificador único del archivo")
    original_name: str = Field(description="Nombre original del archivo subido")
    size: int = Field(description="Tamaño en bytes")
    content_type: str | None = Field(description="Tipo MIME, si pudo determinarse")
    sha256: str = Field(description="Hash SHA-256 del contenido (hexadecimal)")
    storage_key: str = Field(description="Clave del objeto en el almacenamiento")
    uploaded_at: datetime = Field(description="Fecha y hora de subida (UTC)")

    @field_validator("uploaded_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # Algunos motores (p. ej. SQLite) devuelven fechas sin zona horaria: se guardan siempre en UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class FileList(BaseModel):
    items: list[FileMetadata]
    total: int = Field(description="Número total de archivos que cumplen los filtros")
    limit: int
    offset: int


class IntegrityCheck(BaseModel):
    file_id: uuid.UUID
    expected_sha256: str = Field(description="Hash registrado durante la subida")
    actual_sha256: str = Field(description="Hash calculado sobre el contenido almacenado")
    valid: bool


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
