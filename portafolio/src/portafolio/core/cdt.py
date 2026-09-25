"""Certificados de depósito a término (CDT) con tasa fija.

Convenciones (verifíquelas contra el extracto de su banco):

* La tasa se convierte primero a efectiva anual (E.A.). Los intereses de un
  periodo de ``d`` días son ``capital * ((1 + EA) ** (d / base) - 1)``, con
  días calendario reales y base 365 (o 360 si el título lo dice).
* Los periodos se cuentan desde la emisión (``emision + k`` meses). Si el
  vencimiento no cae en un múltiplo exacto, el último periodo es más corto.
* Si una fecha de pago cae en fin de semana o festivo, se paga el siguiente
  día hábil. Los intereses se causan solo hasta la fecha nominal: los días de
  espera no generan intereses adicionales.
* Una valoración es el valor al cierre del día. El día de pago el interés ya
  salió del CDT, así que el valor vuelve al capital (o a 0 al vencimiento).
* Por ahora solo se proyectan CDT de modalidad vencida. La modalidad
  anticipada se acepta para convertir tasas y comparar ofertas.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from portafolio.core.calendario import siguiente_dia_habil, sumar_meses
from portafolio.core.dinero import redondear


class TipoTasa(str, enum.Enum):
    EFECTIVA_ANUAL = "EFECTIVA_ANUAL"  # E.A.
    NOMINAL = "NOMINAL"  # N.M.V., N.T.V., N.S.V., según la periodicidad


class Modalidad(str, enum.Enum):
    VENCIDA = "VENCIDA"
    ANTICIPADA = "ANTICIPADA"


class Periodicidad(str, enum.Enum):
    MENSUAL = "MENSUAL"
    BIMESTRAL = "BIMESTRAL"
    TRIMESTRAL = "TRIMESTRAL"
    SEMESTRAL = "SEMESTRAL"
    ANUAL = "ANUAL"
    AL_VENCIMIENTO = "AL_VENCIMIENTO"

    @property
    def meses(self) -> int | None:
        return {
            "MENSUAL": 1,
            "BIMESTRAL": 2,
            "TRIMESTRAL": 3,
            "SEMESTRAL": 6,
            "ANUAL": 12,
        }.get(self.value)


def _potencia(base: Decimal, exponente: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        return base**exponente


def tasa_efectiva_anual(
    tasa: Decimal,
    tipo: TipoTasa,
    periodicidad: Periodicidad,
    modalidad: Modalidad = Modalidad.VENCIDA,
) -> Decimal:
    """Convierte la tasa pactada a efectiva anual vencida.

    * Nominal: la tasa periódica es ``tasa / n``, con ``n`` periodos por año
      según la periodicidad (12 para N.M.V.).
    * Anticipada: la tasa periódica anticipada ``ia`` equivale a la vencida
      ``ia / (1 - ia)``.
    """
    tasa = Decimal(tasa)
    meses = periodicidad.meses
    if tipo is TipoTasa.EFECTIVA_ANUAL:
        if modalidad is Modalidad.VENCIDA:
            return tasa
        # E.A. anticipada: un periodo de un año.
        return tasa / (1 - tasa)
    if meses is None:
        raise ValueError("Una tasa nominal necesita una periodicidad de pago (N.M.V., N.T.V., ...).")
    n = Decimal(12 // meses)
    periodica = tasa / n
    if modalidad is Modalidad.ANTICIPADA:
        if periodica >= 1:
            raise ValueError("Tasa anticipada inválida.")
        periodica = periodica / (1 - periodica)
    return _potencia(1 + periodica, n) - 1


@dataclass(frozen=True)
class TerminosCDT:
    capital: Decimal
    fecha_emision: date
    fecha_vencimiento: date
    tasa: Decimal  # fracción: 0.105 = 10,5 %
    tipo_tasa: TipoTasa = TipoTasa.EFECTIVA_ANUAL
    periodicidad: Periodicidad = Periodicidad.AL_VENCIMIENTO
    modalidad: Modalidad = Modalidad.VENCIDA
    base_dias: int = 365

    def __post_init__(self):
        if self.fecha_vencimiento <= self.fecha_emision:
            raise ValueError("El vencimiento debe ser posterior a la emisión.")
        if self.capital <= 0:
            raise ValueError("El capital debe ser positivo.")
        if self.base_dias not in (360, 365):
            raise ValueError("La base de días debe ser 360 o 365.")

    @property
    def tasa_ea(self) -> Decimal:
        return tasa_efectiva_anual(self.tasa, self.tipo_tasa, self.periodicidad, self.modalidad)


@dataclass(frozen=True)
class PeriodoCDT:
    inicio: date
    fin: date  # fecha nominal de corte
    fecha_pago: date  # día hábil en que se paga
    dias: int
    interes: Decimal  # bruto, antes de retención
    capital: Decimal  # devuelto en este pago (solo el último)


def interes_por_dias(capital: Decimal, tasa_ea: Decimal, dias: int, base_dias: int) -> Decimal:
    if dias <= 0:
        return Decimal(0)
    factor = _potencia(1 + tasa_ea, Decimal(dias) / Decimal(base_dias))
    return redondear(capital * (factor - 1))


def _fechas_corte(terminos: TerminosCDT) -> list[date]:
    meses = terminos.periodicidad.meses
    cortes = []
    if meses:
        k = 1
        while (corte := sumar_meses(terminos.fecha_emision, k * meses)) < terminos.fecha_vencimiento:
            cortes.append(corte)
            k += 1
    cortes.append(terminos.fecha_vencimiento)
    return cortes


def calendario_pagos(terminos: TerminosCDT) -> list[PeriodoCDT]:
    if terminos.modalidad is Modalidad.ANTICIPADA:
        raise NotImplementedError("La proyección de CDT con intereses anticipados no está soportada.")
    tasa_ea = terminos.tasa_ea
    periodos, inicio = [], terminos.fecha_emision
    cortes = _fechas_corte(terminos)
    for fin in cortes:
        dias = (fin - inicio).days
        periodos.append(
            PeriodoCDT(
                inicio=inicio,
                fin=fin,
                fecha_pago=siguiente_dia_habil(fin),
                dias=dias,
                interes=interes_por_dias(terminos.capital, tasa_ea, dias, terminos.base_dias),
                capital=terminos.capital if fin == terminos.fecha_vencimiento else Decimal(0),
            )
        )
        inicio = fin
    return periodos


@dataclass(frozen=True)
class Causacion:
    fecha: date
    capital: Decimal  # capital aún dentro del CDT
    interes_causado: Decimal  # causado y no pagado al cierre de ``fecha``

    @property
    def valor(self) -> Decimal:
        return self.capital + self.interes_causado


def causacion(terminos: TerminosCDT, fecha: date) -> Causacion:
    """Capital e intereses causados sin pagar al cierre de ``fecha``."""
    if fecha < terminos.fecha_emision:
        return Causacion(fecha, Decimal(0), Decimal(0))
    periodos = calendario_pagos(terminos)
    if fecha >= periodos[-1].fecha_pago:
        return Causacion(fecha, Decimal(0), Decimal(0))

    interes = Decimal(0)
    for p in periodos:
        if p.fin <= fecha < p.fecha_pago:
            interes += p.interes  # ya se causó; se paga el siguiente día hábil
        elif p.inicio <= fecha < p.fin:
            dias = (fecha - p.inicio).days
            interes += interes_por_dias(terminos.capital, terminos.tasa_ea, dias, terminos.base_dias)
    return Causacion(fecha, terminos.capital, interes)
