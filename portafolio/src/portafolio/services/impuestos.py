"""GMF de las cuentas del portafolio.

Se calcula sobre los RETIRO registrados en una cuenta (``TipoInstrumento.CUENTA``).
Si la cuenta está marcada como exenta (``exenta_gmf``), cada mes están exentos
los primeros ``gmf_tope_exento_uvt`` x UVT retirados.

Limitación: el modelo no registra de qué cuenta sale el dinero de una COMPRA,
así que el GMF de esas transferencias no se estima aquí.
"""

from __future__ import annotations

from datetime import date
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.impuestos import CargoGMF, gmf
from portafolio.data.modelos import Instrumento, Movimiento, TipoInstrumento, TipoMovimiento
from portafolio.services import parametros


def gmf_cuenta(sesion: Session, instrumento_id: int, desde: date, hasta: date) -> list[CargoGMF]:
    """GMF de cada retiro de la cuenta entre ``desde`` y ``hasta`` (inclusive)."""
    cuenta = sesion.get(Instrumento, instrumento_id)
    if cuenta is None or cuenta.tipo is not TipoInstrumento.CUENTA:
        raise ValueError(f"El instrumento {instrumento_id} no es una cuenta.")

    # La exención es mensual: se leen los retiros desde el inicio del mes de ``desde``.
    retiros = sesion.scalars(
        select(Movimiento)
        .where(
            Movimiento.instrumento_id == instrumento_id,
            Movimiento.tipo == TipoMovimiento.RETIRO,
            Movimiento.fecha >= desde.replace(day=1),
            Movimiento.fecha <= hasta,
        )
        .order_by(Movimiento.fecha, Movimiento.id)
    )
    cargos: list[CargoGMF] = []
    for (anio, mes), del_mes in groupby(retiros, key=lambda m: (m.fecha.year, m.fecha.month)):
        inicio_mes = date(anio, mes, 1)
        tarifa = parametros.obligatorio(sesion, parametros.GMF_TARIFA, inicio_mes)
        tope = None
        if cuenta.exenta_gmf:
            uvt = parametros.obligatorio(sesion, parametros.UVT, inicio_mes)
            tope = uvt * parametros.obligatorio(sesion, parametros.GMF_TOPE_EXENTO_UVT, inicio_mes)
        cargos += gmf([(m.fecha, m.monto) for m in del_mes], tarifa, tope)
    return [c for c in cargos if c.fecha >= desde]
