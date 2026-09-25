"""Portafolios, instrumentos, movimientos, valoraciones, CDT y rendimientos del usuario."""

from __future__ import annotations

import io
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from portafolio.api import esquemas as e
from portafolio.api.dependencias import instrumento_propio, obtener_sesion, portafolio_propio, usuario_autorizado
from portafolio.core.calendario import hoy_bogota
from portafolio.data.modelos import Instrumento, Movimiento, Portafolio, Usuario
from portafolio.services import (
    atribucion,
    cdt,
    consultas,
    csv_io,
    impuestos,
    inflacion,
    registro,
    rendimientos,
)

router = APIRouter(prefix="/v1/portafolios", tags=["portafolios"])

LIMITE_ARCHIVO = 5 * 1024 * 1024  # 5 MB


async def leer_archivo(archivo: UploadFile) -> str:
    contenido = await archivo.read(LIMITE_ARCHIVO + 1)
    if len(contenido) > LIMITE_ARCHIVO:
        raise HTTPException(413, detail={"codigo": "archivo_grande", "detalle": "Máximo 5 MB."})
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("latin-1")


def _fecha(fecha: date | None) -> date:
    return fecha or hoy_bogota()


# ------------------------------------------------------------------ portafolios


@router.get("", response_model=list[e.PortafolioSalida])
def listar(usuario: Usuario = Depends(usuario_autorizado), sesion: Session = Depends(obtener_sesion)):
    return consultas.portafolios_de(sesion, usuario.id)


@router.post("", response_model=e.PortafolioSalida, status_code=201)
def crear(entrada: e.PortafolioEntrada, usuario: Usuario = Depends(usuario_autorizado), sesion: Session = Depends(obtener_sesion)):
    portafolio = registro.crear_portafolio(sesion, usuario.id, entrada.nombre, entrada.descripcion)
    sesion.commit()
    return portafolio


@router.get("/{portafolio_id}", response_model=e.PortafolioSalida)
def obtener(portafolio: Portafolio = Depends(portafolio_propio)):
    return portafolio


# ------------------------------------------------------------------ instrumentos


@router.get("/{portafolio_id}/instrumentos", response_model=list[e.InstrumentoSalida])
def instrumentos(portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)):
    return consultas.instrumentos_de(sesion, portafolio.id)


@router.post("/{portafolio_id}/instrumentos", response_model=e.InstrumentoSalida, status_code=201)
def crear_instrumento(
    entrada: e.InstrumentoEntrada, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    instrumento = registro.crear_instrumento(sesion, portafolio, entrada.nombre, entrada.tipo, entrada.emisor, entrada.exenta_gmf)
    sesion.commit()
    return instrumento


# ------------------------------------------------------------------ movimientos y valoraciones


def _movimiento(m: Movimiento) -> e.MovimientoSalida:
    return e.MovimientoSalida(
        id=m.id, fecha=m.fecha, tipo=m.tipo, monto=m.monto, instrumento_id=m.instrumento_id, nota=m.nota,
        automatico=m.clave_generacion is not None,
    )


@router.get("/{portafolio_id}/movimientos", response_model=list[e.MovimientoSalida])
def movimientos(
    limite: int = Query(500, ge=1, le=5000),
    portafolio: Portafolio = Depends(portafolio_propio),
    sesion: Session = Depends(obtener_sesion),
):
    return [_movimiento(m) for m in consultas.movimientos_de(sesion, portafolio.id, limite)]


@router.post("/{portafolio_id}/movimientos", response_model=e.MovimientoSalida, status_code=201)
def crear_movimiento(
    entrada: e.MovimientoEntrada, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    m = registro.registrar_movimiento(
        sesion, portafolio, entrada.fecha, entrada.tipo, entrada.monto, entrada.instrumento_id, entrada.nota
    )
    sesion.commit()
    return _movimiento(m)


@router.delete("/{portafolio_id}/movimientos/{movimiento_id}", status_code=204)
def eliminar_movimiento(
    movimiento_id: int, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    try:
        registro.eliminar_movimiento(sesion, portafolio, movimiento_id)
    except registro.DatoInvalidoError:
        raise HTTPException(404, detail={"codigo": "no_encontrado", "detalle": "Movimiento no encontrado."}) from None
    sesion.commit()
    return Response(status_code=204)


@router.post("/{portafolio_id}/valoraciones", response_model=e.ValoracionSalida, status_code=201)
def crear_valoracion(
    entrada: e.ValoracionEntrada, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    v = registro.registrar_valoracion(sesion, portafolio, entrada.instrumento_id, entrada.fecha, entrada.valor)
    sesion.commit()
    return v


@router.post("/{portafolio_id}/movimientos/importar", response_model=e.ImportacionSalida)
async def importar_movimientos(
    archivo: UploadFile = File(...), portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    total = csv_io.importar_movimientos(sesion, portafolio, io.StringIO(await leer_archivo(archivo)))
    sesion.commit()
    return e.ImportacionSalida(registros=total)


@router.post("/{portafolio_id}/valoraciones/importar", response_model=e.ImportacionSalida)
async def importar_valoraciones(
    archivo: UploadFile = File(...), portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    total = csv_io.importar_valoraciones(sesion, portafolio, io.StringIO(await leer_archivo(archivo)))
    sesion.commit()
    return e.ImportacionSalida(registros=total)


@router.get("/{portafolio_id}/movimientos.csv", response_class=Response)
def exportar_movimientos(portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)):
    salida = io.StringIO()
    csv_io.exportar_movimientos(sesion, portafolio, salida)
    return Response(salida.getvalue(), media_type="text/csv; charset=utf-8")


@router.get("/{portafolio_id}/valoraciones.csv", response_class=Response)
def exportar_valoraciones(portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)):
    salida = io.StringIO()
    csv_io.exportar_valoraciones(sesion, portafolio, salida)
    return Response(salida.getvalue(), media_type="text/csv; charset=utf-8")


# ------------------------------------------------------------------ CDT y GMF


@router.put("/{portafolio_id}/instrumentos/{instrumento_id}/cdt", status_code=204)
def condiciones_cdt(
    entrada: e.CondicionCDTEntrada,
    instrumento: Instrumento = Depends(instrumento_propio),
    portafolio: Portafolio = Depends(portafolio_propio),
    sesion: Session = Depends(obtener_sesion),
):
    registro.registrar_condicion_cdt(sesion, portafolio, instrumento.id, **entrada.model_dump())
    sesion.commit()
    return Response(status_code=204)


@router.get("/{portafolio_id}/instrumentos/{instrumento_id}/cdt/pagos", response_model=list[e.PagoCDTSalida])
def pagos_cdt(instrumento: Instrumento = Depends(instrumento_propio), sesion: Session = Depends(obtener_sesion)):
    return [
        e.PagoCDTSalida(
            corte=p.periodo.fin, fecha_pago=p.periodo.fecha_pago, dias=p.periodo.dias, interes=p.periodo.interes,
            retencion=p.retencion, capital=p.periodo.capital, total_recibido=p.total_recibido,
        )
        for p in cdt.proyectar_cdt(sesion, instrumento.id)
    ]


@router.get("/{portafolio_id}/instrumentos/{instrumento_id}/cdt/estado", response_model=e.EstadoCDTSalida)
def estado_cdt(
    fecha: date | None = None, instrumento: Instrumento = Depends(instrumento_propio), sesion: Session = Depends(obtener_sesion)
):
    estado = cdt.estado_cdt(sesion, instrumento.id, _fecha(fecha))
    c = estado.causacion
    return e.EstadoCDTSalida(
        fecha=c.fecha, capital=c.capital, interes_causado=c.interes_causado, retencion_estimada=estado.retencion_estimada,
        valor_bruto=estado.valor_bruto, valor_neto_estimado=estado.valor_neto_estimado,
    )


@router.post("/{portafolio_id}/instrumentos/{instrumento_id}/cdt/sincronizar", response_model=e.SincronizacionSalida)
def sincronizar_cdt(
    hasta: date | None = None,
    incluir_compra: bool = True,
    instrumento: Instrumento = Depends(instrumento_propio),
    sesion: Session = Depends(obtener_sesion),
):
    resumen = cdt.sincronizar_cdt(sesion, instrumento.id, _fecha(hasta), incluir_compra=incluir_compra)
    sesion.commit()
    return e.SincronizacionSalida(movimientos_creados=resumen.movimientos_creados, valoraciones_creadas=resumen.valoraciones_creadas)


@router.get("/{portafolio_id}/instrumentos/{instrumento_id}/gmf", response_model=list[e.CargoGMFSalida])
def gmf(
    desde: date, hasta: date, instrumento: Instrumento = Depends(instrumento_propio), sesion: Session = Depends(obtener_sesion)
):
    return [e.CargoGMFSalida(fecha=c.fecha, monto=c.monto, exento=c.exento, gmf=c.gmf) for c in impuestos.gmf_cuenta(sesion, instrumento.id, desde, hasta)]


# ------------------------------------------------------------------ consultas y rendimientos


@router.get("/{portafolio_id}/resumen", response_model=e.ResumenSalida)
def resumen(
    fecha: date | None = None,
    serie: Literal["UVR", "IPC"] = "UVR",
    portafolio: Portafolio = Depends(portafolio_propio),
    sesion: Session = Depends(obtener_sesion),
):
    r = consultas.resumen(sesion, portafolio.id, _fecha(fecha), serie)
    return e.ResumenSalida(
        fecha=r.fecha, valor=r.valor, aportes_netos=r.aportes_netos, ganancia=r.ganancia,
        tir=r.tir, tir_real=r.tir_real, twr_anio=r.twr_anio, avisos=r.avisos,
    )


@router.get("/{portafolio_id}/posiciones", response_model=list[e.PosicionSalida])
def posiciones(fecha: date | None = None, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)):
    return consultas.posiciones(sesion, portafolio.id, _fecha(fecha))


@router.get("/{portafolio_id}/evolucion", response_model=list[e.PuntoEvolucionSalida])
def evolucion(
    desde: date, hasta: date | None = None, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
):
    return consultas.evolucion(sesion, portafolio.id, desde, _fecha(hasta))


def _periodo(nominal, real=None) -> e.PeriodoSalida:
    return e.PeriodoSalida(
        metodo=nominal.metodo, rendimiento=nominal.rendimiento, anualizado=nominal.anualizado,
        valor_inicial=nominal.valor_inicial, valor_final=nominal.valor_final, flujo_neto=nominal.flujo_neto,
        exacto=nominal.exacto, fechas_omitidas=nominal.fechas_omitidas,
        inflacion=real.inflacion if real else None, real=real.real if real else None,
        real_anualizado=real.real_anualizado if real else None,
    )


@router.get("/{portafolio_id}/rendimientos", response_model=e.RendimientosSalida)
def rendimientos_periodo(
    desde: date,
    hasta: date | None = None,
    serie: Literal["UVR", "IPC"] = "UVR",
    portafolio: Portafolio = Depends(portafolio_propio),
    sesion: Session = Depends(obtener_sesion),
):
    """TWR y Dietz del periodo (nominales y reales) y TIR desde el primer movimiento hasta ``hasta``.

    Lo que no se puede calcular queda en ``null`` con su explicación en ``avisos``.
    """
    hasta = _fecha(hasta)
    avisos: list[str] = []

    def intentar(funcion, etiqueta):
        try:
            return funcion()
        except consultas.ERRORES_CALCULO as error:
            avisos.append(f"{etiqueta}: {error}")
            return None

    twr = intentar(lambda: rendimientos.twr_portafolio(sesion, portafolio.id, desde, hasta), "TWR")
    dietz = intentar(lambda: rendimientos.dietz_portafolio(sesion, portafolio.id, desde, hasta), "Dietz")
    tir = intentar(lambda: rendimientos.tir_portafolio(sesion, portafolio.id, hasta), "TIR")
    twr_real = twr and intentar(lambda: inflacion.twr_real_portafolio(sesion, portafolio.id, desde, hasta, serie), "Inflación")
    dietz_real = dietz and twr_real and intentar(lambda: inflacion.dietz_real_portafolio(sesion, portafolio.id, desde, hasta, serie), "Dietz real")
    tir_real = tir and twr_real and intentar(lambda: inflacion.tir_real_portafolio(sesion, portafolio.id, hasta, serie), "TIR real")
    return e.RendimientosSalida(
        desde=desde,
        hasta=hasta,
        serie=serie,
        twr=_periodo(twr, twr_real) if twr else None,
        dietz=_periodo(dietz, dietz_real) if dietz else None,
        tir=e.TIRSalida(fecha_corte=hasta, tasa=tir.tasa, tasa_real=tir_real.tasa_real if tir_real else None, valor_final=tir.valor_final)
        if tir
        else None,
        avisos=avisos,
    )


@router.get("/{portafolio_id}/atribucion", response_model=e.AtribucionSalida)
def atribucion_periodo(
    desde: date,
    hasta: date | None = None,
    por: Literal["instrumento", "tipo"] = "instrumento",
    portafolio: Portafolio = Depends(portafolio_propio),
    sesion: Session = Depends(obtener_sesion),
):
    r = atribucion.atribucion_portafolio(sesion, portafolio.id, desde, _fecha(hasta), por)
    return e.AtribucionSalida(
        desde=r.fecha_inicio,
        hasta=r.fecha_fin,
        rendimiento=r.rendimiento,
        ganancia=r.ganancia,
        partes=[
            e.ContribucionSalida(
                nombre=f.nombre, tipo=f.tipo, instrumento_id=f.instrumento_id,
                valor_inicial=f.detalle.valor_inicial, valor_final=f.detalle.valor_final,
                flujo_neto=f.detalle.flujo_neto, ganancia=f.detalle.ganancia, peso=f.detalle.peso,
                rendimiento=f.detalle.rendimiento, contribucion=f.detalle.contribucion,
            )
            for f in r.filas
        ],
    )
