"""Línea de comandos: ``python -m portafolio ...``.

Ejemplos:
    python -m portafolio series importar UVR uvr.csv --col-fecha Fecha --col-valor Valor --decimal ,
    python -m portafolio series importar IPC ipc.xlsx --col-fecha Mes --col-valor Indice
    python -m portafolio series importar FIC:renta-fija fic.csv --nombre "FIC Renta Fija" ...
    python -m portafolio series actualizar TRM --desde 2024-01-01
    python -m portafolio series listar
    python -m portafolio parametros importar datos/parametros_ejemplo.csv
    python -m portafolio --db sqlite:///demo.db demo
    python -m portafolio api --puerto 8000
    python -m portafolio token --sujeto ana --email ana@example.com     # solo modo local
    python -m portafolio usuarios admin ana@example.com
    python -m portafolio usuarios vincular ana@example.com --emisor https://... --sujeto auth0|123
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.exc import OperationalError, ProgrammingError

from portafolio.api.config import ConfiguracionInvalidaError
from portafolio.core.calendario import hoy_bogota
from portafolio.data.db import crear_motor, fabrica_sesiones
from portafolio.sources import archivo, catalogo
from portafolio.sources.base import DefinicionSerie, ErrorFuente
from portafolio.services import csv_io, cuenta, demo, series


def _definicion(codigo: str, nombre: str | None) -> DefinicionSerie:
    if codigo in catalogo.DEFINICIONES:
        return catalogo.DEFINICIONES[codigo]
    if codigo.startswith("FIC:"):
        return catalogo.definicion_fic(codigo, nombre or codigo)
    conocidos = ", ".join(catalogo.DEFINICIONES)
    raise SystemExit(f"Serie desconocida {codigo!r}. Use una de: {conocidos}, o FIC:<nombre>.")


def _importar(args, sesion) -> str:
    definicion = _definicion(args.codigo, args.nombre)
    opciones = dict(
        columna_fecha=args.col_fecha,
        columna_valor=args.col_valor,
        decimal=args.decimal,
        formato_fecha=args.formato_fecha,
        escala=Decimal(args.escala),
    )
    ruta = Path(args.archivo)
    resumen = series.importar_archivo(
        sesion, definicion, ruta.read_bytes(), ruta.name, codificacion=args.codificacion, hoja=args.hoja, **opciones
    )
    return _resumen(resumen)


def _actualizar(args, sesion) -> str:
    fabrica = catalogo.CONECTORES.get(args.codigo)
    if fabrica is None:
        raise SystemExit(
            f"{args.codigo} no tiene conector automático ({', '.join(catalogo.CONECTORES)}). "
            "Descargue el archivo de la fuente y use 'series importar'."
        )
    ultima = series.ultima_fecha(sesion, args.codigo)
    desde = args.desde or (ultima - timedelta(days=7) if ultima else date(2000, 1, 1))
    return _resumen(series.actualizar_desde_fuente(sesion, fabrica(), desde, args.hasta or hoy_bogota()))


def _listar(_args, sesion) -> str:
    lineas = [
        f"{s.codigo:<20} {s.frecuencia:<8} último dato: {s.ultima or '-'}  {s.nombre}"
        for s in series.listar_series(sesion)
    ]
    return "\n".join(lineas) or "No hay series cargadas."


def _parametros(args, sesion) -> str:
    with open(args.archivo, encoding="utf-8") as f:
        return f"{csv_io.importar_parametros(sesion, f)} parámetros cargados."


def _demo(_args, sesion) -> str:
    portafolio = demo.crear_demo(sesion)
    return f"Portafolio '{portafolio.nombre}' creado con datos ficticios."


def _api(args, _sesion) -> str:
    import uvicorn

    uvicorn.run("portafolio.api.app:crear_app", factory=True, host=args.host, port=args.puerto, proxy_headers=True)
    return "API detenida."


def _token(args, _sesion) -> str:
    from portafolio.api.auth import VerificadorLocal
    from portafolio.api.config import Configuracion

    config = Configuracion.desde_entorno()
    if config.modo_auth != "local":
        raise ValueError("Los tokens locales solo existen en modo local (PORTAFOLIO_AUTH_MODO=local).")
    return VerificadorLocal(config.secreto_local).emitir(args.sujeto, args.email, args.nombre, args.horas)


def _usuarios_listar(_args, sesion) -> str:
    from portafolio.services import consultas

    lineas = [
        f"{u.id:>4}  {u.email:<40} {'admin' if u.es_administrador else '     '}  "
        f"{'autorizó ' + u.version_politica if u.version_politica else 'sin autorización'}  "
        f"{u.emisor or '(modo personal)'}"
        for u in consultas.usuarios(sesion)
    ]
    return "\n".join(lineas) or "No hay usuarios."


def _usuarios_admin(args, sesion) -> str:
    try:
        usuario = cuenta.definir_administrador(sesion, args.email, not args.quitar)
    except LookupError as error:
        raise ValueError(str(error)) from None
    return f"{usuario.email}: {'es' if usuario.es_administrador else 'ya no es'} administrador."


def _usuarios_vincular(args, sesion) -> str:
    try:
        usuario = cuenta.vincular_identidad(sesion, args.email, args.emisor, args.sujeto)
    except (LookupError, cuenta.ConflictoIdentidadError) as error:
        raise ValueError(str(error)) from None
    return f"{usuario.email} ahora ingresa como {args.sujeto} de {args.emisor}."


def _resumen(r: series.ResumenCarga) -> str:
    rango = f" ({r.desde} a {r.hasta})" if r.desde else ""
    return f"{r.codigo}: {r.nuevas} nuevos, {r.actualizadas} corregidos, {r.sin_cambio} sin cambio{rango}."


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portafolio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="URL de la base (por defecto PORTAFOLIO_DB_URL)")
    grupos = parser.add_subparsers(dest="grupo", required=True)

    s = grupos.add_parser("series", help="Series globales: UVR, IPC, IBR, TRM, FIC").add_subparsers(dest="accion", required=True)
    imp = s.add_parser("importar", help="Carga una serie desde CSV o Excel")
    imp.add_argument("codigo")
    imp.add_argument("archivo")
    imp.add_argument("--col-fecha", default="fecha")
    imp.add_argument("--col-valor", default="valor")
    imp.add_argument("--decimal", default=".", choices=[".", ","])
    imp.add_argument("--formato-fecha", help="p. ej. %%d/%%m/%%Y; por defecto se detecta")
    imp.add_argument("--escala", default="1", help="multiplica cada valor; 0.01 para pasar de %% a fracción")
    imp.add_argument("--hoja", help="hoja de Excel (por defecto la activa)")
    imp.add_argument("--nombre", help="nombre de la serie, para FIC")
    imp.add_argument("--codificacion", default="utf-8-sig", help="p. ej. latin-1 para archivos de Excel en Windows")
    imp.set_defaults(funcion=_importar)

    act = s.add_parser("actualizar", help="Descarga desde la fuente (solo series con conector)")
    act.add_argument("codigo")
    act.add_argument("--desde", type=date.fromisoformat)
    act.add_argument("--hasta", type=date.fromisoformat)
    act.set_defaults(funcion=_actualizar)

    s.add_parser("listar", help="Series cargadas y su último dato").set_defaults(funcion=_listar)

    p = grupos.add_parser("parametros", help="Parámetros normativos").add_subparsers(dest="accion", required=True)
    pimp = p.add_parser("importar", help="Carga parámetros desde CSV")
    pimp.add_argument("archivo")
    pimp.set_defaults(funcion=_parametros)
    grupos.add_parser("demo", help="Crea datos ficticios en una base vacía").set_defaults(funcion=_demo)

    api = grupos.add_parser("api", help="Inicia la API (configuración en variables PORTAFOLIO_*)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--puerto", type=int, default=8000)
    api.set_defaults(funcion=_api)

    token = grupos.add_parser("token", help="Emite un token de desarrollo (solo modo local)")
    token.add_argument("--sujeto", required=True)
    token.add_argument("--email")
    token.add_argument("--nombre")
    token.add_argument("--horas", type=float, default=8)
    token.set_defaults(funcion=_token)

    u = grupos.add_parser("usuarios", help="Usuarios de la API").add_subparsers(dest="accion", required=True)
    u.add_parser("listar").set_defaults(funcion=_usuarios_listar)
    adm = u.add_parser("admin", help="Da (o quita con --quitar) el rol de administrador")
    adm.add_argument("email")
    adm.add_argument("--quitar", action="store_true")
    adm.set_defaults(funcion=_usuarios_admin)
    vin = u.add_parser("vincular", help="Asocia un usuario existente a su identidad del proveedor de ingreso")
    vin.add_argument("email")
    vin.add_argument("--emisor", required=True, help="claim iss del proveedor")
    vin.add_argument("--sujeto", required=True, help="claim sub del usuario en el proveedor")
    vin.set_defaults(funcion=_usuarios_vincular)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    motor = crear_motor(args.db)
    try:
        with fabrica_sesiones(motor)() as sesion:
            mensaje = args.funcion(args, sesion)
            sesion.commit()
    except (
        archivo.ErrorLectura,
        csv_io.ErrorImportacion,
        ErrorFuente,
        ValueError,
        demo.BaseNoVaciaError,
        ConfiguracionInvalidaError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (OperationalError, ProgrammingError) as error:
        print(f"Error de base de datos: {error.orig}\n¿Ya corrió 'alembic upgrade head'?", file=sys.stderr)
        return 1
    finally:
        motor.dispose()
    print(mensaje)
    return 0
