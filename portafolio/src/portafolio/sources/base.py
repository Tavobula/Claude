"""Tipos comunes y transporte HTTP de los conectores."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from portafolio.core.inflacion import Frecuencia
from portafolio.data.modelos import TipoSerie


class ErrorFuente(RuntimeError):
    """La fuente no respondió o respondió algo que no se pudo interpretar."""


@dataclass(frozen=True)
class Observacion:
    fecha: date
    valor: Decimal


@dataclass(frozen=True)
class DefinicionSerie:
    codigo: str
    nombre: str
    tipo: TipoSerie
    frecuencia: Frecuencia
    fuente: str
    unidad: str


class Conector(Protocol):
    definicion: DefinicionSerie

    def descargar(self, desde: date, hasta: date) -> list[Observacion]: ...


# (url, parámetros de consulta, encabezados) -> cuerpo de la respuesta.
Transporte = Callable[[str, Mapping[str, str], Mapping[str, str]], bytes]

AGENTE = "portafolio/0.1 (seguimiento personal de inversiones)"


def transporte_urllib(
    url: str, parametros: Mapping[str, str], encabezados: Mapping[str, str], timeout: float = 30
) -> bytes:
    if parametros:
        url = f"{url}?{urllib.parse.urlencode(parametros)}"
    solicitud = urllib.request.Request(url, headers={"User-Agent": AGENTE, **encabezados})
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        raise ErrorFuente(f"{url} respondió {error.code} {error.reason}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ErrorFuente(f"No se pudo conectar con {url}: {error}") from error


def leer_json(cuerpo: bytes, url: str):
    try:
        return json.loads(cuerpo)
    except ValueError as error:
        raise ErrorFuente(f"{url} no devolvió JSON válido.") from error
