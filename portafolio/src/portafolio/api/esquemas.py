"""Esquemas de entrada y salida.

Los montos y tasas viajan como **texto** JSON (``"1500000.50"``): un número
JSON con decimales pasaría por ``float`` y perdería precisión. Se aceptan
enteros; los números con decimales se rechazan con un mensaje claro.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from portafolio.core.cdt import Modalidad, Periodicidad, TipoTasa
from portafolio.data.modelos import TipoInstrumento, TipoMovimiento


def _decimal_exacto(valor):
    if isinstance(valor, bool) or isinstance(valor, float):
        raise ValueError('Envíe montos y tasas como texto, p. ej. "1500000.50", para no perder precisión.')
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, str):
        try:
            numero = Decimal(valor.strip())
        except InvalidOperation:
            raise ValueError(f"Número inválido: {valor!r}") from None
        if not numero.is_finite():
            raise ValueError(f"Número inválido: {valor!r}")
        return numero
    return valor


DecimalTexto = Annotated[Decimal, BeforeValidator(_decimal_exacto)]


class Esquema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ cuenta


class UsuarioSalida(Esquema):
    id: int
    nombre: str
    email: str
    es_administrador: bool
    autorizacion_vigente: bool
    version_politica_aceptada: str | None
    version_politica_vigente: str
    autorizacion_datos_en: datetime | None


class AutorizacionEntrada(Esquema):
    version: str
    acepto: Literal[True] = Field(description="Debe ser true: el titular acepta la política.")


class PoliticaSalida(Esquema):
    version: str
    texto: str


# ------------------------------------------------------------------ portafolios


class PortafolioEntrada(Esquema):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: str | None = None


class PortafolioSalida(Esquema):
    id: int
    nombre: str
    descripcion: str | None


class InstrumentoEntrada(Esquema):
    nombre: str = Field(min_length=1, max_length=200)
    tipo: TipoInstrumento
    emisor: str | None = None
    exenta_gmf: bool = False


class InstrumentoSalida(Esquema):
    id: int
    nombre: str
    tipo: TipoInstrumento
    emisor: str | None
    exenta_gmf: bool


class MovimientoEntrada(Esquema):
    fecha: date
    tipo: TipoMovimiento
    monto: DecimalTexto
    instrumento_id: int | None = None
    nota: str | None = None


class MovimientoSalida(Esquema):
    id: int
    fecha: date
    tipo: TipoMovimiento
    monto: Decimal
    instrumento_id: int | None
    nota: str | None
    automatico: bool = False


class ValoracionEntrada(Esquema):
    instrumento_id: int
    fecha: date
    valor: DecimalTexto


class ValoracionSalida(Esquema):
    id: int
    instrumento_id: int
    fecha: date
    valor: Decimal


class CondicionCDTEntrada(Esquema):
    capital: DecimalTexto
    fecha_emision: date
    fecha_vencimiento: date
    tasa: DecimalTexto = Field(description='Fracción: "0.105" = 10,5 %')
    tipo_tasa: TipoTasa = TipoTasa.EFECTIVA_ANUAL
    periodicidad: Periodicidad = Periodicidad.AL_VENCIMIENTO
    modalidad: Modalidad = Modalidad.VENCIDA
    base_dias: Literal[360, 365] | None = None


class PagoCDTSalida(Esquema):
    corte: date
    fecha_pago: date
    dias: int
    interes: Decimal
    retencion: Decimal
    capital: Decimal
    total_recibido: Decimal


class EstadoCDTSalida(Esquema):
    fecha: date
    capital: Decimal
    interes_causado: Decimal
    retencion_estimada: Decimal
    valor_bruto: Decimal
    valor_neto_estimado: Decimal


class SincronizacionSalida(Esquema):
    movimientos_creados: int
    valoraciones_creadas: int


class CargoGMFSalida(Esquema):
    fecha: date
    monto: Decimal
    exento: Decimal
    gmf: Decimal


class ImportacionSalida(Esquema):
    registros: int


# ------------------------------------------------------------------ consultas


class ResumenSalida(Esquema):
    fecha: date
    valor: Decimal | None
    aportes_netos: Decimal
    ganancia: Decimal | None
    tir: float | None
    tir_real: float | None
    twr_anio: float | None
    avisos: list[str]


class PosicionSalida(Esquema):
    instrumento_id: int
    nombre: str
    tipo: str
    valor: Decimal | None
    fecha_valoracion: date | None
    peso: float | None
    aviso: str | None


class PuntoEvolucionSalida(Esquema):
    fecha: date
    valor: Decimal
    aportes_netos: Decimal


class PeriodoSalida(Esquema):
    metodo: str
    rendimiento: float
    anualizado: float | None
    valor_inicial: Decimal
    valor_final: Decimal
    flujo_neto: Decimal
    exacto: bool
    fechas_omitidas: list[date]
    inflacion: float | None = None
    real: float | None = None
    real_anualizado: float | None = None


class TIRSalida(Esquema):
    fecha_corte: date
    tasa: float
    tasa_real: float | None
    valor_final: Decimal


class RendimientosSalida(Esquema):
    desde: date
    hasta: date
    serie: str
    twr: PeriodoSalida | None
    dietz: PeriodoSalida | None
    tir: TIRSalida | None
    avisos: list[str]


class ContribucionSalida(Esquema):
    nombre: str
    tipo: str
    instrumento_id: int | None
    valor_inicial: Decimal
    valor_final: Decimal
    flujo_neto: Decimal
    ganancia: Decimal
    peso: float
    rendimiento: float | None
    contribucion: float


class AtribucionSalida(Esquema):
    desde: date
    hasta: date
    rendimiento: float
    ganancia: Decimal
    partes: list[ContribucionSalida]


# ------------------------------------------------------------------ datos globales


class SerieSalida(Esquema):
    codigo: str
    nombre: str
    frecuencia: str
    fuente: str | None
    datos: int
    primera: date | None
    ultima: date | None


class ParametroSalida(Esquema):
    nombre: str
    vigente_desde: date
    valor: Decimal
    descripcion: str | None


class CargaSerieSalida(Esquema):
    codigo: str
    nuevas: int
    actualizadas: int
    sin_cambio: int
    desde: date | None
    hasta: date | None
