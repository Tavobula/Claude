"""La migración de Alembic debe producir exactamente el esquema de los modelos."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from portafolio.data.db import crear_motor
from portafolio.data.modelos import Base

RAIZ = Path(__file__).resolve().parents[1]


def _config(url: str) -> Config:
    config = Config(str(RAIZ / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configurar_logs"] = False
    return config


def test_migraciones_coinciden_con_modelos(tmp_path):
    url = f"sqlite:///{tmp_path / 'prueba.db'}"
    config = _config(url)
    command.upgrade(config, "head")

    motor = crear_motor(url)
    with motor.connect() as conexion:
        diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)
    assert diferencias == []

    command.downgrade(config, "base")
    assert inspect(motor).get_table_names() == ["alembic_version"]
    motor.dispose()
