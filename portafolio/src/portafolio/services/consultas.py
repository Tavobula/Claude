"""Consultas de lectura para la interfaz: posiciones, evolución y resumen.

Los errores esperables (una valoración faltante, una serie sin cargar) no se
propagan: se devuelven como avisos, para que la interfaz muestre lo que sí se
puede calcular.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.dietz import DenominadorInvalidoError
from portafolio.core.inflacion import ValorNoDisponibleError
from portafolio.core.xirr import SinSolucionError
from portafolio.data.modelos import Instrumento, Movimiento, Portafolio, TipoMovimiento, Usuario
from portafolio.data.repositorios import SerieNoEncontradaError
from portafolio.services import inflacion, rendimientos
from portafolio.services.rendimientos import Libro, ValoracionFaltanteError

ERRORES_CALCULO = (
    ValoracionFaltanteError,
    SinSolucionError,
    DenominadorInvalidoError,
    ValorNoDisponibleError,
    SerieNoEncontradaError,
    ValueError,
)


def usuarios(sesion: Session) -> list[Usuario]:
    return list(sesion.scalars(select(Usuario).order_by(Usuario.id)))


def portafolios_de(sesion: Session, usuario_id: int) -> list[Portafolio]:
    return list(sesion.scalars(select(Portafolio).where(Portafolio.usuario_id == usuario_id).order_by(Portafolio.id)))


def instrumentos_de(sesion: Session, portafolio_id: int) -> list[Instrumento]:
    return list(
        sesion.scalars(select(Instrumento).where(Instrumento.portafolio_id == portafolio_id).order_by(Instrumento.nombre))
    )


def movimientos_de(sesion: Session, portafolio_id: int, limite: int = 500) -> list[Movimiento]:
    consulta = (
        select(Movimiento)
        .where(Movimiento.portafolio_id == portafolio_id)
        .order_by(Movimiento.fecha.desc(), Movimiento.id.desc())
        .limit(limite)
    )
    return list(sesion.scalars(consulta))


def primera_fecha(sesion: Session, portafolio_id: int) -> date | None:
    return sesion.scalar(select(Movimiento.fecha).where(Movimiento.portafolio_id == portafolio_id).order_by(Movimiento.fecha).limit(1))


@dataclass(frozen=True)
class Posicion:
    instrumento_id: int
    nombre: str
    tipo: str
    valor: Decimal | None  # None si no se pudo valorar
    fecha_valoracion: date | None
    peso: float | None
    aviso: str | None = None


def posiciones(sesion: Session, portafolio_id: int, fecha: date) -> list[Posicion]:
    libro = Libro.de_portafolio(sesion, portafolio_id, fecha)
    filas = []
    for instrumento in libro.instrumentos:
        try:
            valor, fecha_val = libro.valor_instrumento(instrumento, fecha)
            filas.append((instrumento, valor, fecha_val, None))
        except ValoracionFaltanteError as error:
            filas.append((instrumento, None, None, str(error)))
    total = sum((v for _, v, _, _ in filas if v is not None), Decimal(0))
    resultado = [
        Posicion(
            i.id,
            i.nombre,
            i.tipo.value,
            v,
            f,
            float(v / total) if v is not None and total else None,
            aviso,
        )
        for i, v, f, aviso in filas
        if aviso or v or f  # omite instrumentos sin historia a la fecha
    ]
    return sorted(resultado, key=lambda p: p.valor or 0, reverse=True)


@dataclass(frozen=True)
class PuntoEvolucion:
    fecha: date
    valor: Decimal
    aportes_netos: Decimal  # aportes menos retiros acumulados


def evolucion(sesion: Session, portafolio_id: int, desde: date, hasta: date) -> list[PuntoEvolucion]:
    """Valor del portafolio en cada fecha con valoraciones completas."""
    libro = Libro.de_portafolio(sesion, portafolio_id, hasta)
    fechas = sorted({desde, hasta, *libro.fechas_con_valoracion(desde, hasta)})
    externos = sorted(
        (m.fecha, m.monto if m.tipo is TipoMovimiento.APORTE else -m.monto)
        for m in libro.movimientos
        if m.tipo in (TipoMovimiento.APORTE, TipoMovimiento.RETIRO)
    )
    puntos, acumulado, i = [], Decimal(0), 0
    for fecha in fechas:
        while i < len(externos) and externos[i][0] <= fecha:
            acumulado += externos[i][1]
            i += 1
        try:
            valor, _ = libro.valor(fecha)
        except ValoracionFaltanteError:
            continue
        puntos.append(PuntoEvolucion(fecha, valor, acumulado))
    return puntos


@dataclass(frozen=True)
class Resumen:
    fecha: date
    valor: Decimal | None
    aportes_netos: Decimal
    tir: float | None
    tir_real: float | None
    twr_anio: float | None  # año corrido
    avisos: list[str] = field(default_factory=list)

    @property
    def ganancia(self) -> Decimal | None:
        return None if self.valor is None else self.valor - self.aportes_netos


def resumen(sesion: Session, portafolio_id: int, fecha: date, serie: str = inflacion.SERIE_POR_DEFECTO) -> Resumen:
    avisos: list[str] = []
    libro = Libro.de_portafolio(sesion, portafolio_id, fecha)
    aportes = sum(
        (-m for _, m in libro.flujos_inversionista(fecha)),
        Decimal(0),
    )

    def intentar(funcion, etiqueta):
        try:
            return funcion()
        except ERRORES_CALCULO as error:
            avisos.append(f"{etiqueta}: {error}")
            return None

    valor = intentar(lambda: libro.valor(fecha)[0], "Valor")
    tir = tir_real = twr_anio = None
    if valor is not None and libro.movimientos:
        resultado_tir = intentar(lambda: rendimientos.tir_portafolio(sesion, portafolio_id, fecha), "TIR")
        tir = resultado_tir.tasa if resultado_tir else None
        if resultado_tir:
            real = intentar(lambda: inflacion.tir_real_portafolio(sesion, portafolio_id, fecha, serie), "TIR real")
            tir_real = real.tasa_real if real else None
        cierre_anterior = date(fecha.year - 1, 12, 31)
        twr = intentar(lambda: rendimientos.twr_portafolio(sesion, portafolio_id, cierre_anterior, fecha), "TWR del año")
        twr_anio = twr.rendimiento if twr else None
    return Resumen(fecha, valor, aportes, tir, tir_real, twr_anio, avisos)
