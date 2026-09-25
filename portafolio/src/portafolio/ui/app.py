"""Interfaz Streamlit para uso personal.

Ejecutar desde la carpeta del proyecto:

    streamlit run src/portafolio/ui/app.py

Regla de capas: esta interfaz solo llama a ``portafolio.services``. No ejecuta
SQL ni hace cálculos financieros propios.
"""

from __future__ import annotations

import io
import os
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from portafolio.core.calendario import hoy_bogota
from portafolio.core.cdt import Modalidad, Periodicidad, TipoTasa
from portafolio.data.db import crear_motor, fabrica_sesiones, url_base_datos
from portafolio.data.modelos import Portafolio, TipoInstrumento, TipoMovimiento
from portafolio.data.repositorios import ParametroNoDefinidoError
from portafolio.services import (
    atribucion,
    cdt,
    consultas,
    csv_io,
    impuestos,
    inflacion,
    registro,
    rendimientos,
    series,
)
from portafolio.sources import catalogo
from portafolio.sources.archivo import ErrorLectura
from portafolio.sources.base import ErrorFuente
from portafolio.ui import formato, graficos

AVISO_LEGAL = (
    "Herramienta de seguimiento y cálculo. No es asesoría de inversión. "
    "Verifique los resultados contra sus extractos."
)
SIN_INSTRUMENTO = "— Sin instrumento —"
ERRORES_USUARIO = (
    registro.DatoInvalidoError,
    csv_io.ErrorImportacion,
    ErrorLectura,
    ErrorFuente,
    ParametroNoDefinidoError,
    cdt.CDTSinCondicionesError,
    NotImplementedError,
    *consultas.ERRORES_CALCULO,
)


# --------------------------------------------------------------------------
# Infraestructura
# --------------------------------------------------------------------------


@st.cache_resource
def _fabrica(url: str):
    return fabrica_sesiones(crear_motor(url))


def _tema() -> str | None:
    try:
        return st.context.theme.type
    except AttributeError:
        return None


def _avisar(mensaje: str, tipo: str = "success") -> None:
    """Muestra el mensaje después del siguiente ``st.rerun()``."""
    st.session_state["_aviso"] = (tipo, mensaje)


def _mostrar_aviso() -> None:
    if aviso := st.session_state.pop("_aviso", None):
        tipo, mensaje = aviso
        getattr(st, tipo)(mensaje)


def _ejecutar(sesion: Session, accion, exito: str) -> None:
    """Corre una acción de escritura: confirma y recarga, o muestra el error sin guardar nada."""
    try:
        resultado = accion()
        sesion.commit()
    except ERRORES_USUARIO as error:
        sesion.rollback()
        st.error(str(error))
        return
    _avisar(exito.format(resultado=resultado))
    st.rerun()


def _elegir(etiqueta: str, objetos: list, nombre, **opciones):
    """Selector de objetos de la base.

    Las opciones son ids: Streamlit conserva el valor elegido entre recargas y
    un objeto ORM de la sesión anterior ya no sirve en la nueva.
    """
    por_id = {o.id: o for o in objetos}
    elegido = st.selectbox(etiqueta, list(por_id), format_func=lambda i: nombre(por_id[i]), **opciones)
    return por_id[elegido] if elegido is not None else None


def _tabla(filas: list[dict], **opciones) -> None:
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch", **opciones)
    else:
        st.caption("Sin datos.")


# --------------------------------------------------------------------------
# Barra lateral: usuario, portafolio, fecha de corte
# --------------------------------------------------------------------------


def _bienvenida(sesion: Session) -> None:
    st.title("Portafolio")
    st.write("Para empezar, cree su usuario y su primer portafolio.")
    with st.form("bienvenida"):
        nombre = st.text_input("Su nombre")
        email = st.text_input("Correo")
        portafolio = st.text_input("Nombre del portafolio", value="Principal")
        if st.form_submit_button("Crear", type="primary"):

            def crear():
                usuario = registro.crear_usuario(sesion, nombre, email)
                return registro.crear_portafolio(sesion, usuario.id, portafolio)

            _ejecutar(sesion, crear, "Portafolio {resultado.nombre} creado.")


def _fecha_inicial() -> date:
    """Hoy en Bogotá, o la fecha de la URL (``?fecha=2025-09-24``) para guardar o compartir una vista."""
    try:
        return date.fromisoformat(st.query_params.get("fecha", ""))
    except ValueError:
        return hoy_bogota()


def _barra_lateral(sesion: Session) -> tuple[Portafolio, date, str] | None:
    usuarios = consultas.usuarios(sesion)
    if not usuarios:
        return None
    with st.sidebar:
        st.header("Portafolio")
        usuario = usuarios[0]
        if len(usuarios) > 1:
            usuario = _elegir("Usuario", usuarios, lambda u: u.nombre)
        portafolios = consultas.portafolios_de(sesion, usuario.id)
        portafolio = _elegir("Portafolio", portafolios, lambda p: p.nombre) if portafolios else None
        with st.expander("Nuevo portafolio"):
            with st.form("nuevo_portafolio", clear_on_submit=True):
                nombre = st.text_input("Nombre", placeholder="Retiro, Corto plazo…")
                descripcion = st.text_input("Descripción (opcional)")
                if st.form_submit_button("Crear"):
                    _ejecutar(
                        sesion,
                        lambda: registro.crear_portafolio(sesion, usuario.id, nombre, descripcion),
                        "Portafolio {resultado.nombre} creado.",
                    )
        fecha = st.date_input("Fecha de corte", value=_fecha_inicial(), format="DD/MM/YYYY")
        serie = st.radio(
            "Deflactar con",
            ["UVR", "IPC"],
            horizontal=True,
            help="UVR es diaria y se publica por adelantado. IPC es mensual.",
        )
        st.caption(AVISO_LEGAL)
    if portafolio is None:
        st.info("Cree un portafolio en la barra lateral.")
        return None
    return portafolio, fecha, serie


# --------------------------------------------------------------------------
# Pestañas
# --------------------------------------------------------------------------


def _resumen(sesion: Session, portafolio: Portafolio, fecha: date, serie: str) -> None:
    r = consultas.resumen(sesion, portafolio.id, fecha, serie)
    fila1 = st.columns(3)
    fila1[0].metric("Valor", formato.pesos(r.valor), border=True)
    fila1[1].metric("Aportes netos", formato.pesos(r.aportes_netos), border=True)
    fila1[2].metric("Ganancia", formato.pesos(r.ganancia), border=True)
    fila2 = st.columns(3)
    fila2[0].metric("TIR (E.A.)", formato.porcentaje(r.tir), border=True, help="Ponderada por dinero, desde el primer movimiento.")
    fila2[1].metric(f"TIR real ({serie})", formato.porcentaje(r.tir_real), border=True, help="Sobre flujos en pesos de la fecha de corte.")
    fila2[2].metric(f"TWR {fecha.year}", formato.porcentaje(r.twr_anio), border=True, help="Ponderado por tiempo, año corrido.")
    for aviso in r.avisos:
        st.warning(aviso)

    inicio = consultas.primera_fecha(sesion, portafolio.id)
    if inicio and inicio < fecha:
        st.subheader("Evolución")
        puntos = consultas.evolucion(sesion, portafolio.id, inicio, fecha)
        if len(puntos) >= 2:
            st.altair_chart(graficos.grafico_evolucion(puntos, _tema()), width="stretch")
            with st.expander("Ver tabla"):
                _tabla(
                    [
                        {
                            "Fecha": formato.fecha(p.fecha),
                            "Valor": formato.pesos(p.valor),
                            "Aportes netos": formato.pesos(p.aportes_netos),
                            "Ganancia": formato.pesos(p.valor - p.aportes_netos),
                        }
                        for p in reversed(puntos)
                    ]
                )
        else:
            st.caption("Registre valoraciones en varias fechas para ver la evolución.")

    st.subheader("Posiciones")
    _tabla(
        [
            {
                "Instrumento": p.nombre,
                "Tipo": p.tipo,
                "Valor": formato.pesos(p.valor),
                "Peso": formato.porcentaje(p.peso, 1),
                "Valorado el": formato.fecha(p.fecha_valoracion),
                "Aviso": p.aviso or "",
            }
            for p in consultas.posiciones(sesion, portafolio.id, fecha)
        ]
    )


def _intentar(funcion):
    try:
        return funcion(), None
    except consultas.ERRORES_CALCULO as error:
        return None, str(error)


def _rendimientos(sesion: Session, portafolio: Portafolio, fecha: date, serie: str) -> None:
    primera = consultas.primera_fecha(sesion, portafolio.id)
    if primera is None:
        st.info("Registre movimientos para calcular rendimientos.")
        return
    columnas = st.columns(2)
    inicio_defecto = max(primera, date(fecha.year - 1, 12, 31))
    # Sin ``key``: si cambia la fecha de corte, cambian los valores por defecto.
    inicio = columnas[0].date_input("Desde (cierre del día)", value=inicio_defecto, format="DD/MM/YYYY")
    fin = columnas[1].date_input("Hasta", value=fecha, format="DD/MM/YYYY")
    if fin <= inicio:
        st.error("La fecha final debe ser posterior a la inicial.")
        return

    # Si falta la serie de inflación se muestra al menos el rendimiento nominal.
    twr_nominal, error_twr = _intentar(lambda: rendimientos.twr_portafolio(sesion, portafolio.id, inicio, fin))
    dietz_nominal, error_dietz = _intentar(lambda: rendimientos.dietz_portafolio(sesion, portafolio.id, inicio, fin))
    twr = dietz = error_real = None
    if twr_nominal:
        twr, error_real = _intentar(lambda: inflacion.twr_real_portafolio(sesion, portafolio.id, inicio, fin, serie))
    if dietz_nominal:
        dietz, _ = _intentar(lambda: inflacion.dietz_real_portafolio(sesion, portafolio.id, inicio, fin, serie))

    def fila(nombre, real, base):
        if base is None:
            return None
        return {
            "Método": nombre,
            "Rendimiento": formato.porcentaje(base.rendimiento),
            "Anualizado": formato.porcentaje(base.anualizado),
            f"Inflación ({serie})": formato.porcentaje(real.inflacion) if real else formato.SIN_DATO,
            "Real": formato.porcentaje(real.real) if real else formato.SIN_DATO,
            "Real anualizado": formato.porcentaje(real.real_anualizado) if real else formato.SIN_DATO,
        }

    filas = [
        fila("TWR (ponderado por tiempo)", twr, twr_nominal),
        fila("Dietz modificado (ponderado por dinero)", dietz, dietz_nominal),
    ]
    _tabla([f for f in filas if f])
    st.caption(
        "El TWR mide la inversión sin el efecto de cuándo aportó o retiró; es el que se compara con un índice. "
        "Dietz refleja además el momento de sus aportes. Solo se anualiza desde un año."
    )
    for error in dict.fromkeys([error_twr, error_dietz, error_real]):
        if error:
            st.warning(error)
    if twr_nominal is not None and not twr_nominal.exacto:
        st.info(
            "El TWR es aproximado: hubo aportes o retiros sin valoración ese mismo día. "
            "Registre una valoración en cada fecha de aporte o retiro para que sea exacto."
        )

    st.subheader("Atribución")
    por = st.segmented_control(
        "Agrupar por", ["instrumento", "tipo"], default="instrumento", format_func=str.capitalize, key="atrib_por"
    ) or "instrumento"
    resultado, error = _intentar(lambda: atribucion.atribucion_portafolio(sesion, portafolio.id, inicio, fin, por))
    if resultado is None:
        st.warning(error)
        return
    st.caption(
        f"Las contribuciones suman el rendimiento Dietz del periodo: {formato.porcentaje(resultado.rendimiento)} "
        f"({formato.pesos(resultado.ganancia)})."
    )
    st.altair_chart(graficos.grafico_atribucion(resultado.filas, _tema()), width="stretch")
    _tabla(
        [
            {
                "Parte": f.nombre,
                "Tipo": f.tipo,
                "Valor inicial": formato.pesos(f.detalle.valor_inicial),
                "Valor final": formato.pesos(f.detalle.valor_final),
                "Flujo neto": formato.pesos(f.detalle.flujo_neto),
                "Ganancia": formato.pesos(f.detalle.ganancia),
                "Peso promedio": formato.porcentaje(f.detalle.peso, 1),
                "Rendimiento propio": formato.porcentaje(f.detalle.rendimiento),
                "Contribución": formato.porcentaje(f.detalle.contribucion),
            }
            for f in resultado.filas
        ]
    )


def _movimientos(sesion: Session, portafolio: Portafolio, fecha: date) -> None:
    instrumentos = consultas.instrumentos_de(sesion, portafolio.id)
    nombres = {i.id: i.nombre for i in instrumentos}
    izquierda, derecha = st.columns(2)
    with izquierda.form("movimiento", clear_on_submit=True):
        st.markdown("**Registrar movimiento**")
        dia = st.date_input("Fecha", value=fecha, format="DD/MM/YYYY")
        tipo = st.selectbox("Tipo", list(TipoMovimiento), format_func=lambda t: t.value.capitalize())
        instrumento = st.selectbox("Instrumento", [None, *nombres], format_func=lambda i: nombres.get(i, SIN_INSTRUMENTO))
        monto = st.text_input("Monto (siempre positivo)", placeholder="1.500.000")
        nota = st.text_input("Nota (opcional)")
        if st.form_submit_button("Guardar", type="primary"):
            _ejecutar(
                sesion,
                lambda: registro.registrar_movimiento(
                    sesion, portafolio, dia, tipo, _monto(monto), instrumento, nota
                ),
                "Movimiento guardado.",
            )
    with derecha.form("valoracion", clear_on_submit=True):
        st.markdown("**Registrar valoración**")
        st.caption("Valor del instrumento al cierre del día (saldo del extracto, precio × unidades).")
        dia_v = st.date_input("Fecha", value=fecha, format="DD/MM/YYYY", key="val_fecha")
        instrumento_v = st.selectbox("Instrumento", list(nombres), format_func=nombres.get, key="val_inst")
        valor = st.text_input("Valor", placeholder="10.250.000", key="val_valor")
        if st.form_submit_button("Guardar", type="primary"):
            _ejecutar(
                sesion,
                lambda: registro.registrar_valoracion(sesion, portafolio, instrumento_v, dia_v, _monto(valor)),
                "Valoración guardada.",
            )

    st.subheader("Movimientos")
    movimientos = consultas.movimientos_de(sesion, portafolio.id)
    _tabla(
        [
            {
                "Id": m.id,
                "Fecha": formato.fecha(m.fecha),
                "Tipo": m.tipo.value.capitalize(),
                "Instrumento": nombres.get(m.instrumento_id, ""),
                "Monto": formato.pesos(m.monto, 2),
                "Nota": m.nota or "",
                "Automático": "Sí" if m.clave_generacion else "",
            }
            for m in movimientos
        ]
    )
    if movimientos:
        with st.expander("Eliminar un movimiento"):
            elegido = _elegir(
                "Movimiento",
                movimientos,
                lambda m: f"#{m.id} · {formato.fecha(m.fecha)} · {m.tipo.value} · {formato.pesos(m.monto)}",
            )
            if st.button("Eliminar", type="secondary"):
                _ejecutar(sesion, lambda: registro.eliminar_movimiento(sesion, portafolio, elegido.id), "Movimiento eliminado.")

    st.subheader("Importar y exportar (CSV)")
    st.caption("UTF-8, fechas aaaa-mm-dd, punto decimal. Movimientos: fecha,instrumento,tipo,monto,nota. Valoraciones: fecha,instrumento,valor.")
    col1, col2 = st.columns(2)
    for columna, clase, importar, exportar in (
        (col1, "movimientos", csv_io.importar_movimientos, csv_io.exportar_movimientos),
        (col2, "valoraciones", csv_io.importar_valoraciones, csv_io.exportar_valoraciones),
    ):
        with columna:
            subido = st.file_uploader(f"Importar {clase}", type=["csv"], key=f"subir_{clase}")
            if subido is not None and st.button(f"Cargar {clase}", key=f"cargar_{clase}"):
                texto = io.StringIO(subido.getvalue().decode("utf-8-sig"))
                _ejecutar(sesion, lambda: importar(sesion, portafolio, texto), f"{{resultado}} {clase} importados.")
            salida = io.StringIO()
            exportar(sesion, portafolio, salida)
            st.download_button(
                f"Exportar {clase}", salida.getvalue(), file_name=f"{clase}_{portafolio.nombre}.csv", mime="text/csv"
            )


def _monto(texto: str) -> Decimal:
    try:
        return formato.leer_monto(texto)
    except ValueError as error:
        raise registro.DatoInvalidoError(str(error)) from None


def _instrumentos(sesion: Session, portafolio: Portafolio, fecha: date) -> None:
    instrumentos = consultas.instrumentos_de(sesion, portafolio.id)
    with st.form("instrumento", clear_on_submit=True):
        st.markdown("**Nuevo instrumento**")
        cols = st.columns([3, 2, 3, 2])
        nombre = cols[0].text_input("Nombre", placeholder="CDT Banco A 360 días")
        tipo = cols[1].selectbox("Tipo", list(TipoInstrumento), format_func=lambda t: t.value)
        emisor = cols[2].text_input("Emisor (opcional)")
        exenta = cols[3].checkbox("Exenta de GMF", help="Solo para cuentas: la cuenta marcada ante el banco como exenta.")
        if st.form_submit_button("Crear", type="primary"):
            _ejecutar(
                sesion,
                lambda: registro.crear_instrumento(sesion, portafolio, nombre, tipo, emisor, exenta),
                "Instrumento {resultado.nombre} creado.",
            )
    _tabla(
        [
            {"Nombre": i.nombre, "Tipo": i.tipo.value, "Emisor": i.emisor or "", "Exenta GMF": "Sí" if i.exenta_gmf else ""}
            for i in instrumentos
        ]
    )

    cdts = [i for i in instrumentos if i.tipo is TipoInstrumento.CDT]
    if cdts:
        st.subheader("CDT")
        elegido = _elegir("CDT", cdts, lambda i: i.nombre, key="cdt_elegido")
        condicion = elegido.condicion_cdt
        with st.form(f"condicion_{elegido.id}"):
            st.markdown("**Condiciones pactadas**")
            c = st.columns(3)
            capital = c[0].text_input("Capital", value=formato.numero(condicion.capital) if condicion else "")
            emision = c[1].date_input("Emisión", value=condicion.fecha_emision if condicion else fecha, format="DD/MM/YYYY")
            vencimiento = c[2].date_input(
                "Vencimiento", value=condicion.fecha_vencimiento if condicion else fecha, format="DD/MM/YYYY"
            )
            c = st.columns(4)
            tasa = c[0].text_input("Tasa (%)", value=formato.numero(condicion.tasa * 100, 4) if condicion else "")
            tipo_tasa = c[1].selectbox(
                "Tipo de tasa", list(TipoTasa), index=list(TipoTasa).index(condicion.tipo_tasa) if condicion else 0,
                format_func=lambda t: {"EFECTIVA_ANUAL": "Efectiva anual", "NOMINAL": "Nominal"}[t.value],
            )
            periodicidad = c[2].selectbox(
                "Pago de intereses", list(Periodicidad),
                index=list(Periodicidad).index(condicion.periodicidad) if condicion else len(Periodicidad) - 1,
                format_func=lambda p: p.value.replace("_", " ").capitalize(),
            )
            modalidad = c[3].selectbox(
                "Modalidad", list(Modalidad), index=list(Modalidad).index(condicion.modalidad) if condicion else 0,
                format_func=lambda m: m.value.capitalize(),
            )
            if st.form_submit_button("Guardar condiciones", type="primary"):
                _ejecutar(
                    sesion,
                    lambda: registro.registrar_condicion_cdt(
                        sesion, portafolio, elegido.id,
                        capital=_monto(capital), fecha_emision=emision, fecha_vencimiento=vencimiento,
                        tasa=_porcentaje(tasa), tipo_tasa=tipo_tasa, periodicidad=periodicidad, modalidad=modalidad,
                    ),
                    "Condiciones guardadas.",
                )
        if condicion:
            try:
                pagos = cdt.proyectar_cdt(sesion, elegido.id)
                estado = cdt.estado_cdt(sesion, elegido.id, fecha)
            except ERRORES_USUARIO as error:
                st.warning(str(error))
            else:
                c = st.columns(3)
                c[0].metric("Tasa efectiva anual", formato.porcentaje(float(cdt.terminos_cdt(sesion, elegido.id).tasa_ea)), border=True)
                c[1].metric(f"Valor al {formato.fecha(fecha)}", formato.pesos(estado.valor_bruto), border=True)
                c[2].metric("Neto estimado de retención", formato.pesos(estado.valor_neto_estimado), border=True)
                _tabla(
                    [
                        {
                            "Corte": formato.fecha(p.periodo.fin),
                            "Pago": formato.fecha(p.periodo.fecha_pago),
                            "Días": p.periodo.dias,
                            "Interés": formato.pesos(p.periodo.interes, 2),
                            "Retención": formato.pesos(p.retencion, 2),
                            "Capital": formato.pesos(p.periodo.capital),
                            "Total recibido": formato.pesos(p.total_recibido, 2),
                        }
                        for p in pagos
                    ]
                )
                incluir_compra = st.checkbox("Registrar también la compra en la emisión", value=True)
                if st.button(f"Registrar pagos y valoraciones hasta el {formato.fecha(fecha)}"):
                    _ejecutar(
                        sesion,
                        lambda: cdt.sincronizar_cdt(sesion, elegido.id, fecha, incluir_compra=incluir_compra),
                        "{resultado.movimientos_creados} movimientos y {resultado.valoraciones_creadas} valoraciones registrados.",
                    )

    cuentas = [i for i in instrumentos if i.tipo is TipoInstrumento.CUENTA]
    if cuentas:
        st.subheader("GMF de una cuenta")
        cuenta = _elegir("Cuenta", cuentas, lambda i: i.nombre, key="gmf_cuenta")
        c = st.columns(2)
        desde = c[0].date_input("Desde", value=date(fecha.year, 1, 1), format="DD/MM/YYYY", key="gmf_desde")
        hasta = c[1].date_input("Hasta", value=fecha, format="DD/MM/YYYY", key="gmf_hasta")
        try:
            cargos = impuestos.gmf_cuenta(sesion, cuenta.id, desde, hasta)
        except ERRORES_USUARIO as error:
            st.warning(str(error))
        else:
            _tabla(
                [
                    {"Fecha": formato.fecha(g.fecha), "Retiro": formato.pesos(g.monto), "Exento": formato.pesos(g.exento), "GMF": formato.pesos(g.gmf, 2)}
                    for g in cargos
                ]
            )
            if cargos:
                st.metric("GMF total", formato.pesos(sum(g.gmf for g in cargos), 2))


def _porcentaje(texto: str) -> Decimal:
    try:
        return formato.leer_porcentaje(texto)
    except ValueError as error:
        raise registro.DatoInvalidoError(str(error)) from None


def _datos(sesion: Session) -> None:
    st.subheader("Series")
    _tabla(
        [
            {
                "Código": s.codigo,
                "Nombre": s.nombre,
                "Frecuencia": s.frecuencia.capitalize(),
                "Datos": s.datos,
                "Desde": formato.fecha(s.primera),
                "Último dato": formato.fecha(s.ultima),
            }
            for s in series.listar_series(sesion)
        ]
    )
    with st.form("serie", clear_on_submit=False):
        st.markdown("**Cargar una serie desde archivo** (CSV o Excel descargado de Banrep, DANE o Superfinanciera)")
        c = st.columns(2)
        codigo = c[0].selectbox("Serie", [*catalogo.DEFINICIONES, "FIC"])
        nombre_fic = c[1].text_input("Nombre del FIC (solo para FIC)")
        c = st.columns(4)
        col_fecha = c[0].text_input("Columna de fecha", value="fecha")
        col_valor = c[1].text_input("Columna de valor", value="valor")
        decimal = c[2].selectbox("Separador decimal", [",", "."])
        escala = c[3].selectbox("Valores en", ["Unidades", "Porcentaje (÷100)"])
        archivo = st.file_uploader("Archivo", type=["csv", "txt", "xlsx"])
        if st.form_submit_button("Cargar", type="primary") and archivo is not None:
            if codigo == "FIC":
                if not nombre_fic.strip():
                    st.error("Escriba el nombre del FIC.")
                    return
                definicion = catalogo.definicion_fic(f"FIC:{nombre_fic.strip()}", nombre_fic.strip())
            else:
                definicion = catalogo.DEFINICIONES[codigo]
            _ejecutar(
                sesion,
                lambda: series.importar_archivo(
                    sesion, definicion, archivo.getvalue(), archivo.name,
                    columna_fecha=col_fecha, columna_valor=col_valor, decimal=decimal,
                    escala=Decimal("0.01") if escala.startswith("Porcentaje") else Decimal(1),
                ),
                "{resultado.codigo}: {resultado.nuevas} nuevos, {resultado.actualizadas} corregidos, {resultado.sin_cambio} sin cambio.",
            )
    if st.button("Actualizar TRM desde datos.gov.co"):
        ultima = series.ultima_fecha(sesion, "TRM") or date(2000, 1, 1)
        _ejecutar(
            sesion,
            lambda: series.actualizar_desde_fuente(sesion, catalogo.conector_trm(), ultima, hoy_bogota()),
            "TRM: {resultado.nuevas} nuevos.",
        )

    st.subheader("Parámetros normativos")
    _tabla(
        [
            {"Nombre": p.nombre, "Vigente desde": formato.fecha(p.vigente_desde), "Valor": str(p.valor), "Descripción": p.descripcion or ""}
            for p in series.listar_parametros(sesion)
        ]
    )
    subido = st.file_uploader("Cargar parámetros (nombre,vigente_desde,valor,descripcion)", type=["csv"], key="parametros")
    if subido is not None and st.button("Cargar parámetros"):
        texto = io.StringIO(subido.getvalue().decode("utf-8-sig"))
        _ejecutar(sesion, lambda: csv_io.importar_parametros(sesion, texto), "{resultado} parámetros cargados.")


# --------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="Portafolio", page_icon="📈", layout="wide")
    if os.environ.get("PORTAFOLIO_ENTORNO") == "produccion":
        # Esta interfaz no tiene ingreso de usuarios: en un servidor compartido
        # cualquiera vería todos los portafolios. Para varios usuarios, use la API.
        st.error("La interfaz Streamlit es de uso personal y no se ejecuta con PORTAFOLIO_ENTORNO=produccion.")
        return
    fabrica = _fabrica(url_base_datos())
    with fabrica() as sesion:
        try:
            seleccion = _barra_lateral(sesion)
        except (OperationalError, ProgrammingError) as error:
            st.error(f"No se pudo leer la base de datos ({error.orig}). ¿Ya corrió `alembic upgrade head`?")
            return
        _mostrar_aviso()
        if not consultas.usuarios(sesion):
            _bienvenida(sesion)
            return
        if seleccion is None:
            return
        portafolio, fecha, serie = seleccion
        st.title(portafolio.nombre)
        resumen, rend, movs, inst, datos = st.tabs(["Resumen", "Rendimientos", "Movimientos", "Instrumentos", "Datos"])
        with resumen:
            _resumen(sesion, portafolio, fecha, serie)
        with rend:
            _rendimientos(sesion, portafolio, fecha, serie)
        with movs:
            _movimientos(sesion, portafolio, fecha)
        with inst:
            _instrumentos(sesion, portafolio, fecha)
        with datos:
            _datos(sesion)


main()
