"""Modelo de datos.

Dos grupos de tablas:

* Globales (comunes a todos los usuarios, se cargan una sola vez):
  ``Serie`` / ``ValorSerie`` (IPC, UVR, IBR, precios BVC, valor de unidad FIC)
  y ``Parametro`` (retención, GMF, base de días) con fecha de vigencia.
* Personales: todas llevan ``usuario_id`` y ``portafolio_id``. Una llave
  foránea compuesta contra ``portafolio(id, usuario_id)`` impide que un
  registro quede con un usuario distinto al dueño del portafolio.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from portafolio.core.calendario import ahora_bogota
from portafolio.core.cdt import Modalidad, Periodicidad, TipoTasa
from portafolio.core.inflacion import Frecuencia
from portafolio.data.tipos import Dinero, Tasa

# Nombres de restricciones deterministas: Alembic los necesita para poder
# modificarlas después, sobre todo en SQLite (modo batch).
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


def _enum(clase: type[enum.Enum]) -> Enum:
    # native_enum=False: VARCHAR + CHECK. Portable y agregar valores no
    # exige migrar un tipo ENUM en PostgreSQL.
    return Enum(clase, native_enum=False, length=20, validate_strings=True)


# --------------------------------------------------------------------------
# Enumeraciones
# --------------------------------------------------------------------------


class TipoSerie(str, enum.Enum):
    INDICADOR = "INDICADOR"  # IPC, UVR, IBR, TRM
    PRECIO = "PRECIO"  # acciones y ETF en la BVC
    VALOR_UNIDAD = "VALOR_UNIDAD"  # fondos de inversión colectiva


class TipoInstrumento(str, enum.Enum):
    CUENTA = "CUENTA"  # cuenta de ahorros / efectivo del portafolio
    CDT = "CDT"
    FIC = "FIC"
    ACCION = "ACCION"
    ETF = "ETF"
    BONO = "BONO"
    OTRO = "OTRO"


class TipoMovimiento(str, enum.Enum):
    # Flujos externos: entran o salen del portafolio.
    APORTE = "APORTE"
    RETIRO = "RETIRO"
    # Flujos internos: entre el efectivo y los instrumentos.
    COMPRA = "COMPRA"
    VENTA = "VENTA"
    DIVIDENDO = "DIVIDENDO"
    INTERES = "INTERES"
    IMPUESTO = "IMPUESTO"
    COMISION = "COMISION"


# --------------------------------------------------------------------------
# Datos globales
# --------------------------------------------------------------------------


class Serie(Base):
    __tablename__ = "serie"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(60), unique=True)  # "UVR", "IPC", "BVC:ECOPETROL"
    nombre: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[TipoSerie] = mapped_column(_enum(TipoSerie))
    fuente: Mapped[str | None] = mapped_column(String(100))  # "Banrep", "DANE", "Superfinanciera"
    unidad: Mapped[str | None] = mapped_column(String(40))
    # MENSUAL: un valor por mes, guardado con fecha del día 1 (IPC).
    frecuencia: Mapped[Frecuencia] = mapped_column(
        _enum(Frecuencia), default=Frecuencia.DIARIA, server_default=Frecuencia.DIARIA.value
    )

    valores: Mapped[list[ValorSerie]] = relationship(back_populates="serie")


class ValorSerie(Base):
    __tablename__ = "valor_serie"
    __table_args__ = (UniqueConstraint("serie_id", "fecha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    serie_id: Mapped[int] = mapped_column(ForeignKey("serie.id", ondelete="CASCADE"), index=True)
    fecha: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Tasa)

    serie: Mapped[Serie] = relationship(back_populates="valores")


class Parametro(Base):
    """Parámetro normativo con vigencia (retención en la fuente, GMF, base de días).

    El valor aplicable a una fecha es el de mayor ``vigente_desde`` que no la
    supere, de modo que el pasado se recalcula con la tarifa de su momento.
    """

    __tablename__ = "parametro"
    __table_args__ = (UniqueConstraint("nombre", "vigente_desde"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    vigente_desde: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Tasa)
    descripcion: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------
# Datos personales
# --------------------------------------------------------------------------


class Usuario(Base):
    __tablename__ = "usuario"
    __table_args__ = (UniqueConstraint("emisor", "sujeto"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_bogota)
    # Identidad en el proveedor de ingreso (claims "iss" y "sub" del token).
    # Nulos en el modo personal, donde no hay ingreso.
    emisor: Mapped[str | None] = mapped_column(String(255))
    sujeto: Mapped[str | None] = mapped_column(String(255))
    es_administrador: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Autorización de tratamiento de datos personales (Ley 1581 de 2012).
    autorizacion_datos_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version_politica: Mapped[str | None] = mapped_column(String(20))

    portafolios: Mapped[list[Portafolio]] = relationship(back_populates="usuario")


class Portafolio(Base):
    __tablename__ = "portafolio"
    __table_args__ = (
        UniqueConstraint("usuario_id", "nombre"),
        # Destino de las llaves compuestas de las tablas personales.
        UniqueConstraint("id", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(100))  # "Retiro", "Corto plazo"
    descripcion: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora_bogota)

    usuario: Mapped[Usuario] = relationship(back_populates="portafolios")
    instrumentos: Mapped[list[Instrumento]] = relationship(back_populates="portafolio")


def _fk_portafolio() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["portafolio_id", "usuario_id"], ["portafolio.id", "portafolio.usuario_id"]
    )


class Instrumento(Base):
    __tablename__ = "instrumento"
    __table_args__ = (
        _fk_portafolio(),
        UniqueConstraint("portafolio_id", "nombre"),
        UniqueConstraint("id", "portafolio_id", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(index=True)
    portafolio_id: Mapped[int] = mapped_column(index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[TipoInstrumento] = mapped_column(_enum(TipoInstrumento))
    emisor: Mapped[str | None] = mapped_column(String(200))
    moneda: Mapped[str] = mapped_column(String(3), default="COP")
    # Serie global de precios o valor de unidad, si el instrumento tiene una.
    serie_id: Mapped[int | None] = mapped_column(ForeignKey("serie.id"))
    # Cuenta marcada como exenta de GMF (una por persona, hasta el tope mensual).
    exenta_gmf: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    portafolio: Mapped[Portafolio] = relationship(back_populates="instrumentos")
    condicion_cdt: Mapped[CondicionCDT | None] = relationship(back_populates="instrumento")


def _fk_instrumento() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["instrumento_id", "portafolio_id", "usuario_id"],
        ["instrumento.id", "instrumento.portafolio_id", "instrumento.usuario_id"],
    )


class Movimiento(Base):
    """Flujo de dinero. ``monto`` es siempre positivo; el signo lo da ``tipo``."""

    __tablename__ = "movimiento"
    __table_args__ = (
        _fk_portafolio(),
        _fk_instrumento(),
        UniqueConstraint("instrumento_id", "clave_generacion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(index=True)
    portafolio_id: Mapped[int] = mapped_column(index=True)
    # Nulo para aportes y retiros que no pasan por un instrumento específico.
    instrumento_id: Mapped[int | None] = mapped_column(index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    tipo: Mapped[TipoMovimiento] = mapped_column(_enum(TipoMovimiento))
    monto: Mapped[Decimal] = mapped_column(Dinero)
    nota: Mapped[str | None] = mapped_column(Text)
    # Identifica los movimientos generados por el sistema (p. ej. "cdt:interes:2025-06-03")
    # para no duplicarlos al regenerar. Nulo en los que registra el usuario.
    clave_generacion: Mapped[str | None] = mapped_column(String(60))

    instrumento: Mapped[Instrumento | None] = relationship()


class Valoracion(Base):
    """Valor de mercado de un instrumento en una fecha (saldo, precio x unidades)."""

    __tablename__ = "valoracion"
    __table_args__ = (
        _fk_portafolio(),
        _fk_instrumento(),
        UniqueConstraint("instrumento_id", "fecha"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(index=True)
    portafolio_id: Mapped[int] = mapped_column(index=True)
    instrumento_id: Mapped[int] = mapped_column(index=True)
    fecha: Mapped[date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Dinero)

    instrumento: Mapped[Instrumento] = relationship()


class CondicionCDT(Base):
    """Condiciones pactadas de un CDT de tasa fija (una por instrumento)."""

    __tablename__ = "condicion_cdt"
    __table_args__ = (_fk_portafolio(), _fk_instrumento())

    instrumento_id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(index=True)
    portafolio_id: Mapped[int] = mapped_column(index=True)
    capital: Mapped[Decimal] = mapped_column(Dinero)
    fecha_emision: Mapped[date] = mapped_column(Date)
    fecha_vencimiento: Mapped[date] = mapped_column(Date)
    tasa: Mapped[Decimal] = mapped_column(Tasa)  # fracción: 0.105 = 10,5 %
    tipo_tasa: Mapped[TipoTasa] = mapped_column(_enum(TipoTasa), default=TipoTasa.EFECTIVA_ANUAL)
    periodicidad: Mapped[Periodicidad] = mapped_column(
        _enum(Periodicidad), default=Periodicidad.AL_VENCIMIENTO
    )
    modalidad: Mapped[Modalidad] = mapped_column(_enum(Modalidad), default=Modalidad.VENCIDA)
    # Nulo: se usa el parámetro "base_dias" vigente en la emisión.
    base_dias: Mapped[int | None]

    instrumento: Mapped[Instrumento] = relationship(back_populates="condicion_cdt")


class Objetivo(Base):
    __tablename__ = "objetivo"
    __table_args__ = (_fk_portafolio(),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(index=True)
    portafolio_id: Mapped[int] = mapped_column(index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    monto_meta: Mapped[Decimal] = mapped_column(Dinero)
    fecha_meta: Mapped[date] = mapped_column(Date)
    # Meta en pesos constantes (deflactada con UVR/IPC) o nominales.
    en_pesos_reales: Mapped[bool] = mapped_column(default=True)
