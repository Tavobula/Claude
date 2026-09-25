"""Tipos de columna portables entre SQLite y PostgreSQL."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.types import TypeDecorator


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
        if dialect.name == "sqlite":
            return str(valor)
        return valor

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)

    def __repr__(self) -> str:
        return f"DecimalExacto(precision={self.precision}, escala={self.escala})"


Dinero = DecimalExacto(20, 6)
"""Saldos, flujos e impuestos en pesos."""

Tasa = DecimalExacto(24, 10)
"""Valores de series (UVR, valor de unidad FIC, IPC) y parámetros."""
