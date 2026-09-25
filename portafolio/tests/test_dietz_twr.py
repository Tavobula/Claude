"""Pruebas del núcleo: Dietz modificado y TWR.

Caso de referencia (calculado a mano):

    01-ene  valor 100.000
    16-ene  aporte 50.000; justo después el portafolio vale 154.000
    31-ene  valor 160.160

    TWR   = (154.000 - 50.000) / 100.000 * 160.160 / 154.000 - 1
          = 1,04 * 1,04 - 1 = 8,16 %
    Dietz = (160.160 - 100.000 - 50.000) / (100.000 + 50.000 * 15/30)
          = 10.160 / 125.000 = 8,128 %
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from portafolio.core.dietz import DenominadorInvalidoError, dietz_modificado
from portafolio.core.twr import anualizar, encadenar, twr
from portafolio.core.xirr import xirr

ENE1, ENE16, ENE31 = date(2024, 1, 1), date(2024, 1, 16), date(2024, 1, 31)


# ------------------------------------------------------------------ Dietz


def test_dietz_caso_de_referencia():
    r = dietz_modificado(100_000, 160_160, ENE1, ENE31, [(ENE16, 50_000)])
    assert r == pytest.approx(0.08128, abs=1e-12)


def test_dietz_con_retiro():
    # Retiro de 20.000 el día 10 de 30: peso 20/30.
    # (95.000 - 100.000 + 20.000) / (100.000 - 20.000 * 20/30) = 15.000 / 86.666,67
    r = dietz_modificado(100_000, 95_000, ENE1, ENE31, [(date(2024, 1, 11), -20_000)])
    assert r == pytest.approx(15_000 / (100_000 - 20_000 * 20 / 30), abs=1e-12)


def test_dietz_sin_flujos_es_rendimiento_simple():
    assert dietz_modificado(Decimal("200"), Decimal("210"), ENE1, ENE31) == pytest.approx(0.05)


def test_dietz_pesos_en_los_extremos():
    # Flujo el último día: peso 0, cuenta solo en el numerador.
    assert dietz_modificado(100, 160, ENE1, ENE31, [(ENE31, 50)]) == pytest.approx(0.10)
    # Flujo el día siguiente al inicio: peso 29/30.
    r = dietz_modificado(100, 160, ENE1, ENE31, [(date(2024, 1, 2), 50)])
    assert r == pytest.approx(10 / (100 + 50 * 29 / 30))


def test_dietz_rechaza_flujos_fuera_del_periodo():
    # El del día inicial ya está dentro del valor inicial.
    with pytest.raises(ValueError, match="fuera del periodo"):
        dietz_modificado(100, 110, ENE1, ENE31, [(ENE1, 10)])
    with pytest.raises(ValueError, match="fuera del periodo"):
        dietz_modificado(100, 110, ENE1, ENE31, [(date(2024, 2, 1), 10)])


def test_dietz_capital_no_positivo():
    # Retira casi todo al comienzo: el capital promedio queda negativo.
    with pytest.raises(DenominadorInvalidoError):
        dietz_modificado(100, 0, ENE1, ENE31, [(date(2024, 1, 2), -150)])


def test_dietz_periodo_vacio():
    assert dietz_modificado(0, 0, ENE1, ENE31) == 0.0


def test_dietz_aproxima_la_tir_del_periodo():
    """Dietz es una aproximación de primer orden de la TIR (no anualizada)."""
    flujos_activo = [(date(2024, 3, 1), 30_000), (date(2024, 5, 20), -10_000)]
    inicio, fin = date(2024, 1, 1), date(2024, 6, 30)
    v0, v1 = 100_000, 124_500
    r_dietz = dietz_modificado(v0, v1, inicio, fin, flujos_activo)

    flujos_inversionista = [(inicio, -v0), *[(f, -m) for f, m in flujos_activo], (fin, v1)]
    r_tir = (1 + xirr(flujos_inversionista)) ** ((fin - inicio).days / 365) - 1
    assert r_dietz == pytest.approx(r_tir, abs=5e-4)


# ------------------------------------------------------------------ TWR


def test_twr_caso_de_referencia_exacto():
    resultado = twr([(ENE1, 100_000), (ENE16, 154_000), (ENE31, 160_160)], [(ENE16, 50_000)])
    assert resultado.rendimiento == pytest.approx(0.0816, abs=1e-12)
    assert resultado.exacto
    assert [s.rendimiento for s in resultado.subperiodos] == pytest.approx([0.04, 0.04])


def test_twr_no_depende_del_tamano_de_los_aportes():
    """Dos inversionistas en el mismo activo, con aportes distintos: igual TWR, distinta TIR."""
    # El activo gana 4 % cada quincena.
    chico = twr([(ENE1, 100), (ENE16, 104 + 10), (ENE31, 114 * 1.04)], [(ENE16, 10)])
    grande = twr([(ENE1, 100), (ENE16, 104 + 900), (ENE31, 1004 * 1.04)], [(ENE16, 900)])
    assert chico.rendimiento == pytest.approx(grande.rendimiento)
    assert chico.rendimiento == pytest.approx(0.0816)

    d_chico = dietz_modificado(100, 114 * 1.04, ENE1, ENE31, [(ENE16, 10)])
    d_grande = dietz_modificado(100, 1004 * 1.04, ENE1, ENE31, [(ENE16, 900)])
    assert d_chico != pytest.approx(d_grande)


def test_twr_sin_flujos_es_rendimiento_simple():
    resultado = twr([(ENE1, 100), (ENE16, 90), (ENE31, 110)])
    assert resultado.rendimiento == pytest.approx(0.10)
    assert resultado.exacto


def test_twr_con_flujo_entre_valoraciones_es_aproximado():
    resultado = twr([(ENE1, 100_000), (ENE31, 160_160)], [(ENE16, 50_000)])
    assert not resultado.exacto
    assert resultado.rendimiento == pytest.approx(0.08128)  # un solo subperiodo = Dietz


def test_twr_ignora_flujos_fuera_del_rango():
    con = twr([(ENE1, 100), (ENE31, 110)], [(ENE1, 100), (date(2024, 2, 5), 50)])
    assert con.rendimiento == pytest.approx(0.10)


def test_twr_desordenado_y_con_decimal():
    resultado = twr(
        [(ENE31, Decimal("160160")), (ENE1, Decimal("100000")), (ENE16, Decimal("154000"))],
        [(ENE16, Decimal("50000"))],
    )
    assert resultado.rendimiento == pytest.approx(0.0816)


@pytest.mark.parametrize(
    "valoraciones",
    [[(ENE1, 100)], [(ENE1, 100), (ENE1, 110)]],
    ids=["una_valoracion", "fechas_repetidas"],
)
def test_twr_valoraciones_invalidas(valoraciones):
    with pytest.raises(ValueError):
        twr(valoraciones)


# ------------------------------------------------------------------ utilidades


def test_encadenar():
    assert encadenar([0.10, -0.10]) == pytest.approx(-0.01)
    assert encadenar([]) == 0.0


def test_anualizar():
    assert anualizar(0.21, 730) == pytest.approx(0.10)
    assert anualizar(0.10, 365) == pytest.approx(0.10)
    # 1 % en 30 días -> (1,01)^(365/30) - 1
    assert anualizar(0.01, 30) == pytest.approx(1.01 ** (365 / 30) - 1)
    with pytest.raises(ValueError):
        anualizar(0.1, 0)


def test_twr_diario_encadenado_coincide_con_rendimiento_total():
    """Sin flujos, partir el periodo en muchos cortes no cambia el resultado."""
    valor, puntos = 1000.0, []
    for dia in range(60):
        puntos.append((ENE1 + timedelta(days=dia), valor))
        valor *= 1.001 if dia % 3 else 0.998
    assert twr(puntos).rendimiento == pytest.approx(puntos[-1][1] / puntos[0][1] - 1)
