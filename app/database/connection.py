"""En este archivo se define la conexión
a la BD (MySQL) mediante SQLAlchemy"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping descarta conexiones rotas; pool_recycle las renueva antes de que MySQL
    # cierre las inactivas (wait_timeout), evitando "MySQL server has gone away".
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_recycle=3600)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
