"""Rendimiento por Dietz modificado para un periodo.

    R = (V1 - V0 - F) / (V0 + sum(w_i * F_i)),   w_i = (T - t_i) / T

donde T son los días del periodo y t_i los días entre el inicio y el flujo.

Convenciones:

* ``V0`` es el valor al cierre de ``fecha_inicio`` y ``V1`` al cierre de
  ``fecha_fin``. Cada valoración incluye los flujos de ese mismo día.
* Por eso solo cuentan los flujos en ``(fecha_inicio, fecha_fin]``: uno el día
  del inicio ya está dentro de ``V0`` y uno el día final pesa 0.
* Signo visto desde el activo: positivo = entra dinero (aporte, compra),
  negativo = sale (retiro, venta, dividendo pagado). Es el opuesto de la
  convención del inversionista que usa ``xirr``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

Numero = "float | int | Decimal"
Flujo = tuple[date, Numero]


class DenominadorInvalidoError(ValueError):
    """El capital promedio invertido es cero o negativo; el rendimiento no tiene sentido."""


def dietz_modificado(
    valor_inicial: Numero,
    valor_final: Numero,
    fecha_inicio: date,
    fecha_fin: date,
    flujos: Sequence[Flujo] = (),
) -> float:
    """Rendimiento del periodo (no anualizado)."""
    if fecha_fin <= fecha_inicio:
        raise ValueError("La fecha final debe ser posterior a la inicial.")
    fuera = [f for f, _ in flujos if not fecha_inicio < f <= fecha_fin]
    if fuera:
        raise ValueError(f"Flujos fuera del periodo ({fecha_inicio}, {fecha_fin}]: {fuera}")

    dias = (fecha_fin - fecha_inicio).days
    v0, v1 = float(valor_inicial), float(valor_final)
    neto = sum(float(m) for _, m in flujos)
    ponderado = sum(float(m) * (fecha_fin - f).days / dias for f, m in flujos)

    ganancia = v1 - v0 - neto
    capital = v0 + ponderado
    if capital <= 0:
        if capital == 0 and ganancia == 0:
            return 0.0  # periodo sin capital ni movimiento
        raise DenominadorInvalidoError(
            f"Capital promedio no positivo ({capital:.2f}) entre {fecha_inicio} y {fecha_fin}."
        )
    return ganancia / capital
