"""Atribución del rendimiento del portafolio por instrumento o por tipo de activo.

Todas las cuentas (``TipoInstrumento.CUENTA``) forman un solo segmento
"Efectivo". Sus flujos no se leen de sus movimientos sino que se deducen:
son los flujos externos del portafolio menos los que entraron o salieron de
los demás instrumentos. Así una COMPRA de un CDT, que en el modelo solo se
registra en el CDT, también sale del efectivo, y las contribuciones suman
exactamente el Dietz modificado del portafolio.

Si el portafolio no tiene cuentas, el segmento se llama "Efectivo no
registrado": su ganancia muestra el dinero que entró o salió sin pasar por
ningún instrumento valorado.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from portafolio.core.atribucion import Contribucion, Segmento, agrupar, atribuir
from portafolio.data.modelos import TipoInstrumento
from portafolio.services.rendimientos import SIGNO_INSTRUMENTO, Libro

EFECTIVO = "Efectivo"
EFECTIVO_NO_REGISTRADO = "Efectivo no registrado"


@dataclass(frozen=True)
class FilaAtribucion:
    nombre: str
    tipo: str
    instrumento_id: int | None  # None en filas agrupadas o de efectivo
    detalle: Contribucion


@dataclass(frozen=True)
class ResultadoAtribucion:
    fecha_inicio: date
    fecha_fin: date
    rendimiento: float  # Dietz modificado del portafolio
    ganancia: Decimal
    filas: list[FilaAtribucion]


def atribucion_portafolio(
    sesion: Session,
    portafolio_id: int,
    fecha_inicio: date,
    fecha_fin: date,
    por: Literal["instrumento", "tipo"] = "instrumento",
) -> ResultadoAtribucion:
    libro = Libro.de_portafolio(sesion, portafolio_id, fecha_fin)

    externos: dict[date, Decimal] = defaultdict(Decimal)
    for f, m in libro.flujos_activo(fecha_inicio, fecha_fin):
        externos[f] += m

    segmentos: list[Segmento] = []
    tipos: dict[str, str] = {}
    ids: dict[str, int] = {}
    efectivo_v0 = efectivo_v1 = Decimal(0)
    hay_cuentas = False
    for instrumento in libro.instrumentos:
        v0, _ = libro.valor_instrumento(instrumento, fecha_inicio)
        v1, _ = libro.valor_instrumento(instrumento, fecha_fin)
        if instrumento.tipo is TipoInstrumento.CUENTA:
            hay_cuentas = True
            efectivo_v0 += v0
            efectivo_v1 += v1
            continue
        flujos = [
            (m.fecha, -SIGNO_INSTRUMENTO[m.tipo] * m.monto)
            for m in libro.movimientos
            if m.instrumento_id == instrumento.id and fecha_inicio < m.fecha <= fecha_fin
        ]
        for f, monto in flujos:
            externos[f] -= monto  # lo que no explica un instrumento pasa por el efectivo
        if not (v0 or v1 or flujos):
            continue  # no existió en el periodo
        segmentos.append(Segmento(instrumento.nombre, v0, v1, flujos))
        tipos[instrumento.nombre] = instrumento.tipo.value
        ids[instrumento.nombre] = instrumento.id

    flujos_efectivo = [(f, m) for f, m in sorted(externos.items()) if m]
    if efectivo_v0 or efectivo_v1 or flujos_efectivo:
        nombre = EFECTIVO if hay_cuentas else EFECTIVO_NO_REGISTRADO
        segmentos.append(Segmento(nombre, efectivo_v0, efectivo_v1, flujos_efectivo))
        tipos[nombre] = TipoInstrumento.CUENTA.value

    if por == "tipo":
        segmentos = agrupar(segmentos, tipos)
        tipos = {s.clave: s.clave for s in segmentos}
        ids = {}

    resultado = atribuir(segmentos, fecha_inicio, fecha_fin)
    filas = [FilaAtribucion(c.clave, tipos[c.clave], ids.get(c.clave), c) for c in resultado.contribuciones]
    filas.sort(key=lambda f: f.detalle.contribucion, reverse=True)
    return ResultadoAtribucion(fecha_inicio, fecha_fin, resultado.rendimiento, resultado.ganancia, filas)
