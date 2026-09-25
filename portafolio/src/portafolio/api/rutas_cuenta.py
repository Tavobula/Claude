"""Cuenta del usuario: política de datos, autorización, exportación y supresión."""

from __future__ import annotations

from importlib import resources

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from portafolio.api.config import Configuracion
from portafolio.api.dependencias import configuracion, obtener_sesion, usuario_actual
from portafolio.api.esquemas import AutorizacionEntrada, PoliticaSalida, UsuarioSalida
from portafolio.data.modelos import Usuario
from portafolio.services import cuenta

router = APIRouter(prefix="/v1", tags=["cuenta"])


def texto_politica() -> str:
    return resources.files("portafolio.api").joinpath("politica_tratamiento_datos.md").read_text(encoding="utf-8")


def _usuario(usuario: Usuario, config: Configuracion) -> UsuarioSalida:
    return UsuarioSalida(
        id=usuario.id,
        nombre=usuario.nombre,
        email=usuario.email,
        es_administrador=usuario.es_administrador,
        autorizacion_vigente=cuenta.tiene_autorizacion(usuario, config.version_politica),
        version_politica_aceptada=usuario.version_politica,
        version_politica_vigente=config.version_politica,
        autorizacion_datos_en=usuario.autorizacion_datos_en,
    )


@router.get("/politica", response_model=PoliticaSalida, summary="Política de tratamiento de datos vigente")
def politica(config: Configuracion = Depends(configuracion)):
    return PoliticaSalida(version=config.version_politica, texto=texto_politica())


@router.get("/yo", response_model=UsuarioSalida, summary="Usuario actual (se crea en el primer ingreso)")
def yo(usuario: Usuario = Depends(usuario_actual), config: Configuracion = Depends(configuracion)):
    return _usuario(usuario, config)


@router.post("/yo/autorizacion", response_model=UsuarioSalida, summary="Aceptar la política de datos")
def autorizar(
    entrada: AutorizacionEntrada,
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
    config: Configuracion = Depends(configuracion),
):
    if entrada.version != config.version_politica:
        raise HTTPException(
            422,
            detail={"codigo": "version_politica", "detalle": f"La versión vigente es {config.version_politica}."},
        )
    cuenta.registrar_autorizacion(sesion, usuario, entrada.version)
    sesion.commit()
    return _usuario(usuario, config)


@router.get("/yo/datos", summary="Descargar todos mis datos (derecho a conocer)")
def mis_datos(usuario: Usuario = Depends(usuario_actual), sesion: Session = Depends(obtener_sesion)) -> dict:
    return cuenta.exportar_datos(sesion, usuario)


@router.delete("/yo", summary="Eliminar mi cuenta y todos mis datos (derecho de supresión)")
def eliminar_cuenta(
    confirmar: bool = Query(False, description="Debe ser true. La eliminación no se puede deshacer."),
    usuario: Usuario = Depends(usuario_actual),
    sesion: Session = Depends(obtener_sesion),
) -> dict:
    if not confirmar:
        raise HTTPException(422, detail={"codigo": "confirmacion_requerida", "detalle": "Envíe confirmar=true."})
    borrados = cuenta.eliminar_usuario(sesion, usuario)
    sesion.commit()
    return {"eliminado": True, "registros": borrados}
