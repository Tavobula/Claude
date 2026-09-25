"""Rendimientos de portafolios e instrumentos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from portafolio.core.xirr import xirr
from portafolio.data import repositorios
from portafolio.data.modelos import Instrumento, Movimiento, TipoMovimiento

# Signo del flujo visto por el inversionista: -1 sale de su bolsillo, +1 vuelve.
# A nivel de portafolio solo cuentan los flujos externos; lo demás ocurre
# dentro del portafolio y ya está reflejado en las valoraciones.
SIGNO_PORTAFOLIO: dict[TipoMovimiento, int] = {
    TipoMovimiento.APORTE: -1,
    TipoMovimiento.RETIRO: +1,
}

SIGNO_INSTRUMENTO: dict[TipoMovimiento, int] = {
    TipoMovimiento.APORTE: -1,
    TipoMovimiento.COMPRA: -1,
    TipoMovimiento.RETIRO: +1,
    TipoMovimiento.VENTA: +1,
    TipoMovimiento.DIVIDENDO: +1,
    TipoMovimiento.INTERES: +1,
    TipoMovimiento.IMPUESTO: -1,
    TipoMovimiento.COMISION: -1,
}


class ValoracionFaltanteError(LookupError):
    """Un instrumento con movimientos no tiene valoración utilizable al corte."""


@dataclass(frozen=True)
class ResultadoTIR:
    tasa: float
    fecha_corte: date
    valor_final: Decimal
    flujos: list[tuple[date, Decimal]]
    # Fecha de la valoración usada por instrumento, para advertir si es vieja.
    fechas_valoracion: dict[int, date] = field(default_factory=dict)


def _flujos(movimientos: list[Movimiento], signos: dict[TipoMovimiento, int]):
    return [(m.fecha, signos[m.tipo] * m.monto) for m in movimientos if m.tipo in signos]


def _valor_instrumento(
    sesion: Session, instrumento: Instrumento, movimientos: list[Movimiento], fecha_corte: date
) -> tuple[Decimal, date | None]:
    propios = [m for m in movimientos if m.instrumento_id == instrumento.id]
    valoracion = repositorios.ultima_valoracion(sesion, instrumento.id, fecha_corte)
    if not propios:
        return (valoracion.valor, valoracion.fecha) if valoracion else (Decimal(0), None)
    ultimo = max(m.fecha for m in propios)
    if valoracion is None or valoracion.fecha < ultimo:
        raise ValoracionFaltanteError(
            f"'{instrumento.nombre}' tiene movimientos hasta {ultimo} pero no una valoración "
            f"posterior al corte {fecha_corte}. Registre una (0 si ya se liquidó)."
        )
    return valoracion.valor, valoracion.fecha


def _resultado(flujos, valor_final, fecha_corte, fechas) -> ResultadoTIR:
    if valor_final:
        flujos = [*flujos, (fecha_corte, valor_final)]
    return ResultadoTIR(
        tasa=xirr(flujos),
        fecha_corte=fecha_corte,
        valor_final=valor_final,
        flujos=flujos,
        fechas_valoracion=fechas,
    )


def tir_portafolio(sesion: Session, portafolio_id: int, fecha_corte: date) -> ResultadoTIR:
    """TIR (XIRR) del portafolio: aportes y retiros más el valor de mercado al corte.

    El valor al corte es la suma de las valoraciones de sus instrumentos,
    incluidas las cuentas de efectivo (``TipoInstrumento.CUENTA``).
    """
    movimientos = repositorios.movimientos_hasta(sesion, fecha_corte, portafolio_id=portafolio_id)
    valor_final = Decimal(0)
    fechas: dict[int, date] = {}
    for instrumento in repositorios.instrumentos_de(sesion, portafolio_id):
        valor, fecha = _valor_instrumento(sesion, instrumento, movimientos, fecha_corte)
        valor_final += valor
        if fecha:
            fechas[instrumento.id] = fecha
    return _resultado(_flujos(movimientos, SIGNO_PORTAFOLIO), valor_final, fecha_corte, fechas)


def tir_instrumento(sesion: Session, instrumento_id: int, fecha_corte: date) -> ResultadoTIR:
    """TIR de un instrumento: compras, ventas, rendimientos pagados y valor al corte."""
    instrumento = sesion.get(Instrumento, instrumento_id)
    if instrumento is None:
        raise LookupError(f"No existe el instrumento {instrumento_id}.")
    movimientos = repositorios.movimientos_hasta(sesion, fecha_corte, instrumento_id=instrumento_id)
    valor, fecha = _valor_instrumento(sesion, instrumento, movimientos, fecha_corte)
    fechas = {instrumento_id: fecha} if fecha else {}
    return _resultado(_flujos(movimientos, SIGNO_INSTRUMENTO), valor, fecha_corte, fechas)
