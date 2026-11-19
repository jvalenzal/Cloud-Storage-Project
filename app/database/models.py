"""En este archivo se hace un modelo de la tabla
de la BD como clase de Python para facilitar 
la transferencia de metadatos"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String, Uuid
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base

# MySQL: DATETIME no guarda zona horaria y por defecto descarta los microsegundos.
# Se guarda siempre la hora UTC sin zona, con precisión de microsegundos (DATETIME(6)).
UtcDateTime = DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Clase de representación de metadatos
class FileRecord(Base):

    __tablename__ = "files"
    __table_args__ = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}

    # En MySQL, Uuid se guarda como CHAR(32).
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, index=True
    )
