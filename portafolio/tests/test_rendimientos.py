from decimal import Decimal

import pytest

from conftest import D, d
from portafolio.data.modelos import Movimiento, TipoMovimiento, Valoracion
from portafolio.services.rendimientos import (
    ValoracionFaltanteError,
    tir_instrumento,
    tir_portafolio,
)


def _mov(p, fecha, tipo, monto, instrumento=None):
    return Movimiento(
        usuario_id=p.usuario_id,
        portafolio_id=p.id,
        instrumento_id=instrumento.id if instrumento else None,
        fecha=d(fecha),
        tipo=tipo,
        monto=D(monto),
    )


def _val(p, instrumento, fecha, valor):
    return Valoracion(
        usuario_id=p.usuario_id,
        portafolio_id=p.id,
        instrumento_id=instrumento.id,
        fecha=d(fecha),
        valor=D(valor),
    )


def test_cdt_a_un_anio(sesion, portafolio, instrumentos):
    cdt = instrumentos["CDT Banco A"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-02", TipoMovimiento.APORTE, "10000000"),
            _mov(portafolio, "2024-01-02", TipoMovimiento.COMPRA, "10000000", cdt),
            _val(portafolio, cdt, "2025-01-01", "11000000"),  # 365 días después
        ]
    )
    sesion.flush()

    resultado = tir_portafolio(sesion, portafolio.id, d("2025-01-01"))
    assert resultado.tasa == pytest.approx(0.10)
    assert resultado.valor_final == Decimal("11000000")
    assert tir_instrumento(sesion, cdt.id, d("2025-01-01")).tasa == pytest.approx(0.10)


def test_portafolio_ignora_flujos_internos(sesion, portafolio, instrumentos):
    """Intereses, impuestos y compras no cambian la TIR del portafolio; sí la del instrumento."""
    cuenta, fic = instrumentos["Cuenta"], instrumentos["FIC Renta Fija"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.APORTE, "1000", cuenta),
            _mov(portafolio, "2024-01-01", TipoMovimiento.COMPRA, "1000", fic),
            _mov(portafolio, "2024-07-01", TipoMovimiento.INTERES, "60", fic),
            _mov(portafolio, "2024-07-01", TipoMovimiento.IMPUESTO, "2.40", fic),
            _val(portafolio, cuenta, "2024-12-31", "57.60"),
            _val(portafolio, fic, "2024-12-31", "1030"),
        ]
    )
    sesion.flush()

    corte = d("2024-12-31")
    portafolio_tir = tir_portafolio(sesion, portafolio.id, corte)
    assert [m for _, m in portafolio_tir.flujos] == [D("-1000"), D("1087.60")]
    assert portafolio_tir.tasa == pytest.approx(0.0876, abs=1e-12)

    fic_tir = tir_instrumento(sesion, fic.id, corte)
    assert [m for _, m in fic_tir.flujos] == [D("-1000"), D("60"), D("-2.40"), D("1030")]


def test_retiros_y_fecha_de_corte(sesion, portafolio, instrumentos):
    cuenta = instrumentos["Cuenta"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.APORTE, "1000", cuenta),
            _mov(portafolio, "2024-12-31", TipoMovimiento.RETIRO, "1100", cuenta),
            _val(portafolio, cuenta, "2024-12-31", "0"),
            # Posterior al corte: no debe contar.
            _mov(portafolio, "2025-03-01", TipoMovimiento.APORTE, "5000", cuenta),
        ]
    )
    sesion.flush()

    resultado = tir_portafolio(sesion, portafolio.id, d("2024-12-31"))
    assert resultado.tasa == pytest.approx(0.10)
    assert resultado.valor_final == 0


def test_valoracion_desactualizada(sesion, portafolio, instrumentos):
    cdt = instrumentos["CDT Banco A"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-02", TipoMovimiento.APORTE, "1000"),
            _mov(portafolio, "2024-01-02", TipoMovimiento.COMPRA, "1000", cdt),
            _val(portafolio, cdt, "2024-06-30", "1040"),
            _mov(portafolio, "2024-09-01", TipoMovimiento.COMPRA, "500", cdt),
        ]
    )
    sesion.flush()

    with pytest.raises(ValoracionFaltanteError, match="CDT Banco A"):
        tir_portafolio(sesion, portafolio.id, d("2024-12-31"))
