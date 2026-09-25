"""Casos de uso de CDT: proyección, causación y registro automático.

Las convenciones de cálculo están en ``portafolio.core.cdt``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.calendario import sumar_meses
from portafolio.core.cdt import Causacion, PeriodoCDT, TerminosCDT, calendario_pagos, causacion
from portafolio.core.impuestos import retencion_rendimientos
from portafolio.data.modelos import (
    CondicionCDT,
    Instrumento,
    Movimiento,
    TipoInstrumento,
    TipoMovimiento,
    Valoracion,
)
from portafolio.services import parametros


class CDTSinCondicionesError(LookupError):
    pass


@dataclass(frozen=True)
class PagoCDT:
    periodo: PeriodoCDT
    retencion: Decimal

    @property
    def interes_neto(self) -> Decimal:
        return self.periodo.interes - self.retencion

    @property
    def total_recibido(self) -> Decimal:
        return self.interes_neto + self.periodo.capital


@dataclass(frozen=True)
class EstadoCDT:
    causacion: Causacion
    # Retención que se practicaría si lo causado se pagara hoy.
    retencion_estimada: Decimal

    @property
    def valor_bruto(self) -> Decimal:
        return self.causacion.valor

    @property
    def valor_neto_estimado(self) -> Decimal:
        return self.causacion.valor - self.retencion_estimada


@dataclass(frozen=True)
class ResumenSincronizacion:
    movimientos_creados: int
    valoraciones_creadas: int


def _condicion(sesion: Session, instrumento_id: int) -> CondicionCDT:
    condicion = sesion.get(CondicionCDT, instrumento_id)
    if condicion is None:
        instrumento = sesion.get(Instrumento, instrumento_id)
        nombre = instrumento.nombre if instrumento else instrumento_id
        raise CDTSinCondicionesError(f"'{nombre}' no tiene condiciones de CDT registradas.")
    return condicion


def terminos_cdt(sesion: Session, instrumento_id: int) -> TerminosCDT:
    c = _condicion(sesion, instrumento_id)
    base = c.base_dias or int(
        parametros.opcional(sesion, parametros.BASE_DIAS, c.fecha_emision, Decimal(365))
    )
    return TerminosCDT(
        capital=c.capital,
        fecha_emision=c.fecha_emision,
        fecha_vencimiento=c.fecha_vencimiento,
        tasa=c.tasa,
        tipo_tasa=c.tipo_tasa,
        periodicidad=c.periodicidad,
        modalidad=c.modalidad,
        base_dias=base,
    )


def _retencion(sesion: Session, interes: Decimal, fecha: date) -> Decimal:
    tarifa = parametros.obligatorio(sesion, parametros.RETENCION_CDT, fecha)
    componente = parametros.opcional(sesion, parametros.COMPONENTE_INFLACIONARIO, fecha, Decimal(0))
    return retencion_rendimientos(interes, tarifa, componente)


def proyectar_cdt(sesion: Session, instrumento_id: int) -> list[PagoCDT]:
    """Todos los pagos del CDT con la retención vigente en cada fecha de pago."""
    return [
        PagoCDT(p, _retencion(sesion, p.interes, p.fecha_pago))
        for p in calendario_pagos(terminos_cdt(sesion, instrumento_id))
    ]


def estado_cdt(sesion: Session, instrumento_id: int, fecha: date) -> EstadoCDT:
    """Capital e intereses causados al cierre de ``fecha``."""
    c = causacion(terminos_cdt(sesion, instrumento_id), fecha)
    return EstadoCDT(c, _retencion(sesion, c.interes_causado, fecha))


def _fechas_valoracion(terminos: TerminosCDT, periodos: list[PeriodoCDT], hasta: date) -> list[date]:
    fin = min(hasta, periodos[-1].fecha_pago)
    fechas = {terminos.fecha_emision, fin}
    for p in periodos:
        fechas.update({p.fin, p.fecha_pago})
    k = 0
    while (fin_mes := sumar_meses(terminos.fecha_emision.replace(day=1), k + 1) - timedelta(days=1)) <= fin:
        fechas.add(fin_mes)
        k += 1
    return sorted(f for f in fechas if terminos.fecha_emision <= f <= fin)


def sincronizar_cdt(
    sesion: Session,
    instrumento_id: int,
    hasta: date,
    *,
    incluir_compra: bool = True,
) -> ResumenSincronizacion:
    """Registra los movimientos y valoraciones del CDT hasta ``hasta``.

    * Movimientos: COMPRA en la emisión (si ``incluir_compra``), INTERES e
      IMPUESTO (retención) en cada fecha de pago, y VENTA del capital al
      vencimiento. Cada uno lleva una ``clave_generacion`` y no se repite si
      ya existe, así que se puede correr cuantas veces se quiera.
    * Valoraciones: en la emisión, en cada corte y pago, en cada fin de mes y
      en ``hasta``. Solo se agregan las fechas sin valoración; una registrada
      a mano (p. ej. del extracto) no se reemplaza.
    """
    instrumento = sesion.get(Instrumento, instrumento_id)
    if instrumento is None or instrumento.tipo is not TipoInstrumento.CDT:
        raise ValueError(f"El instrumento {instrumento_id} no es un CDT.")
    terminos = terminos_cdt(sesion, instrumento_id)
    periodos = calendario_pagos(terminos)

    deseados: list[tuple[str, date, TipoMovimiento, Decimal]] = []
    if incluir_compra:
        deseados.append(("cdt:compra", terminos.fecha_emision, TipoMovimiento.COMPRA, terminos.capital))
    for p in periodos:
        if p.fecha_pago > hasta:
            break
        dia = p.fecha_pago.isoformat()
        deseados.append((f"cdt:interes:{dia}", p.fecha_pago, TipoMovimiento.INTERES, p.interes))
        retencion = _retencion(sesion, p.interes, p.fecha_pago)
        if retencion:
            deseados.append((f"cdt:retencion:{dia}", p.fecha_pago, TipoMovimiento.IMPUESTO, retencion))
        if p.capital:
            deseados.append(("cdt:capital", p.fecha_pago, TipoMovimiento.VENTA, p.capital))

    existentes = set(
        sesion.scalars(
            select(Movimiento.clave_generacion).where(
                Movimiento.instrumento_id == instrumento_id, Movimiento.clave_generacion.is_not(None)
            )
        )
    )
    nuevos_mov = [
        Movimiento(
            usuario_id=instrumento.usuario_id,
            portafolio_id=instrumento.portafolio_id,
            instrumento_id=instrumento_id,
            fecha=fecha,
            tipo=tipo,
            monto=monto,
            clave_generacion=clave,
            nota="Generado desde las condiciones del CDT",
        )
        for clave, fecha, tipo, monto in deseados
        if clave not in existentes and fecha <= hasta
    ]

    valoradas = set(sesion.scalars(select(Valoracion.fecha).where(Valoracion.instrumento_id == instrumento_id)))
    nuevas_val = []
    if hasta >= terminos.fecha_emision:
        nuevas_val = [
            Valoracion(
                usuario_id=instrumento.usuario_id,
                portafolio_id=instrumento.portafolio_id,
                instrumento_id=instrumento_id,
                fecha=fecha,
                valor=causacion(terminos, fecha).valor,
            )
            for fecha in _fechas_valoracion(terminos, periodos, hasta)
            if fecha not in valoradas
        ]

    sesion.add_all(nuevos_mov + nuevas_val)
    sesion.flush()
    return ResumenSincronizacion(len(nuevos_mov), len(nuevas_val))
