"""Traducción de errores de dominio a respuestas HTTP con un código estable.

Formato: ``{"detail": {"codigo": "...", "detalle": "...", "errores": [...]}}``,
igual que las ``HTTPException`` de las dependencias.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from portafolio.core.dietz import DenominadorInvalidoError
from portafolio.core.inflacion import ValorNoDisponibleError
from portafolio.core.xirr import SinSolucionError
from portafolio.data.repositorios import ParametroNoDefinidoError, SerieNoEncontradaError
from portafolio.services.cdt import CDTSinCondicionesError
from portafolio.services.csv_io import ErrorImportacion
from portafolio.services.cuenta import ConflictoIdentidadError
from portafolio.services.registro import DatoInvalidoError
from portafolio.services.rendimientos import ValoracionFaltanteError
from portafolio.sources.archivo import ErrorLectura
from portafolio.sources.base import ErrorFuente

# (excepciones, estado HTTP, código). El orden importa: la primera que aplique.
TABLA = [
    ((ErrorImportacion, ErrorLectura), 422, "archivo_invalido"),
    ((DatoInvalidoError,), 422, "dato_invalido"),
    ((ConflictoIdentidadError,), 409, "conflicto_identidad"),
    (
        (
            ValoracionFaltanteError,
            SinSolucionError,
            DenominadorInvalidoError,
            ValorNoDisponibleError,
            SerieNoEncontradaError,
            ParametroNoDefinidoError,
            CDTSinCondicionesError,
            NotImplementedError,
        ),
        409,
        "no_calculable",
    ),
    ((ErrorFuente,), 502, "fuente_externa"),
    ((ValueError,), 422, "dato_invalido"),
]


def registrar_manejadores(app: FastAPI) -> None:
    for excepciones, estado, codigo in TABLA:
        for excepcion in excepciones:

            async def manejar(_request: Request, error: Exception, estado=estado, codigo=codigo):
                cuerpo = {"codigo": codigo, "detalle": str(error).split("\n")[0]}
                if errores := getattr(error, "errores", None):
                    cuerpo["errores"] = errores
                return JSONResponse(status_code=estado, content={"detail": cuerpo})

            app.add_exception_handler(excepcion, manejar)
