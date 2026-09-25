"""Formato colombiano y la app de Streamlit (sin navegador, con AppTest)."""

from decimal import Decimal as D
from pathlib import Path

import pytest

from portafolio.ui import formato

APP = Path(__file__).resolve().parents[1] / "src" / "portafolio" / "ui" / "app.py"


@pytest.mark.parametrize(
    "valor,esperado",
    [(D("1234567.891"), "$ 1.234.568"), (D("-5"), "-$ 5"), (0, "$ 0"), (None, "—"), (D("999"), "$ 999")],
)
def test_pesos(valor, esperado):
    assert formato.pesos(valor) == esperado


def test_numero_y_porcentaje():
    assert formato.numero(D("1234.5"), 2) == "1.234,50"
    assert formato.numero(D("-0.001"), 2) == "0,00"
    assert formato.porcentaje(0.0816) == "8,16 %"
    assert formato.porcentaje(-0.123, 1) == "-12,3 %"
    assert formato.porcentaje(None) == "—"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("1.234.567,89", D("1234567.89")),
        ("1234567,89", D("1234567.89")),
        ("1234567.89", D("1234567.89")),
        ("1.234.567", D("1234567")),
        ("1.234", D("1234")),
        ("$ 1.500.000", D("1500000")),
        ("0,5", D("0.5")),
    ],
)
def test_leer_monto(texto, esperado):
    assert formato.leer_monto(texto) == esperado


@pytest.mark.parametrize("texto", ["", "abc", "1,2,3", "NaN"])
def test_leer_monto_invalido(texto):
    with pytest.raises(ValueError):
        formato.leer_monto(texto)


def test_leer_porcentaje():
    assert formato.leer_porcentaje("10,5") == D("0.105")
    assert formato.leer_porcentaje("9.75 %") == D("0.0975")


# ------------------------------------------------------------------ app

streamlit_testing = pytest.importorskip("streamlit.testing.v1")


@pytest.fixture
def base(tmp_path, monkeypatch):
    from portafolio.data.db import crear_motor
    from portafolio.data.modelos import Base

    url = f"sqlite:///{tmp_path / 'ui.db'}"
    motor = crear_motor(url)
    Base.metadata.create_all(motor)
    motor.dispose()
    monkeypatch.setenv("PORTAFOLIO_DB_URL", url)
    return url


def _app():
    return streamlit_testing.AppTest.from_file(str(APP), default_timeout=30)


def test_bienvenida_crea_usuario_y_portafolio(base):
    at = _app().run()
    assert not at.exception
    at.text_input[0].set_value("Ana")
    at.text_input[1].set_value("ana@example.com")
    at.button[0].click().run()
    assert not at.exception
    assert at.title[0].value == "Principal"
    assert any("creado" in s.value for s in at.success)


def test_bienvenida_valida_correo(base):
    at = _app().run()
    at.text_input[0].set_value("Ana")
    at.text_input[1].set_value("sin-arroba")
    at.button[0].click().run()
    assert at.error[0].value == "Correo inválido."


def test_demo_se_ve_completa(base):
    from datetime import date

    from portafolio.data.db import crear_motor, fabrica_sesiones
    from portafolio.services import demo

    motor = crear_motor(base)
    with fabrica_sesiones(motor)() as sesion:
        demo.crear_demo(sesion)
        sesion.commit()
    motor.dispose()

    at = _app()
    at.run()
    at.sidebar.date_input[0].set_value(date(2025, 9, 24)).run()
    assert not at.exception, at.exception
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["Valor"] == "$ 36.195.236"
    assert metricas["TIR (E.A.)"] == "8,88 %"
    assert metricas["TIR real (UVR)"] == "3,70 %"
    assert not at.warning  # todo se pudo calcular
    assert len(at.tabs) == 5


def test_registrar_movimiento_invalido_muestra_error(base):
    at = _app().run()
    at.text_input[0].set_value("Ana")
    at.text_input[1].set_value("ana@example.com")
    at.button[0].click().run()
    # Pestaña Movimientos: el primer formulario con "Monto".
    monto = next(t for t in at.text_input if t.label.startswith("Monto"))
    monto.set_value("abc")
    boton = next(b for b in at.button if b.label == "Guardar")
    boton.click().run()
    assert not at.exception
    assert any("Monto inválido" in e.value for e in at.error)
