"""Deflactación con índices de precios (UVR, IPC).

* UVR: valor diario (Banco de la República). Se publica para todos los días
  calendario y con anticipación, así que sirve para fechas recientes. Es el
  índice por defecto.
* IPC: índice mensual (DANE). Una fecha usa el índice de su mes, que se
  guarda con fecha del día 1. Si el mes aún no se publica, falla en lugar de
  usar uno anterior.

Pesos constantes: ``monto_real = monto * I(base) / I(fecha)``, es decir, el
monto expresado en poder de compra de ``fecha_base``.
"""

from __future__ import annotations

import enum
from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class Frecuencia(str, enum.Enum):
    DIARIA = "DIARIA"
    MENSUAL = "MENSUAL"


class ValorNoDisponibleError(LookupError):
    """El índice no tiene valor para la fecha pedida."""


def normalizar_fecha(fecha: date, frecuencia: Frecuencia) -> date:
    return fecha.replace(day=1) if frecuencia is Frecuencia.MENSUAL else fecha


@dataclass(frozen=True)
class Indice:
    codigo: str
    frecuencia: Frecuencia
    fechas: tuple[date, ...]
    valores: tuple[Decimal, ...]

    @classmethod
    def crear(
        cls, codigo: str, frecuencia: Frecuencia, observaciones: Iterable[tuple[date, Decimal]]
    ) -> Indice:
        por_fecha: dict[date, Decimal] = {}
        for fecha, valor in observaciones:
            fecha = normalizar_fecha(fecha, frecuencia)
            valor = Decimal(valor)
            if valor <= 0:
                raise ValueError(f"{codigo}: valor no positivo el {fecha}.")
            if fecha in por_fecha and por_fecha[fecha] != valor:
                raise ValueError(f"{codigo}: dos valores distintos para {fecha}.")
            por_fecha[fecha] = valor
        fechas = tuple(sorted(por_fecha))
        return cls(codigo, frecuencia, fechas, tuple(por_fecha[f] for f in fechas))

    def valor_en(self, fecha: date) -> Decimal:
        clave = normalizar_fecha(fecha, self.frecuencia)
        i = bisect_left(self.fechas, clave)
        if i < len(self.fechas) and self.fechas[i] == clave:
            return self.valores[i]
        if not self.fechas:
            raise ValorNoDisponibleError(f"La serie {self.codigo} no tiene datos.")
        periodo = f"{clave:%Y-%m}" if self.frecuencia is Frecuencia.MENSUAL else clave.isoformat()
        raise ValorNoDisponibleError(
            f"{self.codigo} no tiene valor para {periodo} "
            f"(hay datos de {self.fechas[0]} a {self.fechas[-1]}). Actualice la serie."
        )


def inflacion(indice: Indice, desde: date, hasta: date) -> float:
    """Variación del índice entre dos fechas (no anualizada)."""
    return float(indice.valor_en(hasta) / indice.valor_en(desde)) - 1.0


def deflactar(monto: Decimal, indice: Indice, fecha: date, fecha_base: date) -> Decimal:
    """``monto`` de ``fecha`` expresado en pesos de ``fecha_base``."""
    return Decimal(monto) * indice.valor_en(fecha_base) / indice.valor_en(fecha)


def flujos_reales(
    flujos: Sequence[tuple[date, Decimal]], indice: Indice, fecha_base: date
) -> list[tuple[date, Decimal]]:
    return [(f, deflactar(m, indice, f, fecha_base)) for f, m in flujos]


def rendimiento_real(nominal: float, inflacion_periodo: float) -> float:
    """Ecuación de Fisher: (1 + nominal) / (1 + inflación) - 1."""
    return (1.0 + nominal) / (1.0 + inflacion_periodo) - 1.0
