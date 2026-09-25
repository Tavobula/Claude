"""Alta y edición de datos personales, con validación.

La interfaz usa estas funciones en lugar de crear modelos directamente, para
que las reglas (montos positivos, instrumento del mismo portafolio, etc.)
vivan en un solo lugar y sirvan igual cuando exista la API.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portafolio.core.cdt import Modalidad, Periodicidad, TerminosCDT, TipoTasa
from portafolio.data.modelos import (
    CondicionCDT,
    Instrumento,
    Movimiento,
    Portafolio,
    TipoInstrumento,
    TipoMovimiento,
    Usuario,
    Valoracion,
)


class DatoInvalidoError(ValueError):
    pass


def _positivo(valor: Decimal, nombre: str, permitir_cero: bool = False) -> Decimal:
    if isinstance(valor, float):
        raise DatoInvalidoError(f"{nombre}: use Decimal, no float.")
    valor = Decimal(valor)
    if valor < 0 or (valor == 0 and not permitir_cero):
        raise DatoInvalidoError(f"{nombre} debe ser {'cero o ' if permitir_cero else ''}positivo.")
    return valor


def _nombre(texto: str, campo: str = "El nombre") -> str:
    texto = (texto or "").strip()
    if not texto:
        raise DatoInvalidoError(f"{campo} no puede estar vacío.")
    return texto


def crear_usuario(sesion: Session, nombre: str, email: str) -> Usuario:
    email = _nombre(email, "El correo").lower()
    if "@" not in email:
        raise DatoInvalidoError("Correo inválido.")
    if sesion.scalar(select(Usuario).where(Usuario.email == email)):
        raise DatoInvalidoError(f"Ya existe un usuario con el correo {email}.")
    usuario = Usuario(nombre=_nombre(nombre), email=email)
    sesion.add(usuario)
    sesion.flush()
    return usuario


def crear_portafolio(sesion: Session, usuario_id: int, nombre: str, descripcion: str | None = None) -> Portafolio:
    nombre = _nombre(nombre)
    existe = sesion.scalar(select(Portafolio).where(Portafolio.usuario_id == usuario_id, Portafolio.nombre == nombre))
    if existe:
        raise DatoInvalidoError(f"Ya tiene un portafolio llamado {nombre!r}.")
    portafolio = Portafolio(usuario_id=usuario_id, nombre=nombre, descripcion=(descripcion or "").strip() or None)
    sesion.add(portafolio)
    sesion.flush()
    return portafolio


def crear_instrumento(
    sesion: Session,
    portafolio: Portafolio,
    nombre: str,
    tipo: TipoInstrumento,
    emisor: str | None = None,
    exenta_gmf: bool = False,
) -> Instrumento:
    nombre = _nombre(nombre)
    existe = sesion.scalar(
        select(Instrumento).where(Instrumento.portafolio_id == portafolio.id, Instrumento.nombre == nombre)
    )
    if existe:
        raise DatoInvalidoError(f"Ya existe un instrumento llamado {nombre!r} en este portafolio.")
    if exenta_gmf and tipo is not TipoInstrumento.CUENTA:
        raise DatoInvalidoError("Solo una cuenta puede marcarse como exenta de GMF.")
    instrumento = Instrumento(
        usuario_id=portafolio.usuario_id,
        portafolio_id=portafolio.id,
        nombre=nombre,
        tipo=tipo,
        emisor=(emisor or "").strip() or None,
        exenta_gmf=exenta_gmf,
    )
    sesion.add(instrumento)
    sesion.flush()
    return instrumento


def _instrumento_de(sesion: Session, portafolio: Portafolio, instrumento_id: int | None) -> Instrumento | None:
    if instrumento_id is None:
        return None
    instrumento = sesion.get(Instrumento, instrumento_id)
    if instrumento is None or instrumento.portafolio_id != portafolio.id:
        raise DatoInvalidoError("El instrumento no pertenece a este portafolio.")
    return instrumento


def registrar_movimiento(
    sesion: Session,
    portafolio: Portafolio,
    fecha: date,
    tipo: TipoMovimiento,
    monto: Decimal,
    instrumento_id: int | None = None,
    nota: str | None = None,
) -> Movimiento:
    if instrumento_id is None and tipo not in (TipoMovimiento.APORTE, TipoMovimiento.RETIRO):
        raise DatoInvalidoError(f"Un movimiento de tipo {tipo.value} debe indicar el instrumento.")
    instrumento = _instrumento_de(sesion, portafolio, instrumento_id)
    movimiento = Movimiento(
        usuario_id=portafolio.usuario_id,
        portafolio_id=portafolio.id,
        instrumento_id=instrumento.id if instrumento else None,
        fecha=fecha,
        tipo=tipo,
        monto=_positivo(monto, "El monto"),
        nota=(nota or "").strip() or None,
    )
    sesion.add(movimiento)
    sesion.flush()
    return movimiento


def eliminar_movimiento(sesion: Session, portafolio: Portafolio, movimiento_id: int) -> None:
    movimiento = sesion.get(Movimiento, movimiento_id)
    if movimiento is None or movimiento.portafolio_id != portafolio.id:
        raise DatoInvalidoError("El movimiento no pertenece a este portafolio.")
    sesion.delete(movimiento)
    sesion.flush()


def registrar_valoracion(
    sesion: Session, portafolio: Portafolio, instrumento_id: int, fecha: date, valor: Decimal
) -> Valoracion:
    """Crea la valoración o reemplaza la que ya exista ese día."""
    instrumento = _instrumento_de(sesion, portafolio, instrumento_id)
    valor = _positivo(valor, "El valor", permitir_cero=True)
    existente = sesion.scalar(
        select(Valoracion).where(Valoracion.instrumento_id == instrumento.id, Valoracion.fecha == fecha)
    )
    if existente:
        existente.valor = valor
        sesion.flush()
        return existente
    valoracion = Valoracion(
        usuario_id=portafolio.usuario_id,
        portafolio_id=portafolio.id,
        instrumento_id=instrumento.id,
        fecha=fecha,
        valor=valor,
    )
    sesion.add(valoracion)
    sesion.flush()
    return valoracion


def registrar_condicion_cdt(
    sesion: Session,
    portafolio: Portafolio,
    instrumento_id: int,
    *,
    capital: Decimal,
    fecha_emision: date,
    fecha_vencimiento: date,
    tasa: Decimal,
    tipo_tasa: TipoTasa = TipoTasa.EFECTIVA_ANUAL,
    periodicidad: Periodicidad = Periodicidad.AL_VENCIMIENTO,
    modalidad: Modalidad = Modalidad.VENCIDA,
    base_dias: int | None = None,
) -> CondicionCDT:
    """Crea o reemplaza las condiciones del CDT, validándolas con el núcleo."""
    instrumento = _instrumento_de(sesion, portafolio, instrumento_id)
    if instrumento.tipo is not TipoInstrumento.CDT:
        raise DatoInvalidoError(f"{instrumento.nombre!r} no es un CDT.")
    capital = _positivo(capital, "El capital")
    tasa = _positivo(tasa, "La tasa", permitir_cero=True)
    try:
        terminos = TerminosCDT(
            capital, fecha_emision, fecha_vencimiento, tasa, tipo_tasa, periodicidad, modalidad, base_dias or 365
        )
        terminos.tasa_ea  # valida, p. ej., una tasa nominal sin periodicidad
    except ValueError as error:
        raise DatoInvalidoError(str(error)) from error

    condicion = sesion.get(CondicionCDT, instrumento.id) or CondicionCDT(
        instrumento_id=instrumento.id, usuario_id=portafolio.usuario_id, portafolio_id=portafolio.id
    )
    condicion.capital = capital
    condicion.fecha_emision = fecha_emision
    condicion.fecha_vencimiento = fecha_vencimiento
    condicion.tasa = tasa
    condicion.tipo_tasa = tipo_tasa
    condicion.periodicidad = periodicidad
    condicion.modalidad = modalidad
    condicion.base_dias = base_dias
    sesion.add(condicion)
    sesion.flush()
    return condicion
