"""Punto de entrada de la aplicación FastAPI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_storage
from app.api.routes import files
from app.config import get_settings
from app.exceptions import AppError
from app.storage.s3_storage import StorageError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().s3_auto_create_bucket:
        storage = app.dependency_overrides.get(get_storage, get_storage)()
        try:
            storage.ensure_bucket()
        except StorageError:
            # La API arranca igualmente; las operaciones devolverán 503 hasta que haya almacenamiento.
            logger.exception("No se pudo preparar el bucket de almacenamiento")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Servicio de almacenamiento de archivos",
        version="1.0.0",
        description="API REST para subir, listar, consultar, descargar, verificar y eliminar archivos.",
        lifespan=lifespan,
    )

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/health", tags=["health"], summary="Comprobación de vida")
    def health():
        return {"status": "ok"}

    app.include_router(files.router)
    return app


app = create_app()
