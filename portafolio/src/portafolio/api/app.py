"""Aplicación FastAPI.

    python -m portafolio api            # o
    uvicorn --factory portafolio.api.app:crear_app
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from portafolio.api import errores, rutas_cuenta, rutas_globales, rutas_portafolios
from portafolio.api.auth import Verificador, crear_verificador
from portafolio.api.config import Configuracion
from portafolio.data.db import crear_motor, fabrica_sesiones

DESCRIPCION = """
API de seguimiento de portafolios de inversión en Colombia.

**Herramienta de seguimiento y cálculo. No es asesoría de inversión.**

* Autenticación: `Authorization: Bearer <token>` de su proveedor de identidad.
* Antes de usar los datos financieros, acepte la política de tratamiento de
  datos: `GET /v1/politica` y `POST /v1/yo/autorizacion`.
* Montos y tasas viajan como texto (`"1500000.50"`); las tasas son fracciones
  (`"0.105"` = 10,5 %). Los rendimientos se devuelven como fracción.
"""


def crear_app(config: Configuracion | None = None, verificador: Verificador | None = None) -> FastAPI:
    config = config or Configuracion.desde_entorno()
    app = FastAPI(title="Portafolio API", version="0.1.0", description=DESCRIPCION)
    motor = crear_motor(config.url_base_datos, pool_pre_ping=True)
    app.state.config = config
    app.state.motor = motor
    app.state.fabrica = fabrica_sesiones(motor)
    app.state.verificador = verificador or crear_verificador(config)

    if config.origenes_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.origenes_cors),
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def encabezados_seguridad(request: Request, llamar_siguiente):
        respuesta = await llamar_siguiente(request)
        # Datos financieros: que no queden en cachés intermedias ni del navegador.
        respuesta.headers.setdefault("Cache-Control", "no-store")
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("Referrer-Policy", "no-referrer")
        return respuesta

    @app.get("/salud", tags=["sistema"], summary="Estado del servicio y de la base de datos")
    def salud() -> dict:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        return {"estado": "ok", "entorno": config.entorno}

    errores.registrar_manejadores(app)
    app.include_router(rutas_cuenta.router)
    app.include_router(rutas_portafolios.router)
    app.include_router(rutas_globales.router)
    return app
