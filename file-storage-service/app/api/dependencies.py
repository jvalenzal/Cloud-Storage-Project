"""Dependencias inyectables (se pueden sustituir en las pruebas)."""

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.connection import get_db
from app.services.file_service import FileService
from app.storage.s3_storage import ObjectStorage, S3Storage


@lru_cache
def get_storage() -> ObjectStorage:
    s = get_settings()
    return S3Storage(
        bucket=s.s3_bucket,
        endpoint_url=s.s3_endpoint_url,
        access_key=s.s3_access_key,
        secret_key=s.s3_secret_key,
        region=s.s3_region,
    )


def get_file_service(
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> FileService:
    return FileService(db=db, storage=storage, settings=settings)
