"""Conexión a la base de datos.

La URL sale de ``PORTAFOLIO_DB_URL``; por defecto un archivo SQLite local.
Pasar a PostgreSQL es cambiar la URL y correr ``alembic upgrade head``.
"""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

URL_POR_DEFECTO = "sqlite:///portafolio.db"


def url_base_datos() -> str:
    return os.environ.get("PORTAFOLIO_DB_URL", URL_POR_DEFECTO)


def crear_motor(url: str | None = None, **kwargs) -> Engine:
    motor = create_engine(url or url_base_datos(), **kwargs)
    if motor.dialect.name == "sqlite":
        # SQLite no valida llaves foráneas a menos que se active por conexión.
        @event.listens_for(motor, "connect")
        def _activar_fk(conexion, _registro):
            cursor = conexion.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return motor


def fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=motor, expire_on_commit=False)
