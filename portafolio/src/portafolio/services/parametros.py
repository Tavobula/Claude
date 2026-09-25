"""Nombres de los parámetros normativos que usan los servicios.

Los valores se cargan en la tabla ``parametro`` con su fecha de vigencia
(por ejemplo con ``csv_io.importar_parametros``). Ninguno está fijo en el
código: el sistema falla con ``ParametroNoDefinidoError`` si falta uno
obligatorio, en vez de suponer una tarifa.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from portafolio.data.repositorios import ParametroNoDefinidoError, parametro_vigente

# Obligatorios cuando se usan.
RETENCION_CDT = "retencion_rendimientos_cdt"  # tarifa sobre intereses de CDT (fracción)
GMF_TARIFA = "gmf_tarifa"  # 0.004 = 4 x 1.000
UVT = "uvt"  # valor en pesos, vigente desde el 1 de enero de cada año
GMF_TOPE_EXENTO_UVT = "gmf_tope_exento_uvt"  # tope mensual exento, en UVT

# Opcionales, con valor por defecto.
COMPONENTE_INFLACIONARIO = "componente_inflacionario"  # fracción no gravada; defecto 0
BASE_DIAS = "base_dias"  # 365 o 360; defecto 365


def obligatorio(sesion: Session, nombre: str, fecha: date) -> Decimal:
    return parametro_vigente(sesion, nombre, fecha)


def opcional(sesion: Session, nombre: str, fecha: date, defecto: Decimal) -> Decimal:
    try:
        return parametro_vigente(sesion, nombre, fecha)
    except ParametroNoDefinidoError:
        return defecto
