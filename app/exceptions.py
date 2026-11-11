"""Errores de aplicación. Cada uno sabe qué código HTTP le corresponde."""


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class FileNotFoundError_(AppError):
    status_code = 404
    code = "file_not_found"


class InvalidInputError(AppError):
    status_code = 400
    code = "invalid_input"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "unsupported_media_type"


class StorageUnavailableError(AppError):
    status_code = 503
    code = "storage_unavailable"


class DatabaseUnavailableError(AppError):
    status_code = 503
    code = "database_unavailable"


class InconsistentStateError(AppError):
    """Hay metadatos pero falta el objeto en el almacenamiento."""

    status_code = 500
    code = "inconsistent_state"
