"""TWR y Dietz desde la base de datos."""

from datetime import date

import pytest

from conftest import D, d
from portafolio.data.modelos import Movimiento, TipoMovimiento, Valoracion
from portafolio.services.rendimientos import (
    ValoracionFaltanteError,
    dietz_instrumento,
    dietz_portafolio,
    twr_instrumento,
    twr_portafolio,
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


@pytest.fixture
def caso_referencia(sesion, portafolio, instrumentos):
    """El caso de test_dietz_twr.py, registrado como movimientos y valoraciones del FIC."""
    fic = instrumentos["FIC Renta Fija"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.APORTE, "100000", fic),
            _val(portafolio, fic, "2024-01-01", "100000"),
            _mov(portafolio, "2024-01-16", TipoMovimiento.APORTE, "50000", fic),
            _val(portafolio, fic, "2024-01-16", "154000"),
            _val(portafolio, fic, "2024-01-31", "160160"),
        ]
    )
    sesion.flush()
    return fic


def test_twr_portafolio_exacto(sesion, portafolio, caso_referencia):
    r = twr_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    assert r.metodo == "TWR"
    assert r.rendimiento == pytest.approx(0.0816, abs=1e-12)
    assert r.exacto
    assert (r.valor_inicial, r.valor_final, r.flujo_neto) == (D("100000"), D("160160"), D("50000"))
    assert [(s.inicio, s.fin) for s in r.subperiodos] == [
        (d("2024-01-01"), d("2024-01-16")),
        (d("2024-01-16"), d("2024-01-31")),
    ]
    assert r.anualizado is None  # menos de un año


def test_dietz_portafolio(sesion, portafolio, caso_referencia):
    r = dietz_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    assert r.metodo == "DIETZ"
    assert r.rendimiento == pytest.approx(0.08128, abs=1e-12)
    assert not r.exacto  # hubo un flujo a mitad de periodo


def test_twr_instrumento_igual_al_del_portafolio(sesion, portafolio, caso_referencia):
    r = twr_instrumento(sesion, caso_referencia.id, d("2024-01-01"), d("2024-01-31"))
    assert r.rendimiento == pytest.approx(0.0816, abs=1e-12)


def test_periodo_desde_antes_del_primer_aporte(sesion, portafolio, caso_referencia):
    """Si el portafolio no existía al inicio, el primer subperiodo arranca en 0 y aporta 0 %."""
    r = twr_portafolio(sesion, portafolio.id, d("2023-12-31"), d("2024-01-31"))
    assert r.rendimiento == pytest.approx(0.0816, abs=1e-12)
    assert r.valor_inicial == 0


def test_instrumento_que_paga_intereses(sesion, portafolio, instrumentos):
    """Los intereses pagados salen del instrumento y cuentan como rendimiento."""
    cdt = instrumentos["CDT Banco A"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.COMPRA, "1000", cdt),
            _val(portafolio, cdt, "2024-01-01", "1000"),
            _mov(portafolio, "2024-07-01", TipoMovimiento.INTERES, "60", cdt),
            _mov(portafolio, "2024-07-01", TipoMovimiento.IMPUESTO, "2.40", cdt),
            _val(portafolio, cdt, "2024-07-01", "1000"),
            _val(portafolio, cdt, "2024-12-31", "1030"),
        ]
    )
    sesion.flush()

    r = twr_instrumento(sesion, cdt.id, d("2024-01-01"), d("2024-12-31"))
    # Primer semestre: salen 57,60 netos de retención -> 5,76 %. Segundo: 3 %.
    assert [s.rendimiento for s in r.subperiodos] == pytest.approx([0.0576, 0.03])
    assert r.rendimiento == pytest.approx(1.0576 * 1.03 - 1)
    assert r.flujo_neto == D("-57.60")


def test_omite_fechas_sin_valoracion_completa(sesion, portafolio, caso_referencia, instrumentos):
    """El 16-ene el CDT tiene un movimiento sin valorar: ese corte se omite y el TWR se aproxima."""
    cdt = instrumentos["CDT Banco A"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.APORTE, "1000", cdt),
            _val(portafolio, cdt, "2024-01-01", "1000"),
            _mov(portafolio, "2024-01-10", TipoMovimiento.COMISION, "5", cdt),
            _val(portafolio, cdt, "2024-01-31", "1000"),
        ]
    )
    sesion.flush()

    r = twr_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    assert r.fechas_omitidas == [date(2024, 1, 16)]
    assert not r.exacto
    assert len(r.subperiodos) == 1


def test_usa_valoracion_anterior_si_no_hubo_movimientos(sesion, portafolio, caso_referencia, instrumentos):
    """Un instrumento quieto conserva su última valoración en los cortes intermedios."""
    cuenta = instrumentos["Cuenta"]
    sesion.add_all(
        [
            _mov(portafolio, "2024-01-01", TipoMovimiento.APORTE, "20000", cuenta),
            _val(portafolio, cuenta, "2024-01-01", "20000"),
            _val(portafolio, cuenta, "2024-01-31", "20000"),
        ]
    )
    sesion.flush()

    r = twr_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    assert r.exacto and not r.fechas_omitidas
    # 16-ene: 174.000 = 154.000 del FIC + 20.000 de la cuenta.
    assert r.subperiodos[0].valor_final == 174_000
    assert r.rendimiento == pytest.approx((124_000 / 120_000) * (180_160 / 174_000) - 1)


def test_anualiza_periodos_de_un_anio_o_mas(sesion, portafolio, instrumentos):
    fic = instrumentos["FIC Renta Fija"]
    sesion.add_all(
        [
            _mov(portafolio, "2023-01-01", TipoMovimiento.APORTE, "1000", fic),
            _val(portafolio, fic, "2023-01-01", "1000"),
            _val(portafolio, fic, "2024-12-31", "1210"),  # 730 días
        ]
    )
    sesion.flush()

    r = twr_portafolio(sesion, portafolio.id, d("2023-01-01"), d("2024-12-31"))
    assert r.rendimiento == pytest.approx(0.21)
    assert r.anualizado == pytest.approx(0.10)
    assert dietz_instrumento(sesion, fic.id, d("2023-01-01"), d("2024-12-31")).anualizado == pytest.approx(0.10)


def test_errores(sesion, portafolio, caso_referencia):
    with pytest.raises(ValueError, match="posterior"):
        twr_portafolio(sesion, portafolio.id, d("2024-01-31"), d("2024-01-31"))
    # Aporte del 5-feb sin valoración posterior: el valor final no se puede calcular.
    sesion.add(_mov(portafolio, "2024-02-05", TipoMovimiento.APORTE, "1", caso_referencia))
    sesion.flush()
    with pytest.raises(ValoracionFaltanteError):
        dietz_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-02-10"))
