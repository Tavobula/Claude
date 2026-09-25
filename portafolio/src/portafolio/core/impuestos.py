"""Retención en la fuente sobre rendimientos y gravamen a los movimientos financieros (GMF).

Las tarifas no están aquí: llegan como argumentos desde la tabla de parámetros,
porque cambian por norma y el pasado se recalcula con la tarifa de su momento.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from portafolio.core.dinero import redondear


def retencion_rendimientos(
    interes: Decimal, tarifa: Decimal, componente_inflacionario: Decimal = Decimal(0)
) -> Decimal:
    """Retención sobre un pago de intereses.

    ``componente_inflacionario`` es la fracción del rendimiento que no se grava
    (aplica a personas naturales no obligadas a llevar contabilidad; se fija
    por decreto cada año). Con 0 la retención se calcula sobre todo el interés.
    """
    if interes <= 0:
        return Decimal(0)
    if not 0 <= componente_inflacionario <= 1:
        raise ValueError("El componente inflacionario debe estar entre 0 y 1.")
    return redondear(interes * (1 - componente_inflacionario) * tarifa)


@dataclass(frozen=True)
class CargoGMF:
    fecha: date
    monto: Decimal
    exento: Decimal  # parte cubierta por la exención mensual
    gmf: Decimal


def gmf(
    retiros: Sequence[tuple[date, Decimal]],
    tarifa: Decimal,
    tope_exento_mensual: Decimal | None = None,
) -> list[CargoGMF]:
    """GMF (4 x 1.000) sobre retiros, con la exención mensual de una cuenta marcada.

    La exención se consume en orden cronológico y se reinicia cada mes
    calendario. Con ``tope_exento_mensual=None`` la cuenta no está exenta.
    El resultado conserva el orden de ``retiros``.
    """
    orden = sorted(range(len(retiros)), key=lambda i: retiros[i][0])
    cargos: dict[int, CargoGMF] = {}
    usado: dict[tuple[int, int], Decimal] = {}
    for i in orden:
        fecha, monto = retiros[i]
        if monto < 0:
            raise ValueError("Los montos de retiro deben ser positivos.")
        exento = Decimal(0)
        if tope_exento_mensual is not None:
            mes = (fecha.year, fecha.month)
            disponible = max(tope_exento_mensual - usado.get(mes, Decimal(0)), Decimal(0))
            exento = min(monto, disponible)
            usado[mes] = usado.get(mes, Decimal(0)) + exento
        cargos[i] = CargoGMF(fecha, monto, exento, redondear((monto - exento) * tarifa))
    return [cargos[i] for i in range(len(retiros))]
