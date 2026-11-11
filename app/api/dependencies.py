''' Con este archivo se construyen los objectos necesarios para cada petición 
a la base de BD usando el soporte nativo de dependencias inyectables para FastAPI '''

''' Se define la sesión, el cliente de almacenamiento  y
el FileService (que contiene la base de datos, la configuración 
de la aplicación y de la base de datos)'''

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
