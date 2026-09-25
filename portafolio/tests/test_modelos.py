from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from portafolio.data.modelos import Movimiento, Parametro, Portafolio, TipoMovimiento, Usuario
from portafolio.data.repositorios import ParametroNoDefinidoError, parametro_vigente


def test_decimal_exacto_en_sqlite(sesion, portafolio):
    m = Movimiento(
        usuario_id=portafolio.usuario_id,
        portafolio_id=portafolio.id,
        fecha=date(2024, 1, 1),
        tipo=TipoMovimiento.APORTE,
        monto=Decimal("12345678901234.123456"),
    )
    sesion.add(m)
    sesion.commit()
    sesion.expire_all()
    guardado = sesion.get(Movimiento, m.id)
    assert guardado.monto == Decimal("12345678901234.123456")
    assert isinstance(guardado.monto, Decimal)


def test_rechaza_float(sesion, portafolio):
    sesion.add(
        Movimiento(
            usuario_id=portafolio.usuario_id,
            portafolio_id=portafolio.id,
            fecha=date(2024, 1, 1),
            tipo=TipoMovimiento.APORTE,
            monto=0.1,
        )
    )
    with pytest.raises(StatementError, match="float"):
        sesion.flush()


def test_usuario_debe_coincidir_con_dueno_del_portafolio(sesion, portafolio):
    otro = Usuario(nombre="Otra persona", email="otra@example.com")
    sesion.add(otro)
    sesion.flush()
    sesion.add(
        Movimiento(
            usuario_id=otro.id,
            portafolio_id=portafolio.id,
            fecha=date(2024, 1, 1),
            tipo=TipoMovimiento.APORTE,
            monto=Decimal(1),
        )
    )
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_varios_portafolios_por_usuario(sesion, portafolio):
    sesion.add(Portafolio(usuario_id=portafolio.usuario_id, nombre="Corto plazo"))
    sesion.flush()
    sesion.add(Portafolio(usuario_id=portafolio.usuario_id, nombre="Corto plazo"))
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_parametro_vigente_por_fecha(sesion):
    sesion.add_all(
        [
            Parametro(nombre="retencion_rendimientos", vigente_desde=date(2020, 1, 1), valor=Decimal("0.04")),
            Parametro(nombre="retencion_rendimientos", vigente_desde=date(2025, 1, 1), valor=Decimal("0.07")),
        ]
    )
    sesion.flush()
    assert parametro_vigente(sesion, "retencion_rendimientos", date(2024, 12, 31)) == Decimal("0.04")
    assert parametro_vigente(sesion, "retencion_rendimientos", date(2025, 1, 1)) == Decimal("0.07")
    with pytest.raises(ParametroNoDefinidoError):
        parametro_vigente(sesion, "retencion_rendimientos", date(2019, 1, 1))
