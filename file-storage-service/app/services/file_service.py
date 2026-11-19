"""Lógica de negocio: coordina el almacenamiento de objetos y los metadatos."""

import hashlib
import logging
import mimetypes
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models import FileRecord
from app.exceptions import (
    DatabaseUnavailableError,
    FileNotFoundError_,
    InconsistentStateError,
    InvalidInputError,
    PayloadTooLargeError,
    StorageUnavailableError,
    UnsupportedMediaTypeError,
)
from app.storage.s3_storage import CHUNK_SIZE, ObjectNotFoundError, ObjectStorage, StorageError

logger = logging.getLogger(__name__)

GENERIC_CONTENT_TYPE = "application/octet-stream"
_SPOOL_MAX_MEMORY = 8 * 1024 * 1024  # a partir de 8 MiB el buffer temporal pasa a disco


@dataclass
class Download:
    record: FileRecord
    content: Iterator[bytes]


class FileService:
    def __init__(self, db: Session, storage: ObjectStorage, settings: Settings):
        self.db = db
        self.storage = storage
        self.settings = settings

    # ------------------------------------------------------------------ subir
    def upload(self, filename: str | None, data: BinaryIO, content_type: str | None) -> FileRecord:
        name = self._validate_filename(filename)
        mime = self._resolve_content_type(name, content_type)

        file_id = uuid.uuid4()
        storage_key = f"files/{file_id}"

        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_MEMORY) as buffer:
            size, sha256 = self._copy_and_hash(data, buffer)
            buffer.seek(0)
            try:
                self.storage.upload(storage_key, buffer, mime)
            except StorageError as exc:
                logger.exception("Fallo al guardar el objeto %s", storage_key)
                raise StorageUnavailableError("No se pudo guardar el archivo en el almacenamiento") from exc

        record = FileRecord(
            id=file_id,
            original_name=name,
            size=size,
            content_type=mime,
            sha256=sha256,
            storage_key=storage_key,
        )
        try:
            self.db.add(record)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.exception("Fallo al registrar metadatos de %s; se elimina el objeto", file_id)
            self._delete_orphan(storage_key)
            raise DatabaseUnavailableError("No se pudieron registrar los metadatos del archivo") from exc
        return record

    # ---------------------------------------------------------------- listar
    def list(
        self,
        limit: int,
        offset: int,
        name: str | None = None,
        content_type: str | None = None,
    ) -> tuple[list[FileRecord], int]:
        conditions = []
        if name:
            conditions.append(FileRecord.original_name.ilike(f"%{_escape_like(name)}%", escape="\\"))
        if content_type:
            conditions.append(FileRecord.content_type == content_type.lower())
        try:
            total = self.db.scalar(select(func.count()).select_from(FileRecord).where(*conditions))
            items = self.db.scalars(
                select(FileRecord)
                .where(*conditions)
                .order_by(FileRecord.uploaded_at.desc(), FileRecord.id)
                .limit(limit)
                .offset(offset)
            ).all()
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("No se pudo consultar la base de datos") from exc
        return list(items), int(total or 0)

    # -------------------------------------------------------------- consultar
    def get(self, file_id: uuid.UUID) -> FileRecord:
        try:
            record = self.db.get(FileRecord, file_id)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("No se pudo consultar la base de datos") from exc
        if record is None:
            raise FileNotFoundError_(f"No existe ningún archivo con identificador {file_id}")
        return record

    # -------------------------------------------------------------- descargar
    def download(self, file_id: uuid.UUID) -> Download:
        record = self.get(file_id)
        return Download(record=record, content=self._open(record))

    # -------------------------------------------------------------- eliminar
    def delete(self, file_id: uuid.UUID) -> None:
        """Elimina metadatos y objeto.

        El borrado del registro se prepara dentro de una transacción y sólo se
        confirma cuando el objeto se ha eliminado: si falla el almacenamiento,
        se deshace y el archivo sigue completo y accesible.
        """
        record = self.get(file_id)
        try:
            self.db.delete(record)
            self.db.flush()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise DatabaseUnavailableError("No se pudieron eliminar los metadatos") from exc

        try:
            self.storage.delete(record.storage_key)
        except StorageError as exc:
            self.db.rollback()
            logger.exception("Fallo al eliminar el objeto %s; se conservan los metadatos", record.storage_key)
            raise StorageUnavailableError("No se pudo eliminar el archivo del almacenamiento") from exc

        try:
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            # El objeto ya no existe: queda un registro sin contenido. Se deja constancia.
            logger.error("Objeto %s eliminado pero el registro %s no se pudo borrar", record.storage_key, file_id)
            raise DatabaseUnavailableError("No se pudieron eliminar los metadatos") from exc

    # ---------------------------------------------------- comprobar integridad
    def verify(self, file_id: uuid.UUID) -> tuple[FileRecord, str]:
        record = self.get(file_id)
        digest = hashlib.sha256()
        try:
            for chunk in self._open(record):
                digest.update(chunk)
        except StorageError as exc:
            raise StorageUnavailableError("No se pudo leer el archivo del almacenamiento") from exc
        return record, digest.hexdigest()

    # ------------------------------------------------------------ auxiliares
    def _validate_filename(self, filename: str | None) -> str:
        # Se descarta cualquier ruta que envíe el cliente; sólo se guarda el nombre.
        name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name:
            raise InvalidInputError("El archivo debe tener un nombre")
        if len(name) > self.settings.max_filename_length:
            raise InvalidInputError(
                f"El nombre del archivo supera {self.settings.max_filename_length} caracteres"
            )
        if any(ord(c) < 32 for c in name):
            raise InvalidInputError("El nombre del archivo contiene caracteres de control")
        return name

    def _resolve_content_type(self, name: str, declared: str | None) -> str | None:
        mime = (declared or "").split(";", 1)[0].strip().lower() or None
        if mime in (None, GENERIC_CONTENT_TYPE):
            guessed, _ = mimetypes.guess_type(name)
            mime = guessed.lower() if guessed else mime
        allowed = self.settings.allowed_content_types
        if allowed and (mime or GENERIC_CONTENT_TYPE) not in allowed:
            raise UnsupportedMediaTypeError(f"Tipo de contenido no permitido: {mime or 'desconocido'}")
        return mime

    def _copy_and_hash(self, source: BinaryIO, target: BinaryIO) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        limit = self.settings.max_upload_size
        while chunk := source.read(CHUNK_SIZE):
            size += len(chunk)
            if size > limit:
                raise PayloadTooLargeError(f"El archivo supera el tamaño máximo de {limit} bytes")
            digest.update(chunk)
            target.write(chunk)
        return size, digest.hexdigest()

    def _open(self, record: FileRecord) -> Iterator[bytes]:
        try:
            return self.storage.iter_content(record.storage_key)
        except ObjectNotFoundError as exc:
            logger.error("Falta el objeto %s del archivo %s", record.storage_key, record.id)
            raise InconsistentStateError("El contenido del archivo no está disponible") from exc
        except StorageError as exc:
            raise StorageUnavailableError("No se pudo leer el archivo del almacenamiento") from exc

    def _delete_orphan(self, storage_key: str) -> None:
        try:
            self.storage.delete(storage_key)
        except StorageError:
            logger.exception("No se pudo eliminar el objeto huérfano %s", storage_key)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
