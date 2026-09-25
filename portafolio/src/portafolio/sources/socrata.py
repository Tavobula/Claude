"""Conector para la API de datos abiertos de Colombia (www.datos.gov.co, Socrata).

Cada conjunto de datos tiene un identificador de 9 caracteres (``xxxx-xxxx``)
que aparece en su URL. Los nombres de los campos se ven en la pestaña de API
del conjunto. Con un token de aplicación (variable ``PORTAFOLIO_SOCRATA_TOKEN``)
el límite de consultas es más alto.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from portafolio.sources.base import (
    DefinicionSerie,
    ErrorFuente,
    Observacion,
    Transporte,
    leer_json,
    transporte_urllib,
)

_IDENTIFICADOR = re.compile(r"^[a-z0-9_]+$")
_DATASET = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")


def _campo(nombre: str) -> str:
    if not _IDENTIFICADOR.match(nombre):
        raise ValueError(f"Nombre de campo inválido: {nombre!r}")
    return nombre


def _literal(valor: str) -> str:
    return "'" + str(valor).replace("'", "''") + "'"


class ConectorSocrata:
    def __init__(
        self,
        definicion: DefinicionSerie,
        dataset: str,
        campo_fecha: str,
        campo_valor: str,
        *,
        campo_fecha_hasta: str | None = None,
        filtros: Mapping[str, str] | None = None,
        dominio: str = "www.datos.gov.co",
        transporte: Transporte | None = None,
        tamano_pagina: int = 50_000,
    ):
        """
        ``campo_fecha_hasta``: para datos publicados como vigencias (desde-hasta),
        repite el valor en cada día de la vigencia.
        ``filtros``: igualdades adicionales, p. ej. ``{"nombre_fondo": "..."}``.
        """
        if not _DATASET.match(dataset):
            raise ValueError(f"Identificador de conjunto inválido: {dataset!r}")
        self.definicion = definicion
        self.url = f"https://{dominio}/resource/{dataset}.json"
        self.campo_fecha = _campo(campo_fecha)
        self.campo_valor = _campo(campo_valor)
        self.campo_fecha_hasta = _campo(campo_fecha_hasta) if campo_fecha_hasta else None
        self.filtros = {_campo(k): v for k, v in (filtros or {}).items()}
        self.transporte = transporte or transporte_urllib
        self.tamano_pagina = tamano_pagina

    def _condicion(self, desde: date, hasta: date) -> str:
        partes = [
            f"{self.campo_fecha} <= {_literal(f'{hasta.isoformat()}T23:59:59')}",
            # Con vigencias, una que empezó antes de ``desde`` puede cubrirlo.
            f"{self.campo_fecha_hasta or self.campo_fecha} >= {_literal(f'{desde.isoformat()}T00:00:00')}",
        ]
        partes += [f"{campo} = {_literal(valor)}" for campo, valor in self.filtros.items()]
        return " AND ".join(partes)

    def _paginas(self, desde: date, hasta: date):
        campos = [self.campo_fecha, self.campo_valor] + ([self.campo_fecha_hasta] if self.campo_fecha_hasta else [])
        encabezados = {}
        if token := os.environ.get("PORTAFOLIO_SOCRATA_TOKEN"):
            encabezados["X-App-Token"] = token
        desplazamiento = 0
        while True:
            parametros = {
                "$select": ",".join(campos),
                "$where": self._condicion(desde, hasta),
                "$order": f"{self.campo_fecha} ASC",
                "$limit": str(self.tamano_pagina),
                "$offset": str(desplazamiento),
            }
            filas = leer_json(self.transporte(self.url, parametros, encabezados), self.url)
            if not isinstance(filas, list):
                raise ErrorFuente(f"{self.url} devolvió un objeto en lugar de filas: {str(filas)[:200]}")
            yield from filas
            if len(filas) < self.tamano_pagina:
                return
            desplazamiento += self.tamano_pagina

    def descargar(self, desde: date, hasta: date) -> list[Observacion]:
        por_fecha: dict[date, Decimal] = {}
        for fila in self._paginas(desde, hasta):
            try:
                inicio = date.fromisoformat(fila[self.campo_fecha][:10])
                fin = date.fromisoformat(fila[self.campo_fecha_hasta][:10]) if self.campo_fecha_hasta else inicio
                valor = Decimal(str(fila[self.campo_valor]))
            except (KeyError, TypeError, ValueError, InvalidOperation) as error:
                raise ErrorFuente(f"Fila inesperada de {self.url}: {fila}") from error
            dia = max(inicio, desde)
            while dia <= min(fin, hasta):
                por_fecha[dia] = valor
                dia += timedelta(days=1)
        return [Observacion(f, por_fecha[f]) for f in sorted(por_fecha)]
