"""Tipos de columna portables entre SQLite y PostgreSQL."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.types import TypeDecorator


class EscalaExcedidaError(ValueError):
    pass


def validar_escala(valor: Decimal, escala: int, nombre: str = "El valor") -> Decimal:
    """Rechaza más decimales de los que guarda la columna.

    PostgreSQL redondearía en silencio y SQLite guardaría todo; así ambos
    motores se comportan igual.
    """
    valor = Decimal(valor)
    if valor.is_finite() and sin_ceros(valor).as_tuple().exponent < -escala:
        raise EscalaExcedidaError(f"{nombre} admite máximo {escala} decimales: {valor}")
    return valor


def sin_ceros(valor: Decimal) -> Decimal:
    """Quita los ceros finales sin pasar a notación exponencial.

    PostgreSQL devuelve ``10000000.000000`` (la escala de la columna) y SQLite
    el texto guardado; así ambos leen ``10000000`` y ``10000000.5``.
    """
    if valor == valor.to_integral_value():
        return valor.quantize(Decimal(1))
    return valor.normalize()


class DecimalExacto(TypeDecorator):
    """Número decimal exacto: ``NUMERIC`` en PostgreSQL, texto en SQLite.

    SQLite no tiene decimal nativo y SQLAlchemy lo convertiría a ``float``,
    así que ahí se guarda como texto. Siempre se lee como ``Decimal``.
    Rechaza ``float`` a propósito para que los errores de redondeo no entren
    por descuido.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int = 20, escala: int = 6):
        super().__init__()
        self.precision = precision
        self.escala = escala

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(self.precision + 2))
        return dialect.type_descriptor(Numeric(self.precision, self.escala, asdecimal=True))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("Use Decimal (o int/str) para montos; float pierde precisión.")
        valor = Decimal(value)
        validar_escala(valor, self.escala)
        if dialect.name == "sqlite":
            return str(valor)
        return valor

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return sin_ceros(Decimal(value))

    def __repr__(self) -> str:
        return f"DecimalExacto(precision={self.precision}, escala={self.escala})"


Dinero = DecimalExacto(20, 6)
"""Saldos, flujos e impuestos en pesos."""

Tasa = DecimalExacto(24, 10)
"""Valores de series (UVR, valor de unidad FIC, IPC) y parámetros."""
