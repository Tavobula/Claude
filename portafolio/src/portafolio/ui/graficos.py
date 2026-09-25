"""Gráficos Altair de la interfaz.

Colores de la paleta de referencia, validados en claro y oscuro (CVD y
contraste). La identidad nunca depende solo del color: hay leyenda, tooltip
y una tabla con los mismos datos junto a cada gráfico.
"""

from __future__ import annotations

from collections.abc import Sequence

import altair as alt
import pandas as pd

from portafolio.services.atribucion import FilaAtribucion
from portafolio.services.consultas import PuntoEvolucion
from portafolio.ui import formato

PALETA = {
    # serie 1 (azul), serie 2 (naranja), negativo (rojo, polo del divergente), guía
    "light": {"serie1": "#2a78d6", "serie2": "#eb6834", "negativo": "#e34948", "guia": "#52514e"},
    "dark": {"serie1": "#3987e5", "serie2": "#d95926", "negativo": "#e66767", "guia": "#c3c2b7"},
}

VALOR = "Valor del portafolio"
APORTES = "Aportes netos"
SUMA = "Suma al rendimiento"
RESTA = "Resta al rendimiento"

# Etiquetas de eje en formato colombiano (coma decimal).
_EJE_MILLONES = "'$ ' + replace(format(datum.value / 1e6, '.1f'), '.', ',') + ' M'"
_EJE_PORCENTAJE = "replace(format(datum.value * 100, '.1f'), '.', ',') + ' %'"


def colores(tema: str | None) -> dict[str, str]:
    return PALETA["dark" if tema == "dark" else "light"]


def grafico_evolucion(puntos: Sequence[PuntoEvolucion], tema: str | None = None) -> alt.LayerChart:
    """Valor del portafolio frente a lo aportado: la distancia entre ambas es la ganancia."""
    c = colores(tema)
    filas = []
    for p in puntos:
        for serie, valor in ((VALOR, p.valor), (APORTES, p.aportes_netos)):
            filas.append(
                {
                    "fecha": pd.Timestamp(p.fecha),
                    "fecha_texto": formato.fecha(p.fecha),
                    "serie": serie,
                    "valor": float(valor),
                    "texto": formato.pesos(valor),
                }
            )
    datos = pd.DataFrame(filas)
    color = alt.Color(
        "serie:N",
        scale=alt.Scale(domain=[VALOR, APORTES], range=[c["serie1"], c["serie2"]]),
        legend=alt.Legend(orient="top", title=None),
    )
    base = alt.Chart(datos).encode(
        x=alt.X("fecha:T", title=None, axis=alt.Axis(format="%m/%Y", grid=False, tickCount={"interval": "month", "step": 1})),
        # Sin cero en el eje: lo que importa es la distancia entre valor y aportes (la ganancia).
        y=alt.Y(
            "valor:Q",
            title=None,
            scale=alt.Scale(zero=False, nice=True),
            axis=alt.Axis(labelExpr=_EJE_MILLONES, gridOpacity=0.4, tickCount=5),
        ),
        color=color,
    )
    valor = base.transform_filter(alt.datum.serie == VALOR).mark_line(strokeWidth=2)
    # Los aportes cambian solo cuando hay un movimiento: escalón, no pendiente.
    aportes = base.transform_filter(alt.datum.serie == APORTES).mark_line(strokeWidth=2, interpolate="step-after")

    cercano = alt.selection_point(fields=["fecha"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    guia = (
        alt.Chart(datos)
        .transform_pivot("serie", value="texto", groupby=["fecha", "fecha_texto"])
        .mark_rule(color=c["guia"], strokeWidth=1)
        .encode(
            x="fecha:T",
            opacity=alt.condition(cercano, alt.value(0.6), alt.value(0)),
            tooltip=[
                alt.Tooltip("fecha_texto:N", title="Fecha"),
                alt.Tooltip(f"{VALOR}:N", title=VALOR),
                alt.Tooltip(f"{APORTES}:N", title=APORTES),
            ],
        )
        .add_params(cercano)
    )
    marcas = base.mark_point(size=64, filled=True).encode(
        opacity=alt.condition(cercano, alt.value(1), alt.value(0))
    ).transform_filter(cercano)
    return alt.layer(aportes, valor, guia, marcas).properties(height=320)


def grafico_atribucion(filas: Sequence[FilaAtribucion], tema: str | None = None) -> alt.LayerChart:
    """Barras divergentes desde cero: cuánto sumó o restó cada parte al rendimiento total."""
    c = colores(tema)
    datos = pd.DataFrame(
        [
            {
                "nombre": f.nombre,
                "contribucion": f.detalle.contribucion,
                "signo": SUMA if f.detalle.contribucion >= 0 else RESTA,
                "contribucion_texto": formato.porcentaje(f.detalle.contribucion),
                "rendimiento_texto": formato.porcentaje(f.detalle.rendimiento),
                "peso_texto": formato.porcentaje(f.detalle.peso, 1),
                "ganancia_texto": formato.pesos(f.detalle.ganancia),
            }
            for f in filas
        ]
    )
    barras = (
        alt.Chart(datos)
        .mark_bar(size=18, cornerRadiusEnd=4)
        .encode(
            y=alt.Y("nombre:N", sort=None, title=None, axis=alt.Axis(labelLimit=220)),
            x=alt.X("contribucion:Q", title="Contribución al rendimiento", axis=alt.Axis(labelExpr=_EJE_PORCENTAJE, gridOpacity=0.4)),
            color=alt.Color(
                "signo:N",
                scale=alt.Scale(domain=[SUMA, RESTA], range=[c["serie1"], c["negativo"]]),
                legend=alt.Legend(orient="top", title=None),
            ),
            tooltip=[
                alt.Tooltip("nombre:N", title="Parte"),
                alt.Tooltip("contribucion_texto:N", title="Contribución"),
                alt.Tooltip("ganancia_texto:N", title="Ganancia"),
                alt.Tooltip("rendimiento_texto:N", title="Rendimiento propio"),
                alt.Tooltip("peso_texto:N", title="Peso promedio"),
            ],
        )
    )
    cero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=c["guia"], strokeWidth=1).encode(x="x:Q")
    # Un paso fijo por barra: el alto crece con el número de partes y las barras no se enciman.
    return alt.layer(barras, cero).properties(height=alt.Step(34))
