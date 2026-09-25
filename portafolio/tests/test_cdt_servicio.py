"""CDT, retención y GMF desde la base de datos."""

import io
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select

from conftest import d
from portafolio.core.cdt import Periodicidad
from portafolio.data.modelos import (
    CondicionCDT,
    Movimiento,
    Parametro,
    TipoMovimiento,
    Valoracion,
)
from portafolio.data.repositorios import ParametroNoDefinidoError
from portafolio.services.cdt import (
    CDTSinCondicionesError,
    estado_cdt,
    proyectar_cdt,
    sincronizar_cdt,
)
from portafolio.services.csv_io import ErrorImportacion, importar_parametros
from portafolio.services.impuestos import gmf_cuenta
from portafolio.services.rendimientos import tir_instrumento, twr_instrumento

EJEMPLO = Path(__file__).resolve().parents[1] / "datos" / "parametros_ejemplo.csv"


def _parametro(sesion, nombre, valor, desde="2000-01-01"):
    sesion.add(Parametro(nombre=nombre, vigente_desde=d(desde), valor=D(valor)))


@pytest.fixture
def retencion(sesion):
    _parametro(sesion, "retencion_rendimientos_cdt", "0.04")
    sesion.flush()


@pytest.fixture
def cdt(sesion, portafolio, instrumentos):
    """10 millones al 10 % E.A. a un año, del 3-mar-2025 al 3-mar-2026."""
    instrumento = instrumentos["CDT Banco A"]
    sesion.add(
        CondicionCDT(
            instrumento_id=instrumento.id,
            usuario_id=portafolio.usuario_id,
            portafolio_id=portafolio.id,
            capital=D("10000000"),
            fecha_emision=d("2025-03-03"),
            fecha_vencimiento=d("2026-03-03"),
            tasa=D("0.10"),
        )
    )
    sesion.flush()
    return instrumento


def test_proyeccion(sesion, cdt, retencion):
    (pago,) = proyectar_cdt(sesion, cdt.id)
    assert pago.periodo.interes == D("1000000.00")
    assert pago.retencion == D("40000.00")
    assert pago.total_recibido == D("10960000.00")


def test_estado(sesion, cdt, retencion):
    estado = estado_cdt(sesion, cdt.id, d("2025-09-01"))
    assert estado.valor_bruto == D("10486719.23")
    assert estado.retencion_estimada == D("19468.77")
    assert estado.valor_neto_estimado == D("10467250.46")


def test_sincronizar_y_rendimientos(sesion, cdt, retencion):
    resumen = sincronizar_cdt(sesion, cdt.id, d("2026-03-31"))
    movimientos = sesion.scalars(
        select(Movimiento).where(Movimiento.instrumento_id == cdt.id).order_by(Movimiento.fecha, Movimiento.id)
    ).all()
    assert [(m.fecha, m.tipo, m.monto) for m in movimientos] == [
        (date(2025, 3, 3), TipoMovimiento.COMPRA, D("10000000")),
        (date(2026, 3, 3), TipoMovimiento.INTERES, D("1000000.00")),
        (date(2026, 3, 3), TipoMovimiento.IMPUESTO, D("40000.00")),
        (date(2026, 3, 3), TipoMovimiento.VENTA, D("10000000")),
    ]
    # Emisión + 12 fines de mes (mar-2025 a feb-2026) + vencimiento.
    assert resumen.movimientos_creados == 4
    assert resumen.valoraciones_creadas == 14

    # Rendimiento neto de retención: 10 % x (1 - 4 %) = 9,6 %.
    assert tir_instrumento(sesion, cdt.id, d("2026-03-31")).tasa == pytest.approx(0.096, abs=1e-9)
    twr = twr_instrumento(sesion, cdt.id, d("2025-03-03"), d("2026-03-03"))
    assert twr.rendimiento == pytest.approx(0.096, abs=1e-12)
    assert twr.exacto and len(twr.subperiodos) == 13

    # Idempotente.
    otra = sincronizar_cdt(sesion, cdt.id, d("2026-03-31"))
    assert (otra.movimientos_creados, otra.valoraciones_creadas) == (0, 0)


def test_sincronizar_parcial_y_luego_completar(sesion, cdt, retencion):
    parcial = sincronizar_cdt(sesion, cdt.id, d("2025-05-15"))
    # Emisión, fin de marzo, fin de abril y el 15-may.
    assert (parcial.movimientos_creados, parcial.valoraciones_creadas) == (1, 4)
    resto = sincronizar_cdt(sesion, cdt.id, d("2026-12-31"))
    assert resto.movimientos_creados == 3


def test_no_reemplaza_valoraciones_manuales(sesion, portafolio, cdt, retencion):
    sesion.add(
        Valoracion(
            usuario_id=portafolio.usuario_id,
            portafolio_id=portafolio.id,
            instrumento_id=cdt.id,
            fecha=d("2025-03-31"),
            valor=D("10070000"),  # del extracto
        )
    )
    sesion.flush()
    sincronizar_cdt(sesion, cdt.id, d("2025-04-30"))
    manual = sesion.scalar(select(Valoracion).where(Valoracion.instrumento_id == cdt.id, Valoracion.fecha == d("2025-03-31")))
    assert manual.valor == D("10070000")


def test_sin_compra(sesion, cdt, retencion):
    assert sincronizar_cdt(sesion, cdt.id, d("2025-03-10"), incluir_compra=False).movimientos_creados == 0


def test_base_dias_desde_parametro(sesion, cdt, retencion):
    _parametro(sesion, "base_dias", "360")
    sesion.flush()
    (pago,) = proyectar_cdt(sesion, cdt.id)
    assert pago.periodo.interes > D("1000000")


def test_pagos_periodicos(sesion, cdt, retencion):
    condicion = sesion.get(CondicionCDT, cdt.id)
    condicion.periodicidad = Periodicidad.TRIMESTRAL
    sesion.flush()
    pagos = proyectar_cdt(sesion, cdt.id)
    assert len(pagos) == 4
    sincronizar_cdt(sesion, cdt.id, d("2026-03-31"))
    intereses = sesion.scalars(
        select(Movimiento).where(Movimiento.instrumento_id == cdt.id, Movimiento.tipo == TipoMovimiento.INTERES)
    ).all()
    assert [m.fecha for m in intereses] == [p.periodo.fecha_pago for p in pagos]
    # La retención se descuenta de cada cupón, así que el neto compuesto no es
    # 0,96 x 10 %: es (1 + 0,96 x i_trimestral)^4 - 1 ≈ 9,586 %.
    esperado = (1 + 0.96 * (1.1**0.25 - 1)) ** 4 - 1
    assert tir_instrumento(sesion, cdt.id, d("2026-03-31")).tasa == pytest.approx(esperado, abs=1e-4)


def test_errores(sesion, portafolio, instrumentos, cdt):
    with pytest.raises(ParametroNoDefinidoError, match="retencion"):
        proyectar_cdt(sesion, cdt.id)
    with pytest.raises(CDTSinCondicionesError, match="FIC"):
        proyectar_cdt(sesion, instrumentos["FIC Renta Fija"].id)
    with pytest.raises(ValueError, match="no es un CDT"):
        sincronizar_cdt(sesion, instrumentos["FIC Renta Fija"].id, d("2025-12-31"))


# ------------------------------------------------------------------ GMF


def _retiro(p, cuenta, fecha, monto):
    return Movimiento(
        usuario_id=p.usuario_id,
        portafolio_id=p.id,
        instrumento_id=cuenta.id,
        fecha=d(fecha),
        tipo=TipoMovimiento.RETIRO,
        monto=D(monto),
    )


@pytest.fixture
def parametros_gmf(sesion):
    _parametro(sesion, "gmf_tarifa", "0.004")
    _parametro(sesion, "gmf_tope_exento_uvt", "350")
    _parametro(sesion, "uvt", "49799", "2025-01-01")
    sesion.flush()


def test_gmf_cuenta_no_exenta(sesion, portafolio, instrumentos, parametros_gmf):
    cuenta = instrumentos["Cuenta"]
    sesion.add(_retiro(portafolio, cuenta, "2025-01-10", "1000000"))
    sesion.flush()
    (cargo,) = gmf_cuenta(sesion, cuenta.id, d("2025-01-01"), d("2025-01-31"))
    assert cargo.gmf == D("4000.00")


def test_gmf_cuenta_exenta(sesion, portafolio, instrumentos, parametros_gmf):
    cuenta = instrumentos["Cuenta"]
    cuenta.exenta_gmf = True
    sesion.add_all(
        [
            _retiro(portafolio, cuenta, "2025-01-05", "15000000"),
            _retiro(portafolio, cuenta, "2025-01-20", "5000000"),
            _retiro(portafolio, cuenta, "2025-02-03", "1000000"),
        ]
    )
    sesion.flush()
    # Tope 2025: 350 x 49.799 = 17.429.650. El retiro del 5-ene consume la
    # exención aunque quede fuera del rango pedido.
    cargos = gmf_cuenta(sesion, cuenta.id, d("2025-01-15"), d("2025-02-28"))
    assert [(c.fecha, c.exento, c.gmf) for c in cargos] == [
        (date(2025, 1, 20), D("2429650"), D("10281.40")),
        (date(2025, 2, 3), D("1000000"), D("0.00")),
    ]


def test_gmf_errores(sesion, portafolio, instrumentos, cdt):
    with pytest.raises(ValueError, match="no es una cuenta"):
        gmf_cuenta(sesion, cdt.id, d("2025-01-01"), d("2025-01-31"))
    cuenta = instrumentos["Cuenta"]
    sesion.add(_retiro(portafolio, cuenta, "2025-01-10", "1"))
    sesion.flush()
    with pytest.raises(ParametroNoDefinidoError, match="gmf_tarifa"):
        gmf_cuenta(sesion, cuenta.id, d("2025-01-01"), d("2025-01-31"))


# ------------------------------------------------------------------ parámetros por CSV


def test_importa_archivo_de_ejemplo(sesion):
    with EJEMPLO.open(encoding="utf-8") as archivo:
        assert importar_parametros(sesion, archivo) == 6


def test_importar_parametros_actualiza(sesion):
    importar_parametros(sesion, io.StringIO("nombre,vigente_desde,valor\nuvt,2025-01-01,1\n"))
    importar_parametros(sesion, io.StringIO("nombre,vigente_desde,valor\nuvt,2025-01-01,49799\n"))
    assert sesion.scalars(select(Parametro.valor)).all() == [D("49799")]


def test_importar_parametros_errores(sesion):
    with pytest.raises(ErrorImportacion) as error:
        importar_parametros(sesion, io.StringIO("nombre,vigente_desde,valor\n,2025-01-01,1\nuvt,ayer,1\nuvt,2025-01-01,1,5\n"))
    assert len(error.value.errores) == 3
