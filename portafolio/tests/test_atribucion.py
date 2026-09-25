from datetime import date
from decimal import Decimal as D

import pytest

from conftest import d
from portafolio.core.atribucion import Segmento, agrupar, atribuir
from portafolio.core.dietz import DenominadorInvalidoError, dietz_modificado
from portafolio.data.modelos import TipoMovimiento
from portafolio.services import registro
from portafolio.services.atribucion import EFECTIVO, EFECTIVO_NO_REGISTRADO, atribucion_portafolio
from portafolio.services.rendimientos import dietz_portafolio

ENE1, ENE16, ENE31 = date(2024, 1, 1), date(2024, 1, 16), date(2024, 1, 31)


# ------------------------------------------------------------------ núcleo


def test_contribuciones_suman_el_dietz_del_total():
    a = Segmento("A", D("100"), D("112"), [(ENE16, D("10"))])
    b = Segmento("B", D("50"), D("45"), [])
    r = atribuir([a, b], ENE1, ENE31)
    total = dietz_modificado(150, 157, ENE1, ENE31, [(ENE16, 10)])
    assert r.rendimiento == pytest.approx(total)
    assert sum(c.contribucion for c in r.contribuciones) == pytest.approx(total)
    ca, cb = r.contribuciones
    # A: ganancia 2 sobre capital 100 + 10 x 15/30 = 105; B: -5 sobre 50.
    assert (ca.ganancia, cb.ganancia) == (D("2"), D("-5"))
    assert ca.rendimiento == pytest.approx(2 / 105)
    assert cb.rendimiento == pytest.approx(-0.1)
    assert ca.peso + cb.peso == pytest.approx(1)


def test_segmento_sin_capital_no_tiene_rendimiento_propio():
    # Comprado el último día: pesa 0 y su rendimiento propio no está definido.
    r = atribuir([Segmento("A", D("100"), D("110"), []), Segmento("B", D("0"), D("50"), [(ENE31, D("50"))])], ENE1, ENE31)
    assert r.contribuciones[1].rendimiento is None
    assert r.contribuciones[1].contribucion == 0


def test_agrupar():
    segmentos = [
        Segmento("CDT 1", D("100"), D("101"), []),
        Segmento("FIC", D("50"), D("52"), [(ENE16, D("5"))]),
        Segmento("CDT 2", D("200"), D("203"), []),
    ]
    grupos = agrupar(segmentos, {"CDT 1": "CDT", "CDT 2": "CDT", "FIC": "FIC"})
    assert [(g.clave, g.valor_inicial, g.valor_final, len(g.flujos)) for g in grupos] == [
        ("CDT", D("300"), D("304"), 0),
        ("FIC", D("50"), D("52"), 1),
    ]
    assert atribuir(grupos, ENE1, ENE31).rendimiento == pytest.approx(atribuir(segmentos, ENE1, ENE31).rendimiento)


def test_errores():
    with pytest.raises(ValueError, match="fuera del periodo"):
        atribuir([Segmento("A", D("1"), D("1"), [(ENE1, D("1"))])], ENE1, ENE31)
    with pytest.raises(DenominadorInvalidoError):
        atribuir([Segmento("A", D("0"), D("0"), [])], ENE1, ENE31)
    with pytest.raises(ValueError, match="posterior"):
        atribuir([], ENE31, ENE1)


# ------------------------------------------------------------------ servicio


@pytest.fixture
def cartera(sesion, portafolio, instrumentos):
    """Aporte a la cuenta y compras registradas solo en el instrumento comprado."""
    cuenta, cdt, fic = instrumentos["Cuenta"], instrumentos["CDT Banco A"], instrumentos["FIC Renta Fija"]
    p = portafolio
    registro.registrar_movimiento(sesion, p, d("2024-01-01"), TipoMovimiento.APORTE, D("1000"), cuenta.id)
    registro.registrar_valoracion(sesion, p, cuenta.id, d("2024-01-01"), D("1000"))
    registro.registrar_movimiento(sesion, p, d("2024-01-10"), TipoMovimiento.COMPRA, D("600"), cdt.id)
    registro.registrar_movimiento(sesion, p, d("2024-01-10"), TipoMovimiento.COMPRA, D("300"), fic.id)
    registro.registrar_movimiento(sesion, p, d("2024-01-20"), TipoMovimiento.INTERES, D("10"), cdt.id)
    registro.registrar_movimiento(sesion, p, d("2024-01-20"), TipoMovimiento.IMPUESTO, D("0.40"), cdt.id)
    registro.registrar_movimiento(sesion, p, d("2024-01-25"), TipoMovimiento.RETIRO, D("50"), cuenta.id)
    registro.registrar_valoracion(sesion, p, cuenta.id, d("2024-01-31"), D("60"))
    registro.registrar_valoracion(sesion, p, cdt.id, d("2024-01-31"), D("603"))
    registro.registrar_valoracion(sesion, p, fic.id, d("2024-01-31"), D("295"))
    return instrumentos


def test_atribucion_por_instrumento_suma_el_dietz(sesion, portafolio, cartera):
    r = atribucion_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    dietz = dietz_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"))
    assert r.rendimiento == pytest.approx(dietz.rendimiento, abs=1e-15)
    assert sum(f.detalle.contribucion for f in r.filas) == pytest.approx(dietz.rendimiento, abs=1e-15)

    filas = {f.nombre: f.detalle for f in r.filas}
    assert set(filas) == {"CDT Banco A", "FIC Renta Fija", EFECTIVO}
    # CDT: 603 - 0 - (600 - 9,60) = 12,60. FIC: 295 - 300 = -5.
    assert filas["CDT Banco A"].ganancia == D("12.60")
    assert filas["FIC Renta Fija"].ganancia == D("-5")
    # Efectivo: 60 - 1000 - (-900 + 9,60 - 50) = 0,40 (solo el redondeo de este ejemplo).
    assert filas[EFECTIVO].ganancia == D("0.40")
    assert [f.nombre for f in r.filas] == ["CDT Banco A", EFECTIVO, "FIC Renta Fija"]  # por contribución


def test_atribucion_por_tipo(sesion, portafolio, cartera):
    r = atribucion_portafolio(sesion, portafolio.id, d("2024-01-01"), d("2024-01-31"), por="tipo")
    assert {f.nombre for f in r.filas} == {"CDT", "FIC", "CUENTA"}
    assert all(f.instrumento_id is None for f in r.filas)


def test_sin_cuentas_aparece_efectivo_no_registrado(sesion, portafolio):
    from portafolio.data.modelos import TipoInstrumento

    fic = registro.crear_instrumento(sesion, portafolio, "FIC Renta Fija", TipoInstrumento.FIC)
    # Aportó 1.000 sin instrumento pero solo compró 900: 100 quedaron sin registrar.
    registro.registrar_movimiento(sesion, portafolio, d("2024-01-01"), TipoMovimiento.APORTE, D("1000"))
    registro.registrar_movimiento(sesion, portafolio, d("2024-01-01"), TipoMovimiento.COMPRA, D("900"), fic.id)
    registro.registrar_valoracion(sesion, portafolio, fic.id, d("2024-01-01"), D("900"))
    registro.registrar_valoracion(sesion, portafolio, fic.id, d("2024-01-31"), D("910"))
    r = atribucion_portafolio(sesion, portafolio.id, d("2023-12-31"), d("2024-01-31"))
    filas = {f.nombre: f.detalle for f in r.filas}
    assert filas["FIC Renta Fija"].ganancia == D("10")
    assert filas[EFECTIVO_NO_REGISTRADO].ganancia == D("-100")
    assert r.ganancia == D("-90")


def test_aporte_y_compra_el_mismo_dia_no_dejan_efectivo(sesion, portafolio, instrumentos):
    fic = instrumentos["FIC Renta Fija"]
    registro.registrar_movimiento(sesion, portafolio, d("2024-01-01"), TipoMovimiento.APORTE, D("1000"))
    registro.registrar_movimiento(sesion, portafolio, d("2024-01-01"), TipoMovimiento.COMPRA, D("1000"), fic.id)
    registro.registrar_valoracion(sesion, portafolio, fic.id, d("2024-01-31"), D("1010"))
    r = atribucion_portafolio(sesion, portafolio.id, d("2023-12-31"), d("2024-01-31"))
    assert [f.nombre for f in r.filas] == ["FIC Renta Fija"]
