"""Datos de demostración para explorar la interfaz.

Solo se crean en una base vacía, porque incluyen datos globales ficticios
(una UVR sintética y una tarifa de retención) que no deben mezclarse con
datos reales. Use un archivo aparte:

    python -m portafolio --db sqlite:///demo.db demo
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.inflacion import Frecuencia
from portafolio.data.modelos import Parametro, Portafolio, TipoInstrumento, TipoMovimiento, TipoSerie, Usuario
from portafolio.services import cdt, registro, series
from portafolio.sources.base import DefinicionSerie, Observacion

INICIO = date(2025, 1, 2)
FIN = date(2025, 9, 24)


class BaseNoVaciaError(RuntimeError):
    pass


def _fin_de_mes(anio: int, mes: int) -> date:
    return (date(anio, mes, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def crear_demo(sesion: Session) -> Portafolio:
    if sesion.scalar(select(Usuario.id).limit(1)) is not None:
        raise BaseNoVaciaError("La demo solo se crea en una base vacía. Use otro archivo con --db.")

    sesion.add(Parametro(nombre="retencion_rendimientos_cdt", vigente_desde=date(2000, 1, 1), valor=D("0.04"), descripcion="Demo"))
    uvr = DefinicionSerie("UVR", "UVR sintética (solo demo, 5 % anual)", TipoSerie.INDICADOR, Frecuencia.DIARIA, "Demo", "COP")
    dias = (FIN - date(2024, 12, 31)).days
    series.guardar_observaciones(
        sesion,
        uvr,
        [Observacion(date(2024, 12, 31) + timedelta(days=t), D(f"{380 * 1.05 ** (t / 365):.4f}")) for t in range(dias + 1)],
    )

    usuario = registro.crear_usuario(sesion, "Usuario demo", "demo@example.com")
    p = registro.crear_portafolio(sesion, usuario.id, "Demo", "Datos ficticios para explorar la herramienta")
    cuenta = registro.crear_instrumento(sesion, p, "Cuenta de ahorros", TipoInstrumento.CUENTA, "Banco A", exenta_gmf=True)
    cdt_a = registro.crear_instrumento(sesion, p, "CDT Banco A 1 año", TipoInstrumento.CDT, "Banco A")
    fic = registro.crear_instrumento(sesion, p, "FIC Renta Fija", TipoInstrumento.FIC, "Fiduciaria B")
    etf = registro.crear_instrumento(sesion, p, "ETF acciones Colombia", TipoInstrumento.ETF, "Comisionista C")

    def mov(fecha, tipo, monto, instrumento=None):
        registro.registrar_movimiento(sesion, p, fecha, tipo, D(monto), instrumento.id if instrumento else None)

    def val(instrumento, fecha, valor):
        registro.registrar_valoracion(sesion, p, instrumento.id, fecha, D(f"{valor:.2f}"))

    mov(INICIO, TipoMovimiento.APORTE, "32000000", cuenta)
    val(cuenta, INICIO, 32_000_000)
    registro.registrar_condicion_cdt(
        sesion, p, cdt_a.id, capital=D("10000000"), fecha_emision=date(2025, 1, 15),
        fecha_vencimiento=date(2026, 1, 15), tasa=D("0.0975"),
    )
    mov(date(2025, 1, 15), TipoMovimiento.COMPRA, "10000000", fic)
    mov(date(2025, 1, 15), TipoMovimiento.COMPRA, "8000000", etf)
    mov(date(2025, 4, 1), TipoMovimiento.APORTE, "5000000", cuenta)
    mov(date(2025, 4, 1), TipoMovimiento.COMPRA, "5000000", fic)
    mov(date(2025, 7, 10), TipoMovimiento.RETIRO, "3000000", cuenta)

    # Valores al cierre: el FIC crece ~0,7 % al mes; el ETF sube y baja.
    fic_valor, etf_valor, saldo = 10_000_000.0, 8_000_000.0, 4_000_000.0
    val(fic, date(2025, 1, 15), fic_valor)
    val(etf, date(2025, 1, 15), etf_valor)
    val(cuenta, date(2025, 1, 15), saldo)
    movimientos_etf = [0.031, -0.024, 0.045, -0.052, 0.018, 0.037, 0.012, -0.015, 0.028]
    for i, mes in enumerate(range(1, 10)):
        cierre = min(_fin_de_mes(2025, mes), FIN)
        if mes == 4:  # valoración el día del aporte para que el TWR sea exacto
            fic_valor *= 1.007 ** (1 / 31)
            val(fic, date(2025, 4, 1), fic_valor + 5_000_000)
            val(etf, date(2025, 4, 1), etf_valor)
            val(cuenta, date(2025, 4, 1), saldo)
            fic_valor += 5_000_000
        if mes == 7:
            saldo -= 3_000_000
            val(cuenta, date(2025, 7, 10), saldo)
            val(fic, date(2025, 7, 10), fic_valor)
            val(etf, date(2025, 7, 10), etf_valor)
        fic_valor *= 1.007
        etf_valor *= 1 + movimientos_etf[i]
        saldo *= 1.0015
        for instrumento, valor in ((fic, fic_valor), (etf, etf_valor), (cuenta, saldo)):
            if cierre > date(2025, 1, 15):
                val(instrumento, cierre, valor)
    cdt.sincronizar_cdt(sesion, cdt_a.id, FIN)
    return p
