import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from portafolio.core.xirr import SinSolucionError, xirr, xnpv

CASOS_EXCEL = Path(__file__).parent / "casos" / "xirr_excel.csv"


def _cargar_casos():
    casos: dict[str, dict] = defaultdict(lambda: {"flujos": []})
    with CASOS_EXCEL.open(encoding="utf-8") as archivo:
        filas = (linea for linea in archivo if not linea.startswith("#"))
        for fila in csv.DictReader(filas):
            caso = casos[fila["caso"]]
            caso["esperado"] = float(fila["tir_excel"])
            caso["flujos"].append((date.fromisoformat(fila["fecha"]), Decimal(fila["monto"])))
    return [pytest.param(c["flujos"], c["esperado"], id=nombre) for nombre, c in casos.items()]


@pytest.mark.parametrize("flujos,esperado", _cargar_casos())
def test_coincide_con_excel(flujos, esperado):
    # Excel detiene XIRR con una precisión de 0.000001 % (1e-8); nuestro
    # resultado es más exacto, así que se compara con esa tolerancia.
    assert xirr(flujos) == pytest.approx(esperado, abs=1e-8)


def test_vpn_es_cero_en_la_tir():
    flujos = [(date(2024, 1, 15), -5_000_000), (date(2024, 7, 3), 200_000), (date(2025, 2, 1), 5_300_000)]
    assert xnpv(xirr(flujos), flujos) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("tasa", [-0.95, -0.3, 0.0, 0.08, 0.5, 3.0, 25.0])
def test_recupera_tasa_conocida(tasa):
    """Construye flujos cuyo VPN es exactamente cero a ``tasa``."""
    inicio = date(2022, 3, 10)
    flujos = [(inicio, -1000.0), (inicio + timedelta(days=100), -250.0), (inicio + timedelta(days=200), 80.0)]
    fin = inicio + timedelta(days=500)
    vpn_parcial = xnpv(tasa, flujos)
    flujos.append((fin, -vpn_parcial * (1 + tasa) ** (500 / 365)))
    assert xirr(flujos) == pytest.approx(tasa, rel=1e-9, abs=1e-12)


def test_orden_de_flujos_no_importa():
    flujos = [(date(2024, 12, 31), 1100), (date(2024, 1, 1), -1000), (date(2024, 6, 1), -50)]
    assert xirr(flujos) == pytest.approx(xirr(sorted(flujos)))


def test_acepta_decimal():
    flujos = [(date(2023, 1, 1), Decimal("-1000.00")), (date(2024, 1, 1), Decimal("1100.00"))]
    assert xirr(flujos) == pytest.approx(0.1)


def test_estimado_lejano_cae_en_biseccion():
    flujos = [(date(2023, 1, 1), -100), (date(2023, 1, 2), 200)]  # TIR enorme en un día
    tasa = xirr(flujos, estimado=-0.99)
    assert math.isfinite(tasa)
    assert xnpv(tasa, flujos) == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize(
    "flujos",
    [
        [(date(2024, 1, 1), -100)],
        [(date(2024, 1, 1), -100), (date(2024, 6, 1), -50)],
        [(date(2024, 1, 1), 100), (date(2024, 6, 1), 50)],
    ],
    ids=["un_flujo", "solo_negativos", "solo_positivos"],
)
def test_sin_solucion(flujos):
    with pytest.raises(SinSolucionError):
        xirr(flujos)
