"""Configuración de la aplicación leída desde variables de entorno (un fichero .env)"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str

    s3_endpoint_url: str | None = None  # None = AWS S3 real
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "files"
    s3_region: str = "us-east-1"
    s3_auto_create_bucket: bool = True

    max_upload_size: int = Field(default=100 * 1024 * 1024, gt=0)  # bytes (100 MiB)
    allowed_content_types: Annotated[list[str], NoDecode] = []  # vacío = se admite cualquier tipo
    max_filename_length: int = Field(default=255, gt=0)

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return [item.lower() for item in value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
