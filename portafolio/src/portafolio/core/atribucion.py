"""Atribución del rendimiento de un portafolio entre sus partes (Dietz modificado).

Para cada segmento (instrumento o grupo) en el periodo:

    ganancia_i = V1_i - V0_i - F_i
    capital_i  = V0_i + sum(w_j * F_ij)          (capital promedio invertido)
    contribución_i = ganancia_i / sum(capital)
    peso_i         = capital_i / sum(capital)
    rendimiento_i  = ganancia_i / capital_i

Si los flujos de todos los segmentos suman los flujos externos del portafolio
(fecha por fecha), las contribuciones suman exactamente el Dietz modificado
del portafolio. Los signos y pesos son los de ``core.dietz``: positivo = entra
dinero al segmento; un flujo el último día pesa 0.

Esta es la atribución de un solo periodo. Suma al Dietz del periodo, no al
TWR encadenado.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from portafolio.core.dietz import DenominadorInvalidoError


@dataclass(frozen=True)
class Segmento:
    clave: str
    valor_inicial: Decimal
    valor_final: Decimal
    flujos: Sequence[tuple[date, Decimal]]


@dataclass(frozen=True)
class Contribucion:
    clave: str
    valor_inicial: Decimal
    valor_final: Decimal
    flujo_neto: Decimal
    ganancia: Decimal
    capital_promedio: float
    peso: float
    # None si el segmento no tuvo capital promedio positivo (p. ej. se compró el último día).
    rendimiento: float | None
    contribucion: float


@dataclass(frozen=True)
class ResultadoAtribucion:
    rendimiento: float  # Dietz modificado del total
    ganancia: Decimal
    contribuciones: list[Contribucion]


def _capital(segmento: Segmento, inicio: date, fin: date) -> float:
    dias = (fin - inicio).days
    return float(segmento.valor_inicial) + sum(float(m) * (fin - f).days / dias for f, m in segmento.flujos)


def atribuir(segmentos: Sequence[Segmento], fecha_inicio: date, fecha_fin: date) -> ResultadoAtribucion:
    if fecha_fin <= fecha_inicio:
        raise ValueError("La fecha final debe ser posterior a la inicial.")
    for s in segmentos:
        fuera = [f for f, _ in s.flujos if not fecha_inicio < f <= fecha_fin]
        if fuera:
            raise ValueError(f"{s.clave}: flujos fuera del periodo: {fuera}")

    capitales = [_capital(s, fecha_inicio, fecha_fin) for s in segmentos]
    total_capital = sum(capitales)
    ganancias = [s.valor_final - s.valor_inicial - sum((m for _, m in s.flujos), Decimal(0)) for s in segmentos]
    total_ganancia = sum(ganancias, Decimal(0))
    if total_capital <= 0:
        raise DenominadorInvalidoError(
            f"Capital promedio no positivo ({total_capital:.2f}) entre {fecha_inicio} y {fecha_fin}."
        )

    contribuciones = [
        Contribucion(
            clave=s.clave,
            valor_inicial=s.valor_inicial,
            valor_final=s.valor_final,
            flujo_neto=sum((m for _, m in s.flujos), Decimal(0)),
            ganancia=g,
            capital_promedio=c,
            peso=c / total_capital,
            rendimiento=float(g) / c if c > 0 else None,
            contribucion=float(g) / total_capital,
        )
        for s, g, c in zip(segmentos, ganancias, capitales)
    ]
    return ResultadoAtribucion(float(total_ganancia) / total_capital, total_ganancia, contribuciones)


def agrupar(segmentos: Sequence[Segmento], grupo_de: dict[str, str]) -> list[Segmento]:
    """Une segmentos por grupo (p. ej. tipo de instrumento), conservando el orden de aparición."""
    grupos: dict[str, list[Segmento]] = {}
    for s in segmentos:
        grupos.setdefault(grupo_de[s.clave], []).append(s)
    return [
        Segmento(
            clave,
            sum((s.valor_inicial for s in miembros), Decimal(0)),
            sum((s.valor_final for s in miembros), Decimal(0)),
            [f for s in miembros for f in s.flujos],
        )
        for clave, miembros in grupos.items()
    ]
