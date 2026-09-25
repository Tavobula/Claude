"""Datos globales: series (UVR, IPC, IBR, TRM, FIC) y parámetros normativos.

Cualquier usuario autorizado los consulta; solo un administrador los carga,
porque son compartidos por todos los portafolios.
"""

from __future__ import annotations

import io
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from portafolio.api import esquemas as e
from portafolio.api.dependencias import administrador, obtener_sesion, usuario_autorizado
from portafolio.api.rutas_portafolios import LIMITE_ARCHIVO, leer_archivo
from portafolio.core.calendario import hoy_bogota
from portafolio.services import csv_io, series
from portafolio.sources import catalogo

router = APIRouter(prefix="/v1", tags=["datos globales"])


def _carga(r: series.ResumenCarga) -> e.CargaSerieSalida:
    return e.CargaSerieSalida(codigo=r.codigo, nuevas=r.nuevas, actualizadas=r.actualizadas, sin_cambio=r.sin_cambio, desde=r.desde, hasta=r.hasta)


@router.get("/series", response_model=list[e.SerieSalida], dependencies=[Depends(usuario_autorizado)])
def listar_series(sesion: Session = Depends(obtener_sesion)):
    return series.listar_series(sesion)


@router.get("/parametros", response_model=list[e.ParametroSalida], dependencies=[Depends(usuario_autorizado)])
def listar_parametros(sesion: Session = Depends(obtener_sesion)):
    return series.listar_parametros(sesion)


@router.post("/series/{codigo}/importar", response_model=e.CargaSerieSalida, dependencies=[Depends(administrador)])
async def importar_serie(
    codigo: str,
    archivo: UploadFile = File(...),
    columna_fecha: str = Form("fecha"),
    columna_valor: str = Form("valor"),
    decimal: Literal[".", ","] = Form("."),
    escala: str = Form("1"),
    nombre: str | None = Form(None, description="Nombre de la serie, para FIC:<código>"),
    sesion: Session = Depends(obtener_sesion),
):
    if codigo in catalogo.DEFINICIONES:
        definicion = catalogo.DEFINICIONES[codigo]
    elif codigo.startswith("FIC:") and len(codigo) > 4:
        definicion = catalogo.definicion_fic(codigo, nombre or codigo)
    else:
        raise HTTPException(404, detail={"codigo": "serie_desconocida", "detalle": f"Serie desconocida: {codigo}"})
    contenido = await archivo.read(LIMITE_ARCHIVO + 1)
    if len(contenido) > LIMITE_ARCHIVO:
        raise HTTPException(413, detail={"codigo": "archivo_grande", "detalle": "Máximo 5 MB."})
    resumen = series.importar_archivo(
        sesion, definicion, contenido, archivo.filename or "serie.csv",
        columna_fecha=columna_fecha, columna_valor=columna_valor, decimal=decimal, escala=Decimal(escala),
    )
    sesion.commit()
    return _carga(resumen)


@router.post("/series/TRM/actualizar", response_model=e.CargaSerieSalida, dependencies=[Depends(administrador)])
def actualizar_trm(sesion: Session = Depends(obtener_sesion)):
    desde = series.ultima_fecha(sesion, "TRM") or hoy_bogota() - timedelta(days=365)
    resumen = series.actualizar_desde_fuente(sesion, catalogo.CONECTORES["TRM"](), desde, hoy_bogota())
    sesion.commit()
    return _carga(resumen)


@router.post("/parametros/importar", response_model=e.ImportacionSalida, dependencies=[Depends(administrador)])
async def importar_parametros(archivo: UploadFile = File(...), sesion: Session = Depends(obtener_sesion)):
    total = csv_io.importar_parametros(sesion, io.StringIO(await leer_archivo(archivo)))
    sesion.commit()
    return e.ImportacionSalida(registros=total)
