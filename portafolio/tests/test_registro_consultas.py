from datetime import date
from decimal import Decimal as D

import pytest

from conftest import d
from portafolio.core.cdt import Periodicidad, TipoTasa
from portafolio.data.modelos import TipoInstrumento, TipoMovimiento
from portafolio.services import consultas, registro
from portafolio.services.registro import DatoInvalidoError


# ------------------------------------------------------------------ registro


def test_usuario_y_portafolio(sesion):
    u = registro.crear_usuario(sesion, " Ana ", "ANA@example.com")
    assert (u.nombre, u.email) == ("Ana", "ana@example.com")
    with pytest.raises(DatoInvalidoError, match="Ya existe"):
        registro.crear_usuario(sesion, "Otra", "ana@example.com")
    with pytest.raises(DatoInvalidoError, match="Correo"):
        registro.crear_usuario(sesion, "X", "sin-arroba")
    registro.crear_portafolio(sesion, u.id, "Retiro")
    with pytest.raises(DatoInvalidoError, match="Ya tiene"):
        registro.crear_portafolio(sesion, u.id, "Retiro")
    with pytest.raises(DatoInvalidoError, match="vacío"):
        registro.crear_portafolio(sesion, u.id, "  ")


def test_instrumentos(sesion, portafolio):
    registro.crear_instrumento(sesion, portafolio, "Cuenta", TipoInstrumento.CUENTA, exenta_gmf=True)
    with pytest.raises(DatoInvalidoError, match="Ya existe"):
        registro.crear_instrumento(sesion, portafolio, "Cuenta", TipoInstrumento.CUENTA)
    with pytest.raises(DatoInvalidoError, match="Solo una cuenta"):
        registro.crear_instrumento(sesion, portafolio, "CDT", TipoInstrumento.CDT, exenta_gmf=True)


def test_movimientos(sesion, portafolio, instrumentos):
    cdt = instrumentos["CDT Banco A"]
    m = registro.registrar_movimiento(sesion, portafolio, d("2025-01-01"), TipoMovimiento.COMPRA, D("100"), cdt.id, " x ")
    assert (m.nota, m.usuario_id) == ("x", portafolio.usuario_id)
    with pytest.raises(DatoInvalidoError, match="positivo"):
        registro.registrar_movimiento(sesion, portafolio, d("2025-01-01"), TipoMovimiento.APORTE, D("0"))
    with pytest.raises(DatoInvalidoError, match="float"):
        registro.registrar_movimiento(sesion, portafolio, d("2025-01-01"), TipoMovimiento.APORTE, 0.1)
    with pytest.raises(DatoInvalidoError, match="debe indicar el instrumento"):
        registro.registrar_movimiento(sesion, portafolio, d("2025-01-01"), TipoMovimiento.COMPRA, D("1"))
    otro = registro.crear_portafolio(sesion, portafolio.usuario_id, "Otro")
    with pytest.raises(DatoInvalidoError, match="no pertenece"):
        registro.registrar_movimiento(sesion, otro, d("2025-01-01"), TipoMovimiento.COMPRA, D("1"), cdt.id)
    with pytest.raises(DatoInvalidoError, match="no pertenece"):
        registro.eliminar_movimiento(sesion, otro, m.id)
    registro.eliminar_movimiento(sesion, portafolio, m.id)
    assert consultas.movimientos_de(sesion, portafolio.id) == []


def test_valoracion_se_reemplaza(sesion, portafolio, instrumentos):
    fic = instrumentos["FIC Renta Fija"]
    a = registro.registrar_valoracion(sesion, portafolio, fic.id, d("2025-01-31"), D("100"))
    b = registro.registrar_valoracion(sesion, portafolio, fic.id, d("2025-01-31"), D("0"))
    assert a.id == b.id and b.valor == 0


def test_condicion_cdt(sesion, portafolio, instrumentos):
    cdt = instrumentos["CDT Banco A"]
    datos = dict(capital=D("1000"), fecha_emision=d("2025-01-01"), fecha_vencimiento=d("2026-01-01"), tasa=D("0.1"))
    c = registro.registrar_condicion_cdt(sesion, portafolio, cdt.id, **datos)
    c2 = registro.registrar_condicion_cdt(sesion, portafolio, cdt.id, **{**datos, "tasa": D("0.11")})
    assert c is c2 and c2.tasa == D("0.11")
    with pytest.raises(DatoInvalidoError, match="periodicidad"):
        registro.registrar_condicion_cdt(sesion, portafolio, cdt.id, **datos, tipo_tasa=TipoTasa.NOMINAL, periodicidad=Periodicidad.AL_VENCIMIENTO)
    with pytest.raises(DatoInvalidoError, match="vencimiento"):
        registro.registrar_condicion_cdt(sesion, portafolio, cdt.id, **{**datos, "fecha_vencimiento": d("2024-01-01")})
    with pytest.raises(DatoInvalidoError, match="no es un CDT"):
        registro.registrar_condicion_cdt(sesion, portafolio, instrumentos["Cuenta"].id, **datos)


# ------------------------------------------------------------------ consultas


@pytest.fixture
def con_datos(sesion, portafolio, instrumentos):
    cuenta, fic = instrumentos["Cuenta"], instrumentos["FIC Renta Fija"]
    p = portafolio
    registro.registrar_movimiento(sesion, p, d("2025-01-01"), TipoMovimiento.APORTE, D("1000"), fic.id)
    registro.registrar_valoracion(sesion, p, fic.id, d("2025-01-01"), D("1000"))
    registro.registrar_valoracion(sesion, p, fic.id, d("2025-02-01"), D("1010"))
    registro.registrar_movimiento(sesion, p, d("2025-02-15"), TipoMovimiento.APORTE, D("500"), cuenta.id)
    registro.registrar_valoracion(sesion, p, fic.id, d("2025-03-01"), D("1030"))
    registro.registrar_valoracion(sesion, p, cuenta.id, d("2025-03-01"), D("500"))
    return instrumentos


def test_posiciones(sesion, portafolio, con_datos):
    pos = consultas.posiciones(sesion, portafolio.id, d("2025-03-01"))
    assert [(p.nombre, p.valor) for p in pos] == [("FIC Renta Fija", D("1030")), ("Cuenta", D("500"))]
    assert sum(p.peso for p in pos) == pytest.approx(1)
    # El 20-feb la cuenta tiene un aporte sin valorar.
    pos = consultas.posiciones(sesion, portafolio.id, d("2025-02-20"))
    cuenta = next(p for p in pos if p.nombre == "Cuenta")
    assert cuenta.valor is None and "Cuenta" in cuenta.aviso


def test_evolucion(sesion, portafolio, con_datos):
    puntos = consultas.evolucion(sesion, portafolio.id, d("2025-01-01"), d("2025-03-01"))
    assert [(p.fecha, p.valor, p.aportes_netos) for p in puntos] == [
        (d("2025-01-01"), D("1000"), D("1000")),
        (d("2025-02-01"), D("1010"), D("1000")),
        (d("2025-03-01"), D("1530"), D("1500")),
    ]


def test_resumen(sesion, portafolio, con_datos):
    r = consultas.resumen(sesion, portafolio.id, d("2025-03-01"))
    assert (r.valor, r.aportes_netos, r.ganancia) == (D("1530"), D("1500"), D("30"))
    assert r.tir > 0 and r.twr_anio is not None
    assert r.tir_real is None and any("UVR" in a for a in r.avisos)  # sin serie cargada


def test_resumen_con_valoracion_faltante(sesion, portafolio, con_datos):
    r = consultas.resumen(sesion, portafolio.id, d("2025-02-20"))
    assert r.valor is None and r.tir is None
    assert any("Valor" in a for a in r.avisos)


def test_listas(sesion, portafolio, con_datos):
    assert [u.id for u in consultas.usuarios(sesion)] == [portafolio.usuario_id]
    assert [p.nombre for p in consultas.portafolios_de(sesion, portafolio.usuario_id)] == ["Retiro"]
    assert consultas.primera_fecha(sesion, portafolio.id) == date(2025, 1, 1)
