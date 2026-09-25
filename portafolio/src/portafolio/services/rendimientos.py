"""Rendimientos de portafolios e instrumentos: TIR, TWR y Dietz modificado.

* TIR (XIRR): ponderada por dinero. Mide lo que ganó el inversionista,
  incluido el efecto de cuándo aportó o retiró.
* TWR: ponderada por tiempo. Neutraliza aportes y retiros; mide la gestión y
  es la que se compara contra un índice o contra otro portafolio.
* Dietz modificado: aproximación ponderada por dinero para un periodo, útil
  cuando solo hay valoración al inicio y al final.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from portafolio.core.dietz import dietz_modificado
from portafolio.core.twr import Subperiodo, anualizar, twr
from portafolio.core.xirr import xirr
from portafolio.data import repositorios
from portafolio.data.modelos import Instrumento, Movimiento, TipoMovimiento, Valoracion

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

# Por debajo de un año el rendimiento no se anualiza (criterio GIPS): extrapolar
# unas semanas buenas a un año entero exagera.
DIAS_MINIMOS_ANUALIZAR = 365


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


@dataclass(frozen=True)
class ResultadoPeriodo:
    metodo: str  # "TWR" o "DIETZ"
    fecha_inicio: date
    fecha_fin: date
    rendimiento: float  # acumulado en el periodo
    anualizado: float | None  # None si el periodo es menor a un año
    valor_inicial: Decimal
    valor_final: Decimal
    # Neto de flujos externos en (inicio, fin]; positivo = entró dinero.
    flujo_neto: Decimal
    # False si algún flujo cayó entre valoraciones y se aproximó con Dietz.
    exacto: bool
    subperiodos: list[Subperiodo] = field(default_factory=list)
    # Fechas con valoraciones que no se usaron como corte porque algún otro
    # instrumento no tenía valoración vigente ese día.
    fechas_omitidas: list[date] = field(default_factory=list)

    @property
    def dias(self) -> int:
        return (self.fecha_fin - self.fecha_inicio).days


class _Libro:
    """Movimientos y valoraciones cargados una vez para valorar en cualquier fecha."""

    def __init__(
        self,
        instrumentos: list[Instrumento],
        movimientos: list[Movimiento],
        valoraciones: list[Valoracion],
        signos: dict[TipoMovimiento, int],
    ):
        self.instrumentos = instrumentos
        self.movimientos = movimientos
        self.signos = signos
        self._movs: dict[int, list[date]] = defaultdict(list)
        for m in movimientos:
            if m.instrumento_id is not None:
                self._movs[m.instrumento_id].append(m.fecha)
        self._vals: dict[int, list[Valoracion]] = defaultdict(list)
        for v in valoraciones:
            self._vals[v.instrumento_id].append(v)
        for lista in self._movs.values():
            lista.sort()
        for lista in self._vals.values():
            lista.sort(key=lambda v: v.fecha)

    @classmethod
    def de_portafolio(cls, sesion: Session, portafolio_id: int, hasta: date) -> _Libro:
        return cls(
            repositorios.instrumentos_de(sesion, portafolio_id),
            repositorios.movimientos_hasta(sesion, hasta, portafolio_id=portafolio_id),
            repositorios.valoraciones_hasta(sesion, hasta, portafolio_id=portafolio_id),
            SIGNO_PORTAFOLIO,
        )

    @classmethod
    def de_instrumento(cls, sesion: Session, instrumento_id: int, hasta: date) -> _Libro:
        instrumento = sesion.get(Instrumento, instrumento_id)
        if instrumento is None:
            raise LookupError(f"No existe el instrumento {instrumento_id}.")
        return cls(
            [instrumento],
            repositorios.movimientos_hasta(sesion, hasta, instrumento_id=instrumento_id),
            repositorios.valoraciones_hasta(sesion, hasta, instrumento_id=instrumento_id),
            SIGNO_INSTRUMENTO,
        )

    def _valor_instrumento(self, instrumento: Instrumento, fecha: date) -> tuple[Decimal, date | None]:
        vals = self._vals[instrumento.id]
        i = bisect_right([v.fecha for v in vals], fecha)
        valoracion = vals[i - 1] if i else None
        movs = self._movs[instrumento.id]
        j = bisect_right(movs, fecha)
        if not j:
            return (valoracion.valor, valoracion.fecha) if valoracion else (Decimal(0), None)
        ultimo = movs[j - 1]
        if valoracion is None or valoracion.fecha < ultimo:
            raise ValoracionFaltanteError(
                f"'{instrumento.nombre}' tiene movimientos hasta {ultimo} pero no una valoración "
                f"posterior al corte {fecha}. Registre una (0 si ya se liquidó)."
            )
        return valoracion.valor, valoracion.fecha

    def valor(self, fecha: date) -> tuple[Decimal, dict[int, date]]:
        """Valor al cierre de ``fecha`` y la fecha de valoración usada por instrumento."""
        total = Decimal(0)
        fechas: dict[int, date] = {}
        for instrumento in self.instrumentos:
            valor, fecha_val = self._valor_instrumento(instrumento, fecha)
            total += valor
            if fecha_val:
                fechas[instrumento.id] = fecha_val
        return total, fechas

    def flujos_inversionista(self, hasta: date) -> list[tuple[date, Decimal]]:
        return [
            (m.fecha, self.signos[m.tipo] * m.monto)
            for m in self.movimientos
            if m.tipo in self.signos and m.fecha <= hasta
        ]

    def flujos_activo(self, desde: date, hasta: date) -> list[tuple[date, Decimal]]:
        """Flujos externos en ``(desde, hasta]`` con signo del activo (entra = +)."""
        return [(f, -m) for f, m in self.flujos_inversionista(hasta) if f > desde]

    def fechas_con_valoracion(self, desde: date, hasta: date) -> list[date]:
        return sorted({v.fecha for vals in self._vals.values() for v in vals if desde < v.fecha < hasta})


# --------------------------------------------------------------------------
# TIR
# --------------------------------------------------------------------------


def _tir(libro: _Libro, fecha_corte: date) -> ResultadoTIR:
    valor_final, fechas = libro.valor(fecha_corte)
    flujos = libro.flujos_inversionista(fecha_corte)
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
    return _tir(_Libro.de_portafolio(sesion, portafolio_id, fecha_corte), fecha_corte)


def tir_instrumento(sesion: Session, instrumento_id: int, fecha_corte: date) -> ResultadoTIR:
    """TIR de un instrumento: compras, ventas, rendimientos pagados y valor al corte."""
    return _tir(_Libro.de_instrumento(sesion, instrumento_id, fecha_corte), fecha_corte)


# --------------------------------------------------------------------------
# Dietz modificado y TWR
# --------------------------------------------------------------------------


def _validar_periodo(fecha_inicio: date, fecha_fin: date) -> None:
    if fecha_fin <= fecha_inicio:
        raise ValueError("La fecha final debe ser posterior a la inicial.")


def _anualizado(rendimiento: float, dias: int) -> float | None:
    return anualizar(rendimiento, dias) if dias >= DIAS_MINIMOS_ANUALIZAR else None


def _dietz(libro: _Libro, fecha_inicio: date, fecha_fin: date) -> ResultadoPeriodo:
    _validar_periodo(fecha_inicio, fecha_fin)
    v0, _ = libro.valor(fecha_inicio)
    v1, _ = libro.valor(fecha_fin)
    flujos = libro.flujos_activo(fecha_inicio, fecha_fin)
    r = dietz_modificado(v0, v1, fecha_inicio, fecha_fin, flujos)
    return ResultadoPeriodo(
        metodo="DIETZ",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        rendimiento=r,
        anualizado=_anualizado(r, (fecha_fin - fecha_inicio).days),
        valor_inicial=v0,
        valor_final=v1,
        flujo_neto=sum((m for _, m in flujos), Decimal(0)),
        exacto=not any(f < fecha_fin for f, _ in flujos),
    )


def _twr(libro: _Libro, fecha_inicio: date, fecha_fin: date) -> ResultadoPeriodo:
    _validar_periodo(fecha_inicio, fecha_fin)
    v0, _ = libro.valor(fecha_inicio)
    v1, _ = libro.valor(fecha_fin)
    puntos = [(fecha_inicio, v0)]
    omitidas = []
    for fecha in libro.fechas_con_valoracion(fecha_inicio, fecha_fin):
        try:
            puntos.append((fecha, libro.valor(fecha)[0]))
        except ValoracionFaltanteError:
            omitidas.append(fecha)
    puntos.append((fecha_fin, v1))

    flujos = libro.flujos_activo(fecha_inicio, fecha_fin)
    resultado = twr(puntos, flujos)
    return ResultadoPeriodo(
        metodo="TWR",
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        rendimiento=resultado.rendimiento,
        anualizado=_anualizado(resultado.rendimiento, (fecha_fin - fecha_inicio).days),
        valor_inicial=v0,
        valor_final=v1,
        flujo_neto=sum((m for _, m in flujos), Decimal(0)),
        exacto=resultado.exacto,
        subperiodos=resultado.subperiodos,
        fechas_omitidas=omitidas,
    )


def dietz_portafolio(
    sesion: Session, portafolio_id: int, fecha_inicio: date, fecha_fin: date
) -> ResultadoPeriodo:
    """Dietz modificado del portafolio con su valor al inicio y al final del periodo."""
    return _dietz(_Libro.de_portafolio(sesion, portafolio_id, fecha_fin), fecha_inicio, fecha_fin)


def dietz_instrumento(
    sesion: Session, instrumento_id: int, fecha_inicio: date, fecha_fin: date
) -> ResultadoPeriodo:
    return _dietz(_Libro.de_instrumento(sesion, instrumento_id, fecha_fin), fecha_inicio, fecha_fin)


def twr_portafolio(
    sesion: Session, portafolio_id: int, fecha_inicio: date, fecha_fin: date
) -> ResultadoPeriodo:
    """TWR del portafolio, cortando en cada fecha con valoraciones.

    Para que sea exacto, registre una valoración de todos los instrumentos en
    cada fecha de aporte o retiro. Un instrumento sin valoración ese día usa la
    última anterior mientras no haya tenido movimientos desde entonces.
    """
    return _twr(_Libro.de_portafolio(sesion, portafolio_id, fecha_fin), fecha_inicio, fecha_fin)


def twr_instrumento(
    sesion: Session, instrumento_id: int, fecha_inicio: date, fecha_fin: date
) -> ResultadoPeriodo:
    return _twr(_Libro.de_instrumento(sesion, instrumento_id, fecha_fin), fecha_inicio, fecha_fin)
