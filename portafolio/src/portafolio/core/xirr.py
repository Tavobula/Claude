"""Tasa interna de retorno para flujos con fechas irregulares (XIRR).

Sigue la convención de la función XIRR / TIR.NO.PER de Excel:

    sum( F_i / (1 + r) ** ((d_i - d_0) / 365) ) = 0

donde d_0 es la fecha más antigua. Los montos pueden llegar como ``Decimal``
(así se guardan en la base); el cálculo iterativo se hace en ``float`` y el
redondeo queda a cargo de quien muestra el resultado.

Convención de signos: negativo = dinero que sale del bolsillo del inversionista
(aporte, compra); positivo = dinero que vuelve (retiro, venta, valor final).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

Flujo = tuple[date, "float | int | Decimal"]

DIAS_ANIO = 365.0
_TASA_MINIMA = -0.999999999


class SinSolucionError(ValueError):
    """Los flujos no tienen una TIR definida o el método no convergió."""


def _normalizar(flujos: Sequence[Flujo]) -> list[tuple[float, float]]:
    if len(flujos) < 2:
        raise SinSolucionError("Se necesitan al menos dos flujos.")
    base = min(f for f, _ in flujos)
    normalizados = [((f - base).days / DIAS_ANIO, float(m)) for f, m in flujos]
    if not any(m > 0 for _, m in normalizados) or not any(m < 0 for _, m in normalizados):
        raise SinSolucionError("Se necesita al menos un flujo positivo y uno negativo.")
    return normalizados


def _vpn(tasa: float, flujos: list[tuple[float, float]]) -> float:
    return sum(m / (1.0 + tasa) ** t for t, m in flujos)


def _derivada(tasa: float, flujos: list[tuple[float, float]]) -> float:
    return sum(-t * m / (1.0 + tasa) ** (t + 1.0) for t, m in flujos)


def xnpv(tasa: float, flujos: Sequence[Flujo]) -> float:
    """Valor presente neto a la fecha del primer flujo (equivale a VNA.NO.PER)."""
    if tasa <= -1.0:
        raise ValueError("La tasa debe ser mayor que -100 %.")
    return _vpn(tasa, _normalizar(flujos))


def _newton(flujos, estimado: float, tol: float, max_iter: int) -> float | None:
    tasa = estimado
    for _ in range(max_iter):
        try:
            valor = _vpn(tasa, flujos)
            pendiente = _derivada(tasa, flujos)
        except (OverflowError, ZeroDivisionError):
            return None
        if pendiente == 0 or not math.isfinite(valor):
            return None
        nueva = tasa - valor / pendiente
        if nueva <= -1.0 or not math.isfinite(nueva):
            return None
        if abs(nueva - tasa) < tol:
            return nueva
        tasa = nueva
    return None


def _biseccion(flujos, tol: float) -> float:
    bajo, alto = _TASA_MINIMA, 1.0
    v_bajo = _vpn(bajo, flujos)
    v_alto = _vpn(alto, flujos)
    while v_bajo * v_alto > 0:
        alto *= 2.0
        if alto > 1e9:
            raise SinSolucionError("No se encontró un cambio de signo en el VPN.")
        try:
            v_alto = _vpn(alto, flujos)
        except OverflowError:
            raise SinSolucionError("No se encontró un cambio de signo en el VPN.") from None
    for _ in range(500):
        medio = (bajo + alto) / 2.0
        v_medio = _vpn(medio, flujos)
        if v_medio == 0 or (alto - bajo) / 2.0 < tol:
            return medio
        if v_bajo * v_medio < 0:
            alto = medio
        else:
            bajo, v_bajo = medio, v_medio
    return (bajo + alto) / 2.0


def xirr(
    flujos: Sequence[Flujo],
    estimado: float = 0.1,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> float:
    """TIR efectiva anual de flujos con fechas irregulares.

    Usa Newton-Raphson desde ``estimado`` (como Excel) y, si no converge,
    bisección sobre un intervalo que contenga un cambio de signo.

    >>> from datetime import date
    >>> round(xirr([(date(2024, 1, 1), -1000), (date(2024, 12, 31), 1100)]), 6)
    0.1
    """
    normalizados = _normalizar(flujos)
    tasa = _newton(normalizados, estimado, tol, max_iter)
    if tasa is None:
        tasa = _biseccion(normalizados, tol)
    return tasa
