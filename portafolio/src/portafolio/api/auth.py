"""Verificación de tokens de acceso (JWT).

* ``VerificadorOIDC``: tokens firmados por un proveedor de identidad (Auth0,
  Keycloak, Google, Entra ID, Cognito…). Valida firma con las llaves públicas
  del proveedor (JWKS), emisor, audiencia y vencimiento.
* ``VerificadorLocal``: tokens HS256 firmados por esta misma aplicación. Solo
  para desarrollo y pruebas; la configuración lo prohíbe en producción.

La API no maneja contraseñas: el ingreso ocurre en el proveedor.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Protocol

import jwt

from portafolio.services.cuenta import Identidad

ALGORITMOS_OIDC = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]
MARGEN_SEGUNDOS = 30
EMISOR_LOCAL = "portafolio-local"
AUDIENCIA_LOCAL = "portafolio-api"


class TokenInvalidoError(Exception):
    pass


class Verificador(Protocol):
    def verificar(self, token: str) -> Identidad: ...


def _identidad(claims: dict) -> Identidad:
    return Identidad(
        emisor=claims["iss"],
        sujeto=str(claims["sub"]),
        email=claims.get("email"),
        email_verificado=claims.get("email_verified") is True,
        nombre=claims.get("name"),
    )


def _decodificar(token: str, llave, algoritmos: list[str], emisor: str, audiencia: str) -> dict:
    try:
        return jwt.decode(
            token,
            llave,
            algorithms=algoritmos,
            audience=audiencia,
            issuer=emisor,
            leeway=MARGEN_SEGUNDOS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as error:
        raise TokenInvalidoError(str(error)) from error


class VerificadorLocal:
    def __init__(self, secreto: str, emisor: str = EMISOR_LOCAL, audiencia: str = AUDIENCIA_LOCAL):
        if len(secreto) < 32:
            raise ValueError("El secreto debe tener al menos 32 caracteres.")
        self._secreto, self.emisor, self.audiencia = secreto, emisor, audiencia

    def verificar(self, token: str) -> Identidad:
        return _identidad(_decodificar(token, self._secreto, ["HS256"], self.emisor, self.audiencia))

    def emitir(self, sujeto: str, email: str | None = None, nombre: str | None = None, horas: float = 8) -> str:
        ahora = int(time.time())
        claims = {"iss": self.emisor, "aud": self.audiencia, "sub": sujeto, "iat": ahora, "exp": ahora + int(horas * 3600)}
        if email:
            claims |= {"email": email, "email_verified": True}
        if nombre:
            claims["name"] = nombre
        return jwt.encode(claims, self._secreto, algorithm="HS256")


def descubrir_jwks_url(emisor: str, timeout: float = 10) -> str:
    url = emisor.rstrip("/") + "/.well-known/openid-configuration"
    with urllib.request.urlopen(url, timeout=timeout) as respuesta:
        return json.load(respuesta)["jwks_uri"]


class VerificadorOIDC:
    def __init__(
        self,
        emisor: str,
        audiencia: str,
        jwks_url: str | None = None,
        *,
        resolver_llave: Callable[[str], object] | None = None,
    ):
        """``resolver_llave(token) -> llave pública``; por defecto usa el JWKS del proveedor con caché."""
        self.emisor, self.audiencia = emisor, audiencia
        self._jwks_url = jwks_url
        self._cliente: jwt.PyJWKClient | None = None
        self._resolver = resolver_llave

    def _llave(self, token: str):
        if self._resolver is not None:
            return self._resolver(token)
        if self._cliente is None:
            self._cliente = jwt.PyJWKClient(self._jwks_url or descubrir_jwks_url(self.emisor), cache_keys=True, lifespan=3600)
        return self._cliente.get_signing_key_from_jwt(token).key

    def verificar(self, token: str) -> Identidad:
        try:
            llave = self._llave(token)
        except (jwt.PyJWTError, KeyError, OSError) as error:
            raise TokenInvalidoError(f"No se pudo obtener la llave del token: {error}") from error
        return _identidad(_decodificar(token, llave, ALGORITMOS_OIDC, self.emisor, self.audiencia))


def crear_verificador(config) -> Verificador:
    if config.modo_auth == "oidc":
        return VerificadorOIDC(config.oidc_emisor, config.oidc_audiencia, config.oidc_jwks_url)
    return VerificadorLocal(config.secreto_local)
