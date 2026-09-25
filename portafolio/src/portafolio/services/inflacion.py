"""Rendimientos reales y valores en pesos constantes.

Por defecto se deflacta con la UVR (diaria y publicada por adelantado). Con
``serie="IPC"`` se usa el índice mensual del DANE: cada fecha toma el IPC de
su mes, así que dos fechas del mismo mes no muestran inflación entre ellas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from portafolio.core.inflacion import Indice, deflactar, flujos_reales, inflacion, rendimiento_real
from portafolio.core.twr import anualizar
from portafolio.core.xirr import xirr
from portafolio.data import repositorios
from portafolio.services import rendimientos
from portafolio.services.rendimientos import DIAS_MINIMOS_ANUALIZAR, ResultadoPeriodo, ResultadoTIR

SERIE_POR_DEFECTO = "UVR"


def cargar_indice(
    sesion: Session, codigo: str = SERIE_POR_DEFECTO, desde: date | None = None, hasta: date | None = None
) -> Indice:
    serie = repositorios.serie_por_codigo(sesion, codigo)
    if serie is None:
        raise repositorios.SerieNoEncontradaError(
            f"No hay serie '{codigo}'. Cárguela con: python -m portafolio series importar {codigo} <archivo>"
        )
    if desde is not None:
        desde = desde.replace(day=1)  # incluye el mes completo para series mensuales
    return Indice.crear(codigo, serie.frecuencia, repositorios.valores_de_serie(sesion, serie.id, desde, hasta))


@dataclass(frozen=True)
class ResultadoTIRReal:
    nominal: ResultadoTIR
    tasa_real: float
    serie: str
    # Flujos en pesos de la fecha de corte.
    flujos_reales: list[tuple[date, Decimal]]


@dataclass(frozen=True)
class ResultadoPeriodoReal:
    nominal: ResultadoPeriodo
    serie: str
    inflacion: float  # del periodo, no anualizada
    real: float
    real_anualizado: float | None

    @property
    def inflacion_anualizada(self) -> float | None:
        dias = self.nominal.dias
        return anualizar(self.inflacion, dias) if dias >= DIAS_MINIMOS_ANUALIZAR else None


def _tir_real(sesion: Session, resultado: ResultadoTIR, serie: str) -> ResultadoTIRReal:
    fechas = [f for f, _ in resultado.flujos]
    indice = cargar_indice(sesion, serie, min(fechas), resultado.fecha_corte)
    reales = flujos_reales(resultado.flujos, indice, resultado.fecha_corte)
    return ResultadoTIRReal(resultado, xirr(reales), serie, reales)


def tir_real_portafolio(
    sesion: Session, portafolio_id: int, fecha_corte: date, serie: str = SERIE_POR_DEFECTO
) -> ResultadoTIRReal:
    """TIR sobre los flujos expresados en pesos de la fecha de corte."""
    return _tir_real(sesion, rendimientos.tir_portafolio(sesion, portafolio_id, fecha_corte), serie)


def tir_real_instrumento(
    sesion: Session, instrumento_id: int, fecha_corte: date, serie: str = SERIE_POR_DEFECTO
) -> ResultadoTIRReal:
    return _tir_real(sesion, rendimientos.tir_instrumento(sesion, instrumento_id, fecha_corte), serie)


def _real(sesion: Session, resultado: ResultadoPeriodo, serie: str) -> ResultadoPeriodoReal:
    indice = cargar_indice(sesion, serie, resultado.fecha_inicio, resultado.fecha_fin)
    pi = inflacion(indice, resultado.fecha_inicio, resultado.fecha_fin)
    real = rendimiento_real(resultado.rendimiento, pi)
    anualizado = anualizar(real, resultado.dias) if resultado.dias >= DIAS_MINIMOS_ANUALIZAR else None
    return ResultadoPeriodoReal(resultado, serie, pi, real, anualizado)


def twr_real_portafolio(
    sesion: Session, portafolio_id: int, fecha_inicio: date, fecha_fin: date, serie: str = SERIE_POR_DEFECTO
) -> ResultadoPeriodoReal:
    return _real(sesion, rendimientos.twr_portafolio(sesion, portafolio_id, fecha_inicio, fecha_fin), serie)


def twr_real_instrumento(
    sesion: Session, instrumento_id: int, fecha_inicio: date, fecha_fin: date, serie: str = SERIE_POR_DEFECTO
) -> ResultadoPeriodoReal:
    return _real(sesion, rendimientos.twr_instrumento(sesion, instrumento_id, fecha_inicio, fecha_fin), serie)


def dietz_real_portafolio(
    sesion: Session, portafolio_id: int, fecha_inicio: date, fecha_fin: date, serie: str = SERIE_POR_DEFECTO
) -> ResultadoPeriodoReal:
    return _real(sesion, rendimientos.dietz_portafolio(sesion, portafolio_id, fecha_inicio, fecha_fin), serie)


def en_pesos_de(
    sesion: Session, monto: Decimal, fecha: date, fecha_base: date, serie: str = SERIE_POR_DEFECTO
) -> Decimal:
    """``monto`` de ``fecha`` expresado en pesos de ``fecha_base``."""
    indice = cargar_indice(sesion, serie, min(fecha, fecha_base), max(fecha, fecha_base))
    return deflactar(monto, indice, fecha, fecha_base)
