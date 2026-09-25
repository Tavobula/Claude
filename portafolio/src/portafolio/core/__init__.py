"""Núcleo de cálculo: funciones puras sobre flujos y fechas.

Nada en este paquete importa SQLAlchemy ni conoce usuarios o portafolios.
"""

from portafolio.core.xirr import SinSolucionError, xirr, xnpv

__all__ = ["SinSolucionError", "xirr", "xnpv"]
