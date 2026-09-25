from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from portafolio.core.inflacion import (
    Frecuencia,
    Indice,
    ValorNoDisponibleError,
    deflactar,
    flujos_reales,
    inflacion,
    rendimiento_real,
)
from portafolio.core.xirr import xirr


def uvr_constante(desde: date, hasta: date, tasa: float = 0.05, base: float = 300.0) -> Indice:
    """UVR sintética que crece a ``tasa`` efectiva anual (base 365)."""
    dias = (hasta - desde).days
    return Indice.crear(
        "UVR",
        Frecuencia.DIARIA,
        [(desde + timedelta(days=t), D(repr(base * (1 + tasa) ** (t / 365)))) for t in range(dias + 1)],
    )


def test_indice_diario():
    indice = Indice.crear("UVR", Frecuencia.DIARIA, [(date(2025, 1, 2), D("2")), (date(2025, 1, 1), D("1"))])
    assert indice.fechas == (date(2025, 1, 1), date(2025, 1, 2))
    assert indice.valor_en(date(2025, 1, 2)) == D("2")
    with pytest.raises(ValorNoDisponibleError, match="2025-01-03.*2025-01-01 a 2025-01-02"):
        indice.valor_en(date(2025, 1, 3))


def test_indice_mensual_usa_el_mes_de_la_fecha():
    ipc = Indice.crear("IPC", Frecuencia.MENSUAL, [(date(2025, 1, 31), D("100")), (date(2025, 2, 1), D("101"))])
    assert ipc.fechas == (date(2025, 1, 1), date(2025, 2, 1))  # normalizado al día 1
    assert ipc.valor_en(date(2025, 1, 15)) == D("100")
    assert ipc.valor_en(date(2025, 2, 28)) == D("101")
    with pytest.raises(ValorNoDisponibleError, match="2025-03"):
        ipc.valor_en(date(2025, 3, 1))


def test_indice_invalido():
    with pytest.raises(ValueError, match="no positivo"):
        Indice.crear("UVR", Frecuencia.DIARIA, [(date(2025, 1, 1), D("0"))])
    with pytest.raises(ValueError, match="distintos"):
        Indice.crear("UVR", Frecuencia.DIARIA, [(date(2025, 1, 1), D("1")), (date(2025, 1, 1), D("2"))])
    with pytest.raises(ValorNoDisponibleError, match="no tiene datos para 2025-01-01"):
        Indice.crear("UVR", Frecuencia.DIARIA, []).valor_en(date(2025, 1, 1))


def test_inflacion_y_deflactar():
    ipc = Indice.crear("IPC", Frecuencia.MENSUAL, [(date(2024, 1, 1), D("100")), (date(2025, 1, 1), D("105"))])
    assert inflacion(ipc, date(2024, 1, 10), date(2025, 1, 20)) == pytest.approx(0.05)
    # 1.050.000 de enero de 2025 valen 1.000.000 de enero de 2024.
    assert deflactar(D("1050000"), ipc, date(2025, 1, 5), date(2024, 1, 5)) == D("1000000")
    assert deflactar(D("1000000"), ipc, date(2024, 1, 5), date(2025, 1, 5)) == D("1050000")


def test_fisher():
    assert rendimiento_real(0.10, 0.05) == pytest.approx(1.10 / 1.05 - 1)
    assert rendimiento_real(0.03, 0.05) < 0


def test_tir_real_con_inflacion_constante_cumple_fisher():
    """Con inflación constante, la TIR de los flujos deflactados es exactamente Fisher."""
    inicio, fin = date(2023, 1, 1), date(2025, 6, 30)
    uvr = uvr_constante(inicio, fin, tasa=0.05)
    flujos = [
        (inicio, D("-1000000")),
        (date(2023, 7, 19), D("-250000")),
        (date(2024, 3, 2), D("80000")),
        (fin, D("1400000")),
    ]
    nominal = xirr(flujos)
    real = xirr(flujos_reales(flujos, uvr, fin))
    assert real == pytest.approx(rendimiento_real(nominal, 0.05), abs=1e-9)
    # La fecha base no cambia la TIR real.
    assert xirr(flujos_reales(flujos, uvr, inicio)) == pytest.approx(real, abs=1e-9)
