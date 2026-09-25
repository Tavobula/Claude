"""Lectura de series desde archivos descargados a mano (CSV o Excel).

Pensado para los archivos de Banrep, DANE y Superfinanciera, que suelen:

* traer filas de título antes del encabezado (se busca la fila que contiene
  las columnas pedidas),
* usar fechas ``dd/mm/aaaa`` y coma decimal (``376,1234``).

Las fechas se interpretan día/mes (formato colombiano). Una columna de meses
escrita como ``2024-03`` o ``03/2024`` se guarda con el día 1; nombres de mes
(``mar-2024``) no se reconocen.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from portafolio.sources.base import Observacion

_FORMATOS = [
    (re.compile(r"^\d{4}-\d{1,2}-\d{1,2}"), "%Y-%m-%d"),
    (re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"), "%d/%m/%Y"),
    (re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"), "%Y/%m/%d"),
    (re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"), "%d-%m-%Y"),
    (re.compile(r"^\d{4}-\d{1,2}$"), "%Y-%m"),
    (re.compile(r"^\d{1,2}/\d{4}$"), "%m/%Y"),
]


class ErrorLectura(ValueError):
    def __init__(self, errores: list[str]):
        self.errores = errores
        super().__init__("\n".join(errores[:20]) + (f"\n... y {len(errores) - 20} más" if len(errores) > 20 else ""))


def interpretar_fecha(valor, formato: str | None = None) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if formato:
        return datetime.strptime(texto, formato).date()
    for patron, fmt in _FORMATOS:
        if patron.match(texto):
            return datetime.strptime(texto[:10] if fmt == "%Y-%m-%d" else texto, fmt).date()
    raise ValueError(f"fecha no reconocida {texto!r}")


def interpretar_numero(valor, decimal: str = ".") -> Decimal:
    if isinstance(valor, (int, Decimal)):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(repr(valor))  # celda de Excel: conserva los dígitos visibles
    texto = str(valor).strip().replace(" ", "").replace(" ", "").replace("$", "").replace("%", "")
    if decimal == ",":
        texto = texto.replace(".", "").replace(",", ".")
    elif decimal == ".":
        texto = texto.replace(",", "")
    else:
        raise ValueError("El separador decimal debe ser '.' o ','.")
    numero = Decimal(texto)
    if not numero.is_finite():
        raise InvalidOperation
    return numero


def _normalizar(nombre) -> str:
    return re.sub(r"\s+", " ", str(nombre or "")).strip().lower()


def leer_filas(
    filas: Iterable[list],
    *,
    columna_fecha: str,
    columna_valor: str,
    decimal: str = ".",
    formato_fecha: str | None = None,
    escala: Decimal = Decimal(1),
) -> list[Observacion]:
    """Convierte filas (listas de celdas) en observaciones.

    ``escala`` multiplica cada valor, p. ej. ``Decimal("0.01")`` para pasar una
    tasa publicada en porcentaje a fracción.
    """
    iterador: Iterator[list] = iter(filas)
    buscadas = (_normalizar(columna_fecha), _normalizar(columna_valor))
    for n, fila in enumerate(iterador, start=1):
        nombres = [_normalizar(c) for c in fila]
        if all(b in nombres for b in buscadas):
            i_fecha, i_valor = nombres.index(buscadas[0]), nombres.index(buscadas[1])
            break
    else:
        raise ErrorLectura([f"No se encontró una fila de encabezado con {columna_fecha!r} y {columna_valor!r}."])

    observaciones, errores = [], []
    for n, fila in enumerate(iterador, start=n + 1):
        celdas = list(fila) + [None] * (max(i_fecha, i_valor) + 1 - len(fila))
        fecha, valor = celdas[i_fecha], celdas[i_valor]
        if all(c in (None, "") or str(c).strip() == "" for c in (fecha, valor)):
            continue  # filas vacías o notas al pie
        if valor is None or str(valor).strip() in ("", "-", "n.d.", "N.D."):
            continue  # la fuente no tiene dato ese día
        try:
            observaciones.append(
                Observacion(interpretar_fecha(fecha, formato_fecha), interpretar_numero(valor, decimal) * escala)
            )
        except (ValueError, InvalidOperation) as error:
            if str(fecha).strip().lower().startswith(("fuente", "nota")):
                continue
            errores.append(f"Fila {n}: {error or 'número inválido'} ({fecha!r}, {valor!r})")
    if errores:
        raise ErrorLectura(errores)
    return observaciones


def leer_csv(archivo: TextIO, **opciones) -> list[Observacion]:
    muestra = archivo.read(4096)
    archivo.seek(0)
    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    return leer_filas(csv.reader(archivo, dialecto), **opciones)


def leer_excel(ruta: str | Path, hoja: str | None = None, **opciones) -> list[Observacion]:
    """Requiere ``openpyxl`` (``pip install openpyxl``)."""
    try:
        import openpyxl
    except ImportError as error:  # pragma: no cover - depende del entorno
        raise ImportError("Para leer Excel instale openpyxl: pip install openpyxl") from error
    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    try:
        hoja_excel = libro[hoja] if hoja else libro.active
        return leer_filas((list(f) for f in hoja_excel.iter_rows(values_only=True)), **opciones)
    finally:
        libro.close()
