"""Carga y actualización de series globales (UVR, IPC, IBR, TRM, FIC)."""

from __future__ import annotations

import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.inflacion import normalizar_fecha
from portafolio.data import repositorios
from portafolio.data.modelos import Parametro, Serie, ValorSerie
from portafolio.data.tipos import Tasa, sin_ceros
from portafolio.sources import archivo
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


_ESCALA = Decimal(1).scaleb(-Tasa.escala)


def guardar_observaciones(
    sesion: Session, definicion: DefinicionSerie, observaciones: Iterable[Observacion]
) -> ResumenCarga:
    """Inserta o corrige valores (redondeados a 10 decimales). Un valor corregido por la fuente se actualiza."""
    serie = asegurar_serie(sesion, definicion)
    por_fecha: dict[date, Observacion] = {}
    for o in observaciones:
        fecha = normalizar_fecha(o.fecha, definicion.frecuencia)
        if o.valor <= 0 and definicion.unidad != "tasa":
            raise ValueError(f"{definicion.codigo}: valor no positivo el {fecha}.")
        # Las fuentes (y Excel) pueden traer más decimales que la columna: se
        # redondea aquí, a la vista, en lugar de dejar que cada motor decida.
        por_fecha[fecha] = Observacion(fecha, sin_ceros(o.valor.quantize(_ESCALA, rounding=ROUND_HALF_EVEN)))
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


def importar_archivo(
    sesion: Session,
    definicion: DefinicionSerie,
    contenido: bytes,
    nombre_archivo: str,
    *,
    codificacion: str = "utf-8-sig",
    hoja: str | None = None,
    **opciones,
) -> ResumenCarga:
    """Carga una serie desde el contenido de un CSV o Excel (subido o leído de disco).

    ``opciones`` son las de ``sources.archivo.leer_filas`` (columnas, decimal,
    formato de fecha, escala).
    """
    if PurePath(nombre_archivo).suffix.lower() in (".xlsx", ".xlsm"):
        observaciones = archivo.leer_excel(io.BytesIO(contenido), hoja, **opciones)
    else:
        try:
            texto = contenido.decode(codificacion)
        except UnicodeDecodeError:
            texto = contenido.decode("latin-1")  # típico de CSV guardados desde Excel en Windows
        observaciones = archivo.leer_csv(io.StringIO(texto, newline=""), **opciones)
    return guardar_observaciones(sesion, definicion, observaciones)


@dataclass(frozen=True)
class InfoSerie:
    codigo: str
    nombre: str
    frecuencia: str
    fuente: str | None
    datos: int
    primera: date | None
    ultima: date | None


def listar_series(sesion: Session) -> list[InfoSerie]:
    resultado = []
    for serie in sesion.scalars(select(Serie).order_by(Serie.codigo)):
        valores = repositorios.valores_de_serie(sesion, serie.id)
        resultado.append(
            InfoSerie(
                serie.codigo,
                serie.nombre,
                serie.frecuencia.value,
                serie.fuente,
                len(valores),
                valores[0][0] if valores else None,
                valores[-1][0] if valores else None,
            )
        )
    return resultado


def listar_parametros(sesion: Session) -> list[Parametro]:
    return list(sesion.scalars(select(Parametro).order_by(Parametro.nombre, Parametro.vigente_desde)))
