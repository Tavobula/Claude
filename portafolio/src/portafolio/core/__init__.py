"""Núcleo de cálculo: funciones puras sobre flujos y fechas.

Nada en este paquete importa SQLAlchemy ni conoce usuarios o portafolios.
"""

from portafolio.core.dietz import DenominadorInvalidoError, dietz_modificado
from portafolio.core.twr import ResultadoTWR, Subperiodo, anualizar, encadenar, twr
from portafolio.core.xirr import SinSolucionError, xirr, xnpv

__all__ = [
    "DenominadorInvalidoError",
    "ResultadoTWR",
    "SinSolucionError",
    "Subperiodo",
    "anualizar",
    "dietz_modificado",
    "encadenar",
    "twr",
    "xirr",
    "xnpv",
]
