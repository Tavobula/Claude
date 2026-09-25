"""Formato colombiano para mostrar y leer montos: $ 1.234.567,89 y 10,50 %."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

SIN_DATO = "—"


def _miles(entero: str) -> str:
    return re.sub(r"(?<=\d)(?=(\d{3})+$)", ".", entero)


def numero(valor, decimales: int = 0) -> str:
    if valor is None:
        return SIN_DATO
    texto = f"{Decimal(str(valor)):.{decimales}f}"
    signo = "-" if texto.startswith("-") else ""
    entero, _, fraccion = texto.lstrip("-").partition(".")
    if signo and set(entero + fraccion) <= {"0"}:
        signo = ""  # no mostrar "-0"
    return signo + _miles(entero) + ("," + fraccion if fraccion else "")


def pesos(valor, decimales: int = 0) -> str:
    if valor is None:
        return SIN_DATO
    texto = numero(valor, decimales)
    return f"-$ {texto[1:]}" if texto.startswith("-") else f"$ {texto}"


def porcentaje(valor: float | None, decimales: int = 2) -> str:
    return SIN_DATO if valor is None else f"{numero(valor * 100, decimales)} %"


def fecha(valor: date | None) -> str:
    return SIN_DATO if valor is None else valor.strftime("%d/%m/%Y")


def leer_monto(texto: str) -> Decimal:
    """Lee un monto escrito por el usuario, sin pasar por float.

    Acepta ``1.234.567,89``, ``1234567,89``, ``1234567.89``, ``1.234.567`` y
    ``$ 1.234``. Con coma, la coma es el decimal. Sin coma, un punto seguido
    de exactamente tres dígitos (una o más veces) se toma como separador de miles.
    """
    limpio = (texto or "").strip().replace("$", "").replace(" ", "").replace(" ", "")
    if not limpio:
        raise ValueError("Escriba un monto.")
    if "," in limpio:
        limpio = limpio.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", limpio):
        limpio = limpio.replace(".", "")
    try:
        valor = Decimal(limpio)
    except InvalidOperation:
        raise ValueError(f"Monto inválido: {texto!r}") from None
    if not valor.is_finite():
        raise ValueError(f"Monto inválido: {texto!r}")
    return valor


def leer_porcentaje(texto: str) -> Decimal:
    """``10,5`` o ``10.5 %`` -> ``0.105``."""
    return leer_monto((texto or "").replace("%", "")) / 100
