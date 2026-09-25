"""Dependencias de FastAPI: sesión, usuario actual, autorización y pertenencia.

Regla de aislamiento: un portafolio o instrumento de otro usuario responde
404, igual que uno que no existe, para no revelar qué ids están en uso.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from portafolio.api.auth import TokenInvalidoError
from portafolio.api.config import Configuracion
from portafolio.data.modelos import Instrumento, Portafolio, Usuario
from portafolio.services import cuenta

_bearer = HTTPBearer(auto_error=False)


def configuracion(request: Request) -> Configuracion:
    return request.app.state.config


def obtener_sesion(request: Request) -> Iterator[Session]:
    """Una sesión por solicitud. Las rutas que escriben llaman ``commit()`` explícitamente."""
    with request.app.state.fabrica() as sesion:
        try:
            yield sesion
        finally:
            sesion.rollback()


def _no_autenticado(detalle: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"codigo": "no_autenticado", "detalle": detalle},
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_actual(
    request: Request,
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
    sesion: Session = Depends(obtener_sesion),
) -> Usuario:
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise _no_autenticado("Falta el token de acceso (Authorization: Bearer ...).")
    try:
        identidad = request.app.state.verificador.verificar(credenciales.credentials)
    except TokenInvalidoError as error:
        raise _no_autenticado(f"Token inválido: {error}") from None
    usuario = cuenta.usuario_por_identidad(sesion, identidad.emisor, identidad.sujeto)
    if usuario is None:
        usuario = cuenta.obtener_o_crear_usuario(sesion, identidad)
        sesion.commit()
    return usuario


def usuario_autorizado(
    usuario: Usuario = Depends(usuario_actual), config: Configuracion = Depends(configuracion)
) -> Usuario:
    """Exige la autorización de tratamiento de datos de la versión vigente de la política."""
    if not cuenta.tiene_autorizacion(usuario, config.version_politica):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "codigo": "autorizacion_requerida",
                "detalle": "Acepte la política de tratamiento de datos (POST /v1/yo/autorizacion).",
                "version": config.version_politica,
            },
        )
    return usuario


def administrador(usuario: Usuario = Depends(usuario_autorizado)) -> Usuario:
    if not usuario.es_administrador:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"codigo": "solo_administradores", "detalle": "Requiere rol de administrador."})
    return usuario


def _no_encontrado(recurso: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail={"codigo": "no_encontrado", "detalle": f"{recurso} no encontrado."})


def portafolio_propio(
    portafolio_id: int, usuario: Usuario = Depends(usuario_autorizado), sesion: Session = Depends(obtener_sesion)
) -> Portafolio:
    portafolio = sesion.get(Portafolio, portafolio_id)
    if portafolio is None or portafolio.usuario_id != usuario.id:
        raise _no_encontrado("Portafolio")
    return portafolio


def instrumento_propio(
    instrumento_id: int, portafolio: Portafolio = Depends(portafolio_propio), sesion: Session = Depends(obtener_sesion)
) -> Instrumento:
    instrumento = sesion.get(Instrumento, instrumento_id)
    if instrumento is None or instrumento.portafolio_id != portafolio.id:
        raise _no_encontrado("Instrumento")
    return instrumento
