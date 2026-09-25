"""Rendimiento ponderado por tiempo (TWR).

El periodo se parte en subperiodos entre valoraciones consecutivas. Cada
subperiodo se mide con Dietz modificado y los resultados se encadenan:

    TWR = prod(1 + r_k) - 1

Si todo flujo cae en una fecha con valoración, cada subperiodo termina justo
en el flujo, su peso es 0 y el resultado es el TWR exacto. Si hay flujos entre
valoraciones, el subperiodo que los contiene se aproxima con Dietz (TWR por
Dietz encadenado) y ``exacto`` queda en ``False``.

Signo de los flujos: el de ``core.dietz`` (positivo = entra al activo).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from portafolio.core.dietz import Flujo, Numero, dietz_modificado

DIAS_ANIO = 365.0


@dataclass(frozen=True)
class Subperiodo:
    inicio: date
    fin: date
    valor_inicial: float
    valor_final: float
    flujo_neto: float
    rendimiento: float
    # Hay flujos antes del cierre del subperiodo: se usó la aproximación de Dietz.
    aproximado: bool


@dataclass(frozen=True)
class ResultadoTWR:
    rendimiento: float
    subperiodos: list[Subperiodo]

    @property
    def exacto(self) -> bool:
        return not any(s.aproximado for s in self.subperiodos)


def encadenar(rendimientos: Sequence[float]) -> float:
    total = 1.0
    for r in rendimientos:
        total *= 1.0 + r
    return total - 1.0


def anualizar(rendimiento: float, dias: int) -> float:
    """Convierte un rendimiento de ``dias`` días en efectivo anual (base 365)."""
    if dias <= 0:
        raise ValueError("El número de días debe ser positivo.")
    return (1.0 + rendimiento) ** (DIAS_ANIO / dias) - 1.0


def twr(valoraciones: Sequence[tuple[date, Numero]], flujos: Sequence[Flujo] = ()) -> ResultadoTWR:
    """TWR entre la primera y la última valoración.

    ``valoraciones``: (fecha, valor al cierre del día, incluidos sus flujos).
    ``flujos``: externos; los que no caen en ``(primera, última]`` se ignoran
    porque ya están dentro de la valoración inicial o fuera del periodo.
    """
    puntos = sorted(valoraciones)
    fechas = [f for f, _ in puntos]
    if len(puntos) < 2:
        raise ValueError("Se necesitan al menos dos valoraciones.")
    if len(set(fechas)) != len(fechas):
        raise ValueError("Hay dos valoraciones con la misma fecha.")

    subperiodos = []
    for (inicio, v0), (fin, v1) in zip(puntos, puntos[1:]):
        propios = [(f, m) for f, m in flujos if inicio < f <= fin]
        r = dietz_modificado(v0, v1, inicio, fin, propios)
        subperiodos.append(
            Subperiodo(
                inicio=inicio,
                fin=fin,
                valor_inicial=float(v0),
                valor_final=float(v1),
                flujo_neto=sum(float(m) for _, m in propios),
                rendimiento=r,
                aproximado=any(f < fin and m for f, m in propios),
            )
        )
    return ResultadoTWR(encadenar([s.rendimiento for s in subperiodos]), subperiodos)
