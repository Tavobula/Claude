"""Consultas reutilizables. Los servicios las usan; la interfaz nunca."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.data.modelos import Instrumento, Movimiento, Parametro, Valoracion


class ParametroNoDefinidoError(LookupError):
    pass


def parametro_vigente(sesion: Session, nombre: str, fecha: date) -> Decimal:
    consulta = (
        select(Parametro.valor)
        .where(Parametro.nombre == nombre, Parametro.vigente_desde <= fecha)
        .order_by(Parametro.vigente_desde.desc())
        .limit(1)
    )
    valor = sesion.scalar(consulta)
    if valor is None:
        raise ParametroNoDefinidoError(f"No hay valor de '{nombre}' vigente al {fecha}.")
    return valor


def movimientos_hasta(
    sesion: Session,
    fecha_corte: date,
    *,
    portafolio_id: int | None = None,
    instrumento_id: int | None = None,
) -> list[Movimiento]:
    consulta = select(Movimiento).where(Movimiento.fecha <= fecha_corte)
    if portafolio_id is not None:
        consulta = consulta.where(Movimiento.portafolio_id == portafolio_id)
    if instrumento_id is not None:
        consulta = consulta.where(Movimiento.instrumento_id == instrumento_id)
    return list(sesion.scalars(consulta.order_by(Movimiento.fecha, Movimiento.id)))


def instrumentos_de(sesion: Session, portafolio_id: int) -> list[Instrumento]:
    consulta = select(Instrumento).where(Instrumento.portafolio_id == portafolio_id)
    return list(sesion.scalars(consulta.order_by(Instrumento.id)))


def ultima_valoracion(sesion: Session, instrumento_id: int, fecha_corte: date) -> Valoracion | None:
    consulta = (
        select(Valoracion)
        .where(Valoracion.instrumento_id == instrumento_id, Valoracion.fecha <= fecha_corte)
        .order_by(Valoracion.fecha.desc())
        .limit(1)
    )
    return sesion.scalar(consulta)


def valoraciones_hasta(
    sesion: Session,
    fecha_corte: date,
    *,
    portafolio_id: int | None = None,
    instrumento_id: int | None = None,
) -> list[Valoracion]:
    consulta = select(Valoracion).where(Valoracion.fecha <= fecha_corte)
    if portafolio_id is not None:
        consulta = consulta.where(Valoracion.portafolio_id == portafolio_id)
    if instrumento_id is not None:
        consulta = consulta.where(Valoracion.instrumento_id == instrumento_id)
    return list(sesion.scalars(consulta.order_by(Valoracion.fecha, Valoracion.id)))
