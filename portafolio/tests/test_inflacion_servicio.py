from datetime import timedelta
from decimal import Decimal as D

import pytest

from conftest import d
from portafolio.core.inflacion import ValorNoDisponibleError
from portafolio.data.modelos import Movimiento, Serie, TipoMovimiento, Valoracion
from portafolio.data.repositorios import SerieNoEncontradaError
from portafolio.services import series
from portafolio.services.inflacion import (
    dietz_real_portafolio,
    en_pesos_de,
    tir_real_instrumento,
    tir_real_portafolio,
    twr_real_portafolio,
)
from portafolio.sources.base import Observacion
from portafolio.sources.catalogo import IBR_1M, IPC, UVR


def _uvr(sesion, desde, hasta, tasa=0.05):
    dias = (hasta - desde).days
    return series.guardar_observaciones(
        sesion,
        UVR,
        [Observacion(desde + timedelta(days=t), D(repr(300 * (1 + tasa) ** (t / 365)))) for t in range(dias + 1)],
    )


@pytest.fixture
def portafolio_10(sesion, portafolio, instrumentos):
    """Gana 10 % nominal en 2023 (365 días)."""
    fic = instrumentos["FIC Renta Fija"]
    for m in [
        Movimiento(fecha=d("2023-01-01"), tipo=TipoMovimiento.APORTE, monto=D("1000000"), instrumento_id=fic.id),
        Valoracion(fecha=d("2023-01-01"), valor=D("1000000"), instrumento_id=fic.id),
        Valoracion(fecha=d("2024-01-01"), valor=D("1100000"), instrumento_id=fic.id),
    ]:
        m.usuario_id, m.portafolio_id = portafolio.usuario_id, portafolio.id
        sesion.add(m)
    sesion.flush()
    return fic


# ------------------------------------------------------------------ carga de series


def test_guardar_observaciones(sesion):
    r = series.guardar_observaciones(sesion, UVR, [Observacion(d("2025-01-01"), D("376.1")), Observacion(d("2025-01-02"), D("376.2"))])
    assert (r.nuevas, r.actualizadas, r.sin_cambio) == (2, 0, 0)
    r = series.guardar_observaciones(sesion, UVR, [Observacion(d("2025-01-02"), D("376.25")), Observacion(d("2025-01-01"), D("376.1"))])
    assert (r.nuevas, r.actualizadas, r.sin_cambio) == (0, 1, 1)
    assert series.ultima_fecha(sesion, "UVR") == d("2025-01-02")
    assert series.ultima_fecha(sesion, "IPC") is None


def test_serie_mensual_se_normaliza(sesion):
    series.guardar_observaciones(sesion, IPC, [Observacion(d("2025-01-31"), D("146.1"))])
    serie = sesion.query(Serie).filter_by(codigo="IPC").one()
    assert serie.frecuencia.value == "MENSUAL"
    assert serie.valores[0].fecha == d("2025-01-01")


def test_valores_no_positivos(sesion):
    with pytest.raises(ValueError, match="no positivo"):
        series.guardar_observaciones(sesion, UVR, [Observacion(d("2025-01-01"), D("0"))])
    # Una tasa sí puede ser cero o negativa.
    assert series.guardar_observaciones(sesion, IBR_1M, [Observacion(d("2025-01-01"), D("-0.001"))]).nuevas == 1


def test_actualizar_desde_fuente(sesion):
    class Falso:
        definicion = UVR

        def descargar(self, desde, hasta):
            return [Observacion(desde, D("1")), Observacion(hasta, D("2"))]

    r = series.actualizar_desde_fuente(sesion, Falso(), d("2025-01-01"), d("2025-01-05"))
    assert (r.nuevas, r.desde, r.hasta) == (2, d("2025-01-01"), d("2025-01-05"))


# ------------------------------------------------------------------ rendimientos reales


def test_tir_real(sesion, portafolio, portafolio_10):
    _uvr(sesion, d("2023-01-01"), d("2024-01-01"))
    r = tir_real_portafolio(sesion, portafolio.id, d("2024-01-01"))
    assert r.nominal.tasa == pytest.approx(0.10)
    assert r.tasa_real == pytest.approx(1.10 / 1.05 - 1, abs=1e-9)
    assert r.flujos_reales[0][1] == pytest.approx(D("-1050000"), abs=D("0.001"))
    assert tir_real_instrumento(sesion, portafolio_10.id, d("2024-01-01")).tasa_real == pytest.approx(r.tasa_real)


def test_twr_y_dietz_reales(sesion, portafolio, portafolio_10):
    _uvr(sesion, d("2023-01-01"), d("2024-01-01"))
    r = twr_real_portafolio(sesion, portafolio.id, d("2023-01-01"), d("2024-01-01"))
    assert r.inflacion == pytest.approx(0.05, abs=1e-12)
    assert r.inflacion_anualizada == pytest.approx(0.05, abs=1e-12)
    assert r.real == pytest.approx(1.10 / 1.05 - 1, abs=1e-12)
    assert r.real_anualizado == pytest.approx(r.real)
    assert dietz_real_portafolio(sesion, portafolio.id, d("2023-01-01"), d("2024-01-01")).real == pytest.approx(r.real)


def test_menos_de_un_anio_no_se_anualiza(sesion, portafolio, portafolio_10):
    _uvr(sesion, d("2023-01-01"), d("2024-01-01"))
    r = twr_real_portafolio(sesion, portafolio.id, d("2023-01-01"), d("2023-07-01"))
    assert r.real_anualizado is None and r.inflacion_anualizada is None


def test_con_ipc_mensual(sesion, portafolio, portafolio_10):
    series.guardar_observaciones(
        sesion, IPC, [Observacion(d("2023-01-01"), D("100")), Observacion(d("2024-01-01"), D("106"))]
    )
    r = twr_real_portafolio(sesion, portafolio.id, d("2023-01-01"), d("2024-01-01"), serie="IPC")
    assert r.inflacion == pytest.approx(0.06)
    assert r.real == pytest.approx(1.10 / 1.06 - 1)


def test_errores_de_serie(sesion, portafolio, portafolio_10):
    with pytest.raises(SerieNoEncontradaError, match="series importar UVR"):
        tir_real_portafolio(sesion, portafolio.id, d("2024-01-01"))
    _uvr(sesion, d("2023-01-01"), d("2023-12-31"))  # falta el día de corte
    with pytest.raises(ValorNoDisponibleError, match="2024-01-01"):
        tir_real_portafolio(sesion, portafolio.id, d("2024-01-01"))


def test_en_pesos_de(sesion):
    _uvr(sesion, d("2023-01-01"), d("2024-01-01"))
    assert en_pesos_de(sesion, D("1050000"), d("2024-01-01"), d("2023-01-01")) == pytest.approx(D("1000000"), abs=D("0.001"))
