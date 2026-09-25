"""Configuración de la API desde variables de entorno.

| Variable | Uso |
|---|---|
| ``PORTAFOLIO_DB_URL`` | Base de datos (PostgreSQL en producción) |
| ``PORTAFOLIO_ENTORNO`` | ``desarrollo`` (defecto) o ``produccion`` |
| ``PORTAFOLIO_AUTH_MODO`` | ``oidc`` o ``local``; en producción solo ``oidc`` |
| ``PORTAFOLIO_OIDC_EMISOR`` | ``iss`` del proveedor, p. ej. ``https://cuenta.ejemplo.com/`` |
| ``PORTAFOLIO_OIDC_AUDIENCIA`` | ``aud`` que el proveedor pone en los tokens de esta API |
| ``PORTAFOLIO_OIDC_JWKS_URL`` | Opcional; si falta se descubre en ``/.well-known/openid-configuration`` |
| ``PORTAFOLIO_AUTH_SECRETO`` | Solo modo local: secreto HS256 de al menos 32 caracteres |
| ``PORTAFOLIO_POLITICA_VERSION`` | Versión vigente de la política de datos |
| ``PORTAFOLIO_CORS_ORIGENES`` | Orígenes web permitidos, separados por coma |
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from portafolio.data.db import url_base_datos

VERSION_POLITICA = "2026-09"


class ConfiguracionInvalidaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Configuracion:
    url_base_datos: str
    modo_auth: str = "local"
    entorno: str = "desarrollo"
    oidc_emisor: str | None = None
    oidc_audiencia: str | None = None
    oidc_jwks_url: str | None = None
    secreto_local: str | None = None
    version_politica: str = VERSION_POLITICA
    origenes_cors: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.modo_auth not in ("oidc", "local"):
            raise ConfiguracionInvalidaError("PORTAFOLIO_AUTH_MODO debe ser 'oidc' o 'local'.")
        if self.entorno == "produccion":
            if self.modo_auth != "oidc":
                raise ConfiguracionInvalidaError("En producción la autenticación debe ser 'oidc'.")
            if self.url_base_datos.startswith("sqlite"):
                raise ConfiguracionInvalidaError("En producción use PostgreSQL, no SQLite.")
        if self.modo_auth == "oidc" and not (self.oidc_emisor and self.oidc_audiencia):
            raise ConfiguracionInvalidaError("Faltan PORTAFOLIO_OIDC_EMISOR y PORTAFOLIO_OIDC_AUDIENCIA.")
        if self.modo_auth == "local" and len(self.secreto_local or "") < 32:
            raise ConfiguracionInvalidaError("PORTAFOLIO_AUTH_SECRETO debe tener al menos 32 caracteres.")

    @classmethod
    def desde_entorno(cls) -> Configuracion:
        entorno = os.environ.get("PORTAFOLIO_ENTORNO", "desarrollo")
        origenes = tuple(o.strip() for o in os.environ.get("PORTAFOLIO_CORS_ORIGENES", "").split(",") if o.strip())
        return cls(
            url_base_datos=url_base_datos(),
            modo_auth=os.environ.get("PORTAFOLIO_AUTH_MODO", "oidc" if entorno == "produccion" else "local"),
            entorno=entorno,
            oidc_emisor=os.environ.get("PORTAFOLIO_OIDC_EMISOR"),
            oidc_audiencia=os.environ.get("PORTAFOLIO_OIDC_AUDIENCIA"),
            oidc_jwks_url=os.environ.get("PORTAFOLIO_OIDC_JWKS_URL"),
            secreto_local=os.environ.get("PORTAFOLIO_AUTH_SECRETO"),
            version_politica=os.environ.get("PORTAFOLIO_POLITICA_VERSION", VERSION_POLITICA),
            origenes_cors=origenes,
        )
