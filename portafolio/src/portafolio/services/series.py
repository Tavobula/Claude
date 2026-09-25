"""Carga y actualización de series globales (UVR, IPC, IBR, TRM, FIC)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.inflacion import normalizar_fecha
from portafolio.data import repositorios
from portafolio.data.modelos import Serie, ValorSerie
from portafolio.sources.base import Conector, DefinicionSerie, Observacion


@dataclass(frozen=True)
class ResumenCarga:
    codigo: str
    nuevas: int
    actualizadas: int
    sin_cambio: int
    desde: date | None
    hasta: date | None


def asegurar_serie(sesion: Session, definicion: DefinicionSerie) -> Serie:
    """Crea la serie si no existe y actualiza sus metadatos si cambiaron."""
    serie = repositorios.serie_por_codigo(sesion, definicion.codigo)
    if serie is None:
        serie = Serie(codigo=definicion.codigo)
        sesion.add(serie)
    serie.nombre = definicion.nombre
    serie.tipo = definicion.tipo
    serie.frecuencia = definicion.frecuencia
    serie.fuente = definicion.fuente
    serie.unidad = definicion.unidad
    sesion.flush()
    return serie


def guardar_observaciones(
    sesion: Session, definicion: DefinicionSerie, observaciones: Iterable[Observacion]
) -> ResumenCarga:
    """Inserta o corrige valores. Un valor corregido por la fuente se actualiza."""
    serie = asegurar_serie(sesion, definicion)
    por_fecha: dict[date, Observacion] = {}
    for o in observaciones:
        fecha = normalizar_fecha(o.fecha, definicion.frecuencia)
        if o.valor <= 0 and definicion.unidad != "tasa":
            raise ValueError(f"{definicion.codigo}: valor no positivo el {fecha}.")
        por_fecha[fecha] = Observacion(fecha, o.valor)
    if not por_fecha:
        return ResumenCarga(definicion.codigo, 0, 0, 0, None, None)

    desde, hasta = min(por_fecha), max(por_fecha)
    existentes = {
        v.fecha: v
        for v in sesion.scalars(
            select(ValorSerie).where(
                ValorSerie.serie_id == serie.id, ValorSerie.fecha >= desde, ValorSerie.fecha <= hasta
            )
        )
    }
    nuevas = actualizadas = sin_cambio = 0
    for fecha, o in sorted(por_fecha.items()):
        actual = existentes.get(fecha)
        if actual is None:
            sesion.add(ValorSerie(serie_id=serie.id, fecha=fecha, valor=o.valor))
            nuevas += 1
        elif actual.valor != o.valor:
            actual.valor = o.valor
            actualizadas += 1
        else:
            sin_cambio += 1
    sesion.flush()
    return ResumenCarga(definicion.codigo, nuevas, actualizadas, sin_cambio, desde, hasta)


def actualizar_desde_fuente(sesion: Session, conector: Conector, desde: date, hasta: date) -> ResumenCarga:
    return guardar_observaciones(sesion, conector.definicion, conector.descargar(desde, hasta))


def ultima_fecha(sesion: Session, codigo: str) -> date | None:
    serie = repositorios.serie_por_codigo(sesion, codigo)
    if serie is None:
        return None
    valores = repositorios.valores_de_serie(sesion, serie.id)
    return valores[-1][0] if valores else None
