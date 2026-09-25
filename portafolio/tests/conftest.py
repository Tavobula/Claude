from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from portafolio.data.db import crear_motor, fabrica_sesiones
from portafolio.data.modelos import Base, Instrumento, Portafolio, TipoInstrumento, Usuario


@pytest.fixture
def sesion() -> Session:
    motor = crear_motor("sqlite://")
    Base.metadata.create_all(motor)
    with fabrica_sesiones(motor)() as s:
        yield s
    motor.dispose()


@pytest.fixture
def portafolio(sesion) -> Portafolio:
    usuario = Usuario(nombre="Titular", email="titular@example.com")
    p = Portafolio(usuario=usuario, nombre="Retiro")
    sesion.add(p)
    sesion.flush()
    return p


@pytest.fixture
def instrumentos(sesion, portafolio) -> dict[str, Instrumento]:
    datos = {
        "Cuenta": TipoInstrumento.CUENTA,
        "CDT Banco A": TipoInstrumento.CDT,
        "FIC Renta Fija": TipoInstrumento.FIC,
    }
    resultado = {}
    for nombre, tipo in datos.items():
        i = Instrumento(
            usuario_id=portafolio.usuario_id,
            portafolio_id=portafolio.id,
            nombre=nombre,
            tipo=tipo,
        )
        sesion.add(i)
        resultado[nombre] = i
    sesion.flush()
    return resultado


def d(texto: str) -> date:
    return date.fromisoformat(texto)


def D(texto: str) -> Decimal:
    return Decimal(texto)
