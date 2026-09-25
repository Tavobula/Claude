"""Importación y exportación de movimientos y valoraciones en CSV.

Formato: UTF-8, separador coma, fechas ISO (``2024-03-15``), montos con punto
decimal y sin separador de miles (``1250000.50``). El instrumento se indica por
su nombre dentro del portafolio; debe existir antes de importar.

Movimientos:   fecha,instrumento,tipo,monto,nota
Valoraciones:  fecha,instrumento,valor
Parámetros:    nombre,vigente_desde,valor,descripcion   (globales, no de un portafolio)
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.data import repositorios
from portafolio.data.modelos import Movimiento, Parametro, Portafolio, TipoMovimiento, Valoracion

COLUMNAS_MOVIMIENTOS = ["fecha", "instrumento", "tipo", "monto", "nota"]
COLUMNAS_VALORACIONES = ["fecha", "instrumento", "valor"]
COLUMNAS_PARAMETROS = ["nombre", "vigente_desde", "valor", "descripcion"]
_SOBRANTES = "__sobrantes__"


class ErrorImportacion(ValueError):
    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("\n".join(errores))


def _decimal(texto: str) -> Decimal:
    valor = Decimal(texto.strip())
    if not valor.is_finite():
        raise InvalidOperation
    return valor


def _leer(archivo: TextIO, columnas: list[str], portafolio: Portafolio, sesion: Session):
    lector = csv.DictReader(archivo, restkey=_SOBRANTES)
    faltantes = set(columnas) - set(lector.fieldnames or [])
    faltantes.discard("nota")
    if faltantes:
        raise ErrorImportacion([f"Faltan columnas: {', '.join(sorted(faltantes))}"])
    instrumentos = {i.nombre: i for i in repositorios.instrumentos_de(sesion, portafolio.id)}
    for n, fila in enumerate(lector, start=2):  # la fila 1 es el encabezado
        yield n, fila, instrumentos


def _validar_ancho(fila: dict) -> None:
    if fila.get(_SOBRANTES):
        # Típico de "1.234,56": la coma decimal parte el monto en dos columnas.
        raise ValueError("hay columnas de más (¿coma decimal o separador de miles?)")


def importar_movimientos(sesion: Session, portafolio: Portafolio, archivo: TextIO) -> int:
    """Valida todo el archivo y solo si no hay errores agrega los movimientos."""
    nuevos, errores = [], []
    for n, fila, instrumentos in _leer(archivo, COLUMNAS_MOVIMIENTOS, portafolio, sesion):
        try:
            _validar_ancho(fila)
            nombre = (fila.get("instrumento") or "").strip()
            instrumento = instrumentos.get(nombre) if nombre else None
            if nombre and instrumento is None:
                raise ValueError(f"instrumento desconocido '{nombre}'")
            monto = _decimal(fila["monto"])
            if monto < 0:
                raise ValueError("el monto debe ser positivo; el signo lo da el tipo")
            nuevos.append(
                Movimiento(
                    usuario_id=portafolio.usuario_id,
                    portafolio_id=portafolio.id,
                    instrumento_id=instrumento.id if instrumento else None,
                    fecha=date.fromisoformat(fila["fecha"].strip()),
                    tipo=TipoMovimiento(fila["tipo"].strip().upper()),
                    monto=monto,
                    nota=(fila.get("nota") or "").strip() or None,
                )
            )
        except (ValueError, KeyError, InvalidOperation) as error:
            errores.append(f"Fila {n}: {error or 'valor inválido'}")
    if errores:
        raise ErrorImportacion(errores)
    sesion.add_all(nuevos)
    sesion.flush()
    return len(nuevos)


def importar_valoraciones(sesion: Session, portafolio: Portafolio, archivo: TextIO) -> int:
    nuevas, errores = [], []
    for n, fila, instrumentos in _leer(archivo, COLUMNAS_VALORACIONES, portafolio, sesion):
        try:
            _validar_ancho(fila)
            nombre = fila["instrumento"].strip()
            if nombre not in instrumentos:
                raise ValueError(f"instrumento desconocido '{nombre}'")
            nuevas.append(
                Valoracion(
                    usuario_id=portafolio.usuario_id,
                    portafolio_id=portafolio.id,
                    instrumento_id=instrumentos[nombre].id,
                    fecha=date.fromisoformat(fila["fecha"].strip()),
                    valor=_decimal(fila["valor"]),
                )
            )
        except (ValueError, KeyError, InvalidOperation) as error:
            errores.append(f"Fila {n}: {error or 'valor inválido'}")
    if errores:
        raise ErrorImportacion(errores)
    sesion.add_all(nuevas)
    sesion.flush()
    return len(nuevas)


def exportar_movimientos(sesion: Session, portafolio: Portafolio, archivo: TextIO) -> int:
    consulta = (
        select(Movimiento)
        .where(Movimiento.portafolio_id == portafolio.id)
        .order_by(Movimiento.fecha, Movimiento.id)
    )
    escritor = csv.writer(archivo, lineterminator="\n")
    escritor.writerow(COLUMNAS_MOVIMIENTOS)
    total = 0
    for m in sesion.scalars(consulta):
        nombre = m.instrumento.nombre if m.instrumento else ""
        escritor.writerow([m.fecha.isoformat(), nombre, m.tipo.value, m.monto, m.nota or ""])
        total += 1
    return total


def exportar_valoraciones(sesion: Session, portafolio: Portafolio, archivo: TextIO) -> int:
    consulta = (
        select(Valoracion)
        .where(Valoracion.portafolio_id == portafolio.id)
        .order_by(Valoracion.fecha, Valoracion.id)
    )
    escritor = csv.writer(archivo, lineterminator="\n")
    escritor.writerow(COLUMNAS_VALORACIONES)
    total = 0
    for v in sesion.scalars(consulta):
        escritor.writerow([v.fecha.isoformat(), v.instrumento.nombre, v.valor])
        total += 1
    return total


def importar_parametros(sesion: Session, archivo: TextIO) -> int:
    """Agrega o actualiza parámetros (la llave es nombre + vigente_desde).

    Las líneas que empiezan con ``#`` se ignoran, para poder anotar la fuente.
    """
    lector = csv.DictReader((linea for linea in archivo if not linea.startswith("#")), restkey=_SOBRANTES)
    faltantes = {"nombre", "vigente_desde", "valor"} - set(lector.fieldnames or [])
    if faltantes:
        raise ErrorImportacion([f"Faltan columnas: {', '.join(sorted(faltantes))}"])
    filas, errores = [], []
    for n, fila in enumerate(lector, start=2):
        try:
            _validar_ancho(fila)
            nombre = fila["nombre"].strip()
            if not nombre:
                raise ValueError("falta el nombre")
            filas.append(
                (
                    nombre,
                    date.fromisoformat(fila["vigente_desde"].strip()),
                    _decimal(fila["valor"]),
                    (fila.get("descripcion") or "").strip() or None,
                )
            )
        except (ValueError, KeyError, InvalidOperation) as error:
            errores.append(f"Fila {n}: {error or 'valor inválido'}")
    if errores:
        raise ErrorImportacion(errores)
    for nombre, vigente_desde, valor, descripcion in filas:
        existente = sesion.scalar(
            select(Parametro).where(Parametro.nombre == nombre, Parametro.vigente_desde == vigente_desde)
        )
        if existente:
            existente.valor, existente.descripcion = valor, descripcion
        else:
            sesion.add(Parametro(nombre=nombre, vigente_desde=vigente_desde, valor=valor, descripcion=descripcion))
    sesion.flush()
    return len(filas)
