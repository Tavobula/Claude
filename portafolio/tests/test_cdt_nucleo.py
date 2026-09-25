"""CDT, retención y GMF en el núcleo (sin base de datos)."""

from datetime import date
from decimal import Decimal as D

import pytest

from portafolio.core.calendario import sumar_meses
from portafolio.core.cdt import (
    Modalidad,
    Periodicidad,
    TerminosCDT,
    TipoTasa,
    calendario_pagos,
    causacion,
    interes_por_dias,
    tasa_efectiva_anual,
)
from portafolio.core.impuestos import gmf, retencion_rendimientos
from portafolio.core.xirr import xirr

UN_ANIO = TerminosCDT(D("10000000"), date(2025, 3, 3), date(2026, 3, 3), D("0.10"))


# ------------------------------------------------------------------ fechas


@pytest.mark.parametrize(
    "fecha,meses,esperado",
    [
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2025, 1, 31), 2, date(2025, 3, 31)),
        (date(2025, 11, 15), 3, date(2026, 2, 15)),
        (date(2025, 3, 31), -1, date(2025, 2, 28)),
    ],
)
def test_sumar_meses(fecha, meses, esperado):
    assert sumar_meses(fecha, meses) == esperado


# ------------------------------------------------------------------ tasas


def test_tasa_efectiva_anual_pasa_igual():
    assert tasa_efectiva_anual(D("0.1"), TipoTasa.EFECTIVA_ANUAL, Periodicidad.MENSUAL) == D("0.1")


def test_nominal_mes_vencido():
    ea = tasa_efectiva_anual(D("0.12"), TipoTasa.NOMINAL, Periodicidad.MENSUAL)
    assert float(ea) == pytest.approx(1.01**12 - 1, abs=1e-15)


def test_nominal_trimestre_vencido():
    ea = tasa_efectiva_anual(D("0.10"), TipoTasa.NOMINAL, Periodicidad.TRIMESTRAL)
    assert float(ea) == pytest.approx(1.025**4 - 1, abs=1e-15)


def test_nominal_trimestre_anticipado():
    # 10 % N.T.A.: 2,5 % trimestral anticipado = 2,5/97,5 % vencido.
    ea = tasa_efectiva_anual(D("0.10"), TipoTasa.NOMINAL, Periodicidad.TRIMESTRAL, Modalidad.ANTICIPADA)
    assert float(ea) == pytest.approx((1 + 0.025 / 0.975) ** 4 - 1, abs=1e-15)
    assert float(ea) > 1.025**4 - 1  # anticipada rinde más que vencida


def test_nominal_sin_periodicidad():
    with pytest.raises(ValueError, match="periodicidad"):
        tasa_efectiva_anual(D("0.1"), TipoTasa.NOMINAL, Periodicidad.AL_VENCIMIENTO)


# ------------------------------------------------------------------ calendario de pagos


def test_un_anio_al_vencimiento():
    (pago,) = calendario_pagos(UN_ANIO)
    assert pago.dias == 365
    assert pago.interes == D("1000000.00")
    assert pago.capital == D("10000000")
    assert pago.fecha_pago == date(2026, 3, 3)  # martes hábil


def test_base_360():
    t = TerminosCDT(D("10000000"), date(2025, 3, 3), date(2026, 3, 3), D("0.10"), base_dias=360)
    (pago,) = calendario_pagos(t)
    assert pago.interes == (D("10000000") * (D("1.1") ** (D(365) / D(360)) - 1)).quantize(D("0.01"))
    assert pago.interes > D("1000000")


def test_mensual_desde_fin_de_mes_con_festivos():
    t = TerminosCDT(
        D("10000000"), date(2025, 1, 31), date(2025, 7, 31), D("0.12"), TipoTasa.NOMINAL, Periodicidad.MENSUAL
    )
    periodos = calendario_pagos(t)
    assert [p.fin for p in periodos] == [
        date(2025, 2, 28),
        date(2025, 3, 31),  # vuelve al 31: se suma desde la emisión
        date(2025, 4, 30),
        date(2025, 5, 31),
        date(2025, 6, 30),
        date(2025, 7, 31),
    ]
    pagos = {p.fin: p.fecha_pago for p in periodos}
    assert pagos[date(2025, 5, 31)] == date(2025, 6, 3)  # sábado; el lunes 2 es festivo
    assert pagos[date(2025, 6, 30)] == date(2025, 7, 1)  # San Pedro
    assert sum(p.dias for p in periodos) == (t.fecha_vencimiento - t.fecha_emision).days
    assert [p.capital for p in periodos[:-1]] == [0] * 5


def test_ultimo_periodo_corto():
    t = TerminosCDT(D("1000"), date(2025, 1, 15), date(2025, 5, 1), D("0.1"), periodicidad=Periodicidad.TRIMESTRAL)
    assert [(p.inicio, p.fin) for p in calendario_pagos(t)] == [
        (date(2025, 1, 15), date(2025, 4, 15)),
        (date(2025, 4, 15), date(2025, 5, 1)),
    ]


def test_tir_de_los_pagos_es_la_tasa_efectiva():
    """Con pagos en las fechas nominales, la TIR de un CDT es su tasa E.A."""
    t = TerminosCDT(
        D("50000000"), date(2025, 2, 10), date(2026, 8, 10), D("0.09"), TipoTasa.NOMINAL, Periodicidad.TRIMESTRAL
    )
    flujos = [(t.fecha_emision, -t.capital)] + [(p.fin, p.interes + p.capital) for p in calendario_pagos(t)]
    assert xirr(flujos) == pytest.approx(float(t.tasa_ea), abs=1e-7)


def test_anticipada_no_se_proyecta():
    t = TerminosCDT(D("1000"), date(2025, 1, 1), date(2026, 1, 1), D("0.1"), modalidad=Modalidad.ANTICIPADA)
    with pytest.raises(NotImplementedError):
        calendario_pagos(t)


@pytest.mark.parametrize(
    "cambios",
    [
        {"fecha_vencimiento": date(2025, 3, 3)},
        {"capital": D(0)},
        {"base_dias": 366},
    ],
)
def test_terminos_invalidos(cambios):
    datos = dict(capital=D("1000"), fecha_emision=date(2025, 3, 3), fecha_vencimiento=date(2026, 3, 3), tasa=D("0.1"))
    with pytest.raises(ValueError):
        TerminosCDT(**{**datos, **cambios})


# ------------------------------------------------------------------ causación


def test_causacion_a_lo_largo_de_la_vida():
    assert causacion(UN_ANIO, date(2025, 3, 2)).valor == 0
    assert causacion(UN_ANIO, date(2025, 3, 3)).valor == D("10000000")
    mitad = causacion(UN_ANIO, date(2025, 9, 1))  # 182 días
    assert mitad.interes_causado == (D("10000000") * (D("1.1") ** (D(182) / D(365)) - 1)).quantize(D("0.01"))
    assert causacion(UN_ANIO, date(2026, 3, 2)).interes_causado < D("1000000")
    assert causacion(UN_ANIO, date(2026, 3, 3)).valor == 0  # se pagó ese día


def test_causacion_con_vencimiento_en_festivo():
    # Vence el lunes festivo 12-ene-2026; se paga el martes 13 sin intereses extra.
    t = TerminosCDT(D("1000000"), date(2025, 1, 13), date(2026, 1, 12), D("0.1"))
    (pago,) = calendario_pagos(t)
    assert pago.fecha_pago == date(2026, 1, 13)
    festivo = causacion(t, date(2026, 1, 12))
    assert festivo.interes_causado == pago.interes
    assert festivo.valor == pago.interes + pago.capital
    assert causacion(t, date(2026, 1, 13)).valor == 0


def test_causacion_con_pagos_periodicos():
    t = TerminosCDT(
        D("10000000"), date(2025, 1, 31), date(2025, 7, 31), D("0.12"), TipoTasa.NOMINAL, Periodicidad.MENSUAL
    )
    assert causacion(t, date(2025, 2, 28)).valor == D("10000000")  # pagado ese día
    sabado = causacion(t, date(2025, 5, 31))  # corte sábado, se paga el 3-jun
    mayo = calendario_pagos(t)[3]
    assert sabado.interes_causado == mayo.interes
    # El 2-jun sigue pendiente el de mayo y se suman 2 días de junio.
    lunes = causacion(t, date(2025, 6, 2))
    assert lunes.interes_causado > mayo.interes
    # El 3-jun ya se pagó mayo: quedan los 3 días de junio causados.
    assert causacion(t, date(2025, 6, 3)).interes_causado == interes_por_dias(t.capital, t.tasa_ea, 3, 365)


# ------------------------------------------------------------------ impuestos


def test_retencion():
    assert retencion_rendimientos(D("1000000"), D("0.04")) == D("40000.00")
    assert retencion_rendimientos(D("1000000"), D("0.04"), D("0.5")) == D("20000.00")
    assert retencion_rendimientos(D("333.33"), D("0.04")) == D("13.33")
    assert retencion_rendimientos(D(0), D("0.04")) == 0
    with pytest.raises(ValueError):
        retencion_rendimientos(D("100"), D("0.04"), D("1.5"))


def test_gmf_sin_exencion():
    (cargo,) = gmf([(date(2025, 1, 10), D("1000000"))], D("0.004"))
    assert (cargo.exento, cargo.gmf) == (0, D("4000.00"))


def test_gmf_con_exencion_mensual():
    tope = D("17000000")
    retiros = [
        (date(2025, 2, 3), D("5000000")),  # otro mes, se lista primero a propósito
        (date(2025, 1, 20), D("10000000")),
        (date(2025, 1, 10), D("10000000")),
    ]
    cargos = gmf(retiros, D("0.004"), tope)
    assert [c.fecha for c in cargos] == [f for f, _ in retiros]  # conserva el orden
    feb, ene20, ene10 = cargos
    assert (ene10.exento, ene10.gmf) == (D("10000000"), 0)
    assert (ene20.exento, ene20.gmf) == (D("7000000"), D("12000.00"))
    assert (feb.exento, feb.gmf) == (D("5000000"), 0)  # el tope se reinicia


def test_gmf_monto_negativo():
    with pytest.raises(ValueError):
        gmf([(date(2025, 1, 1), D("-1"))], D("0.004"))
