"""Fechas en hora de Bogotá y días hábiles colombianos.

Los festivos (incluida la Ley Emiliani) afectan el pago de CDTs, la
publicación del valor de unidad de los FIC y los precios de la BVC.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays

ZONA_BOGOTA = ZoneInfo("America/Bogota")


def ahora_bogota() -> datetime:
    return datetime.now(ZONA_BOGOTA)


def hoy_bogota() -> date:
    return ahora_bogota().date()


@lru_cache(maxsize=64)
def _festivos(anio: int) -> frozenset[date]:
    return frozenset(holidays.country_holidays("CO", years=anio).keys())


def es_festivo(fecha: date) -> bool:
    return fecha in _festivos(fecha.year)


def es_dia_habil(fecha: date) -> bool:
    return fecha.weekday() < 5 and not es_festivo(fecha)


def siguiente_dia_habil(fecha: date) -> date:
    """La misma fecha si es hábil; si no, el siguiente día hábil."""
    while not es_dia_habil(fecha):
        fecha += timedelta(days=1)
    return fecha


def sumar_dias_habiles(fecha: date, dias: int) -> date:
    paso = 1 if dias >= 0 else -1
    restantes = abs(dias)
    while restantes:
        fecha += timedelta(days=paso)
        if es_dia_habil(fecha):
            restantes -= 1
    return fecha
