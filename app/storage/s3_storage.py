"""Módulo de acceso al almacenamiento de objetos. Toda la interacción con S3/MinIO está encapsulada aquí

La lógica del servicio sólo depende del protocolo ``ObjectStorage``, de modo que MinIO puede 
sustituirse por cualquier otro sistema compatible con S3 (o por otra implementación) sin tocarla.
"""

from collections.abc import Iterator
from typing import BinaryIO, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

CHUNK_SIZE = 1024 * 1024  # 1 MiB


class StorageError(Exception):
    """Fallo del servicio de almacenamiento (red, credenciales, servidor...)."""


class ObjectNotFoundError(StorageError):
    """El objeto solicitado no existe."""


class ObjectStorage(Protocol):
    def ensure_bucket(self) -> None: ...

    def upload(self, key: str, data: BinaryIO, content_type: str | None = None) -> None: ...

    def iter_content(self, key: str, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...


_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class S3Storage:
    """Implementación de ``ObjectStorage`` sobre una API compatible con S3 (boto3)."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        client=None,
    ):
        self.bucket = bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in _NOT_FOUND_CODES:
                raise StorageError(f"No se pudo comprobar el bucket: {exc}") from exc
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except (ClientError, BotoCoreError) as create_exc:
                raise StorageError(f"No se pudo crear el bucket: {create_exc}") from create_exc
        except BotoCoreError as exc:
            raise StorageError(f"No se pudo comprobar el bucket: {exc}") from exc

    def upload(self, key: str, data: BinaryIO, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self._client.upload_fileobj(data, self.bucket, key, ExtraArgs=extra)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Error al guardar el objeto '{key}': {exc}") from exc

    def iter_content(self, key: str, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
        """Devuelve un iterador sobre el contenido.

        La petición se hace aquí (no de forma perezosa) para que los errores, como
        un objeto inexistente, se detecten antes de empezar a enviar la respuesta.
        """
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                raise ObjectNotFoundError(key) from exc
            raise StorageError(f"Error al leer el objeto '{key}': {exc}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"Error al leer el objeto '{key}': {exc}") from exc

        body = response["Body"]

        def _chunks() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(chunk_size)
            finally:
                body.close()

        return _chunks()

    def delete(self, key: str) -> None:
        # S3 no da error al borrar una clave inexistente: la operación es idempotente.
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"Error al eliminar el objeto '{key}': {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                return False
            raise StorageError(f"Error al consultar el objeto '{key}': {exc}") from exc
        except BotoCoreError as exc:
            raise StorageError(f"Error al consultar el objeto '{key}': {exc}") from exc
