"""Redondeo de montos en pesos."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")


def redondear(valor: Decimal) -> Decimal:
    """Redondea a centavos, mitad hacia arriba (como una liquidación bancaria)."""
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)
