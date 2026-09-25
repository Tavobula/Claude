"""Identidad, autorización de datos y derechos del titular (Ley 1581 de 2012).

* Los usuarios que ingresan por la API se identifican por el emisor y el
  sujeto del token (``iss`` y ``sub``), no por el correo: un correo puede
  cambiar o no estar verificado. Nunca se vincula una cuenta existente solo
  porque coincide el correo; eso se hace a mano con ``vincular_identidad``.
* Antes de guardar o consultar datos financieros, el usuario debe aceptar la
  política de tratamiento de datos vigente.
* El titular puede descargar todos sus datos y eliminar su cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from portafolio.core.calendario import ahora_bogota
from portafolio.data.modelos import (
    CondicionCDT,
    Instrumento,
    Movimiento,
    Objetivo,
    Portafolio,
    Usuario,
    Valoracion,
)

TABLAS_PERSONALES = (Valoracion, Movimiento, CondicionCDT, Objetivo, Instrumento, Portafolio)


class ConflictoIdentidadError(RuntimeError):
    """Hay un usuario con ese correo pero otra identidad (o ninguna)."""


@dataclass(frozen=True)
class Identidad:
    emisor: str
    sujeto: str
    email: str | None = None
    email_verificado: bool = False
    nombre: str | None = None


def usuario_por_identidad(sesion: Session, emisor: str, sujeto: str) -> Usuario | None:
    return sesion.scalar(select(Usuario).where(Usuario.emisor == emisor, Usuario.sujeto == sujeto))


def usuario_por_email(sesion: Session, email: str) -> Usuario | None:
    return sesion.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))


def obtener_o_crear_usuario(sesion: Session, identidad: Identidad) -> Usuario:
    """Devuelve el usuario de la identidad; lo crea en su primer ingreso."""
    usuario = usuario_por_identidad(sesion, identidad.emisor, identidad.sujeto)
    if usuario is not None:
        return usuario
    # Sin correo verificado se usa un identificador interno único: el correo es
    # único en la tabla y no se debe poder "reservar" el de otra persona.
    email = (identidad.email or "").strip().lower()
    if not (email and identidad.email_verificado):
        email = f"{identidad.sujeto}@{_dominio_interno(identidad.emisor)}"
    if usuario_por_email(sesion, email) is not None:
        raise ConflictoIdentidadError(
            f"Ya existe un usuario con el correo {email}. Un administrador debe vincular la cuenta "
            "(python -m portafolio usuarios vincular)."
        )
    usuario = Usuario(
        nombre=(identidad.nombre or email.split("@")[0])[:200],
        email=email,
        emisor=identidad.emisor,
        sujeto=identidad.sujeto,
    )
    sesion.add(usuario)
    sesion.flush()
    return usuario


def _dominio_interno(emisor: str) -> str:
    limpio = "".join(c if c.isalnum() else "-" for c in emisor.lower().split("://")[-1]).strip("-")
    return f"{limpio[:60] or 'emisor'}.sin-correo.invalid"


def vincular_identidad(sesion: Session, email: str, emisor: str, sujeto: str) -> Usuario:
    """Asocia un usuario existente (p. ej. el del modo personal) a una identidad de ingreso."""
    usuario = usuario_por_email(sesion, email)
    if usuario is None:
        raise LookupError(f"No hay un usuario con el correo {email}.")
    otro = usuario_por_identidad(sesion, emisor, sujeto)
    if otro is not None and otro.id != usuario.id:
        raise ConflictoIdentidadError("Esa identidad ya pertenece a otro usuario.")
    usuario.emisor, usuario.sujeto = emisor, sujeto
    sesion.flush()
    return usuario


def definir_administrador(sesion: Session, email: str, es_administrador: bool = True) -> Usuario:
    usuario = usuario_por_email(sesion, email)
    if usuario is None:
        raise LookupError(f"No hay un usuario con el correo {email}.")
    usuario.es_administrador = es_administrador
    sesion.flush()
    return usuario


# --------------------------------------------------------------------------
# Autorización de tratamiento de datos
# --------------------------------------------------------------------------


def tiene_autorizacion(usuario: Usuario, version_vigente: str) -> bool:
    return usuario.autorizacion_datos_en is not None and usuario.version_politica == version_vigente


def registrar_autorizacion(sesion: Session, usuario: Usuario, version: str) -> Usuario:
    """Guarda cuándo y qué versión de la política aceptó el titular (prueba de la autorización)."""
    usuario.autorizacion_datos_en = ahora_bogota()
    usuario.version_politica = version
    sesion.flush()
    return usuario


# --------------------------------------------------------------------------
# Derechos del titular: conocer (exportar) y suprimir
# --------------------------------------------------------------------------


def _valor(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if hasattr(v, "value"):  # enumeraciones
        return v.value
    return v


def _fila(objeto) -> dict:
    return {c.key: _valor(getattr(objeto, c.key)) for c in objeto.__mapper__.column_attrs}


def exportar_datos(sesion: Session, usuario: Usuario) -> dict:
    """Todos los datos personales del usuario, listos para serializar como JSON."""
    datos = {"usuario": _fila(usuario), "exportado_en": ahora_bogota().isoformat()}
    for modelo in reversed(TABLAS_PERSONALES):
        filas = sesion.scalars(select(modelo).where(modelo.usuario_id == usuario.id))
        datos[modelo.__tablename__] = [_fila(f) for f in filas]
    return datos


def eliminar_usuario(sesion: Session, usuario: Usuario) -> dict[str, int]:
    """Borra al usuario y todos sus datos personales. Los datos globales no se tocan."""
    borrados = {}
    for modelo in TABLAS_PERSONALES:  # de las hojas hacia la raíz, por las llaves foráneas
        resultado = sesion.execute(delete(modelo).where(modelo.usuario_id == usuario.id))
        borrados[modelo.__tablename__] = resultado.rowcount
    borrados["usuario"] = sesion.execute(delete(Usuario).where(Usuario.id == usuario.id)).rowcount
    sesion.expire_all()  # los objetos cargados ya no existen en la base
    return borrados
