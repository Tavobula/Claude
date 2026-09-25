import io
from decimal import Decimal

import pytest

from portafolio.services.csv_io import (
    ErrorImportacion,
    exportar_movimientos,
    exportar_valoraciones,
    importar_movimientos,
    importar_valoraciones,
)

MOVIMIENTOS = """fecha,instrumento,tipo,monto,nota
2024-01-02,,aporte,10000000,Aporte inicial
2024-01-02,CDT Banco A,COMPRA,10000000.50,
"""

VALORACIONES = """fecha,instrumento,valor
2024-06-30,CDT Banco A,10450000.123456
"""


def test_ida_y_vuelta(sesion, portafolio, instrumentos):
    assert importar_movimientos(sesion, portafolio, io.StringIO(MOVIMIENTOS)) == 2
    assert importar_valoraciones(sesion, portafolio, io.StringIO(VALORACIONES)) == 1

    salida = io.StringIO()
    exportar_movimientos(sesion, portafolio, salida)
    assert salida.getvalue() == (
        "fecha,instrumento,tipo,monto,nota\n"
        "2024-01-02,,APORTE,10000000,Aporte inicial\n"
        "2024-01-02,CDT Banco A,COMPRA,10000000.50,\n"
    )

    salida = io.StringIO()
    exportar_valoraciones(sesion, portafolio, salida)
    assert salida.getvalue() == VALORACIONES


def test_reporta_todos_los_errores_sin_guardar_nada(sesion, portafolio, instrumentos):
    malo = """fecha,instrumento,tipo,monto
2024-01-02,,APORTE,1000
2024-13-01,,APORTE,1000
2024-01-03,CDT Inexistente,COMPRA,1000
2024-01-04,,REGALO,1000
2024-01-05,,APORTE,-5
2024-01-06,,APORTE,1.234,56
"""
    with pytest.raises(ErrorImportacion) as error:
        importar_movimientos(sesion, portafolio, io.StringIO(malo))
    filas = [e.split(":")[0] for e in error.value.errores]
    assert filas == ["Fila 3", "Fila 4", "Fila 5", "Fila 6", "Fila 7"]

    salida = io.StringIO()
    assert exportar_movimientos(sesion, portafolio, salida) == 0


def test_columnas_faltantes(sesion, portafolio):
    with pytest.raises(ErrorImportacion, match="monto"):
        importar_movimientos(sesion, portafolio, io.StringIO("fecha,tipo\n2024-01-01,APORTE\n"))
