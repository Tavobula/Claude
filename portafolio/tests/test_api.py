"""API: autenticación, autorización de datos, aislamiento entre usuarios y flujo completo.

Corre contra SQLite o, con PORTAFOLIO_TEST_DB_URL, contra PostgreSQL.
"""

import time
from datetime import date

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from conftest import URL_PRUEBAS
from portafolio.api.app import crear_app
from portafolio.api.auth import VerificadorLocal, VerificadorOIDC, TokenInvalidoError
from portafolio.api.config import Configuracion, ConfiguracionInvalidaError
from portafolio.data.db import crear_motor, fabrica_sesiones
from portafolio.data.modelos import Base
from portafolio.services import cuenta

SECRETO = "s" * 40
VERSION = "2026-09"


@pytest.fixture
def url(tmp_path):
    url = URL_PRUEBAS if URL_PRUEBAS.startswith("postgresql") else f"sqlite:///{tmp_path / 'api.db'}"
    motor = crear_motor(url)
    Base.metadata.drop_all(motor)
    Base.metadata.create_all(motor)
    yield url
    Base.metadata.drop_all(motor)
    motor.dispose()


@pytest.fixture
def app(url):
    app = crear_app(Configuracion(url, secreto_local=SECRETO, version_politica=VERSION))
    yield app
    app.state.motor.dispose()


@pytest.fixture
def cliente(app):
    return TestClient(app)


def token(sujeto, email=None, **extra):
    return VerificadorLocal(SECRETO).emitir(sujeto, email or f"{sujeto}@example.com", sujeto.capitalize(), **extra)


def cab(sujeto, email=None):
    return {"Authorization": f"Bearer {token(sujeto, email)}"}


def autorizado(cliente, sujeto):
    h = cab(sujeto)
    r = cliente.post("/v1/yo/autorizacion", json={"version": VERSION, "acepto": True}, headers=h)
    assert r.status_code == 200, r.text
    return h


# ------------------------------------------------------------------ sistema y configuración


def test_salud_y_politica(cliente):
    assert cliente.get("/salud").json()["estado"] == "ok"
    r = cliente.get("/v1/politica")
    assert r.json()["version"] == VERSION
    assert "Ley 1581" in r.json()["texto"]
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "argumentos,mensaje",
    [
        ({"secreto_local": "corto"}, "32 caracteres"),
        ({"entorno": "produccion", "secreto_local": SECRETO}, "oidc"),
        ({"entorno": "produccion", "modo_auth": "oidc", "oidc_emisor": "https://x", "oidc_audiencia": "a"}, "PostgreSQL"),
        ({"modo_auth": "oidc"}, "OIDC_EMISOR"),
    ],
)
def test_configuracion_invalida(argumentos, mensaje):
    with pytest.raises(ConfiguracionInvalidaError, match=mensaje):
        Configuracion("sqlite://", **argumentos)


# ------------------------------------------------------------------ autenticación


def test_sin_token_o_token_invalido(cliente):
    assert cliente.get("/v1/yo").status_code == 401
    assert cliente.get("/v1/yo", headers={"Authorization": "Bearer basura"}).status_code == 401
    vencido = VerificadorLocal(SECRETO).emitir("ana", horas=-1)
    r = cliente.get("/v1/yo", headers={"Authorization": f"Bearer {vencido}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"]["detalle"].lower()
    otro_secreto = VerificadorLocal("x" * 40).emitir("ana")
    assert cliente.get("/v1/yo", headers={"Authorization": f"Bearer {otro_secreto}"}).status_code == 401
    sin_firma = jwt.encode({"iss": "portafolio-local", "aud": "portafolio-api", "sub": "ana", "iat": 0, "exp": 2**31}, None, algorithm="none")
    assert cliente.get("/v1/yo", headers={"Authorization": f"Bearer {sin_firma}"}).status_code == 401
    assert cliente.get("/v1/yo").headers["www-authenticate"] == "Bearer"


def test_verificador_oidc_con_llaves_rsa():
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verificador = VerificadorOIDC("https://id.ejemplo.com/", "api-portafolio", resolver_llave=lambda _t: llave.public_key())
    ahora = int(time.time())
    claims = {"iss": "https://id.ejemplo.com/", "aud": "api-portafolio", "sub": "u-1", "iat": ahora, "exp": ahora + 60,
              "email": "u@example.com", "email_verified": True}
    identidad = verificador.verificar(jwt.encode(claims, llave, algorithm="RS256"))
    assert (identidad.emisor, identidad.sujeto, identidad.email_verificado) == ("https://id.ejemplo.com/", "u-1", True)
    for malo in (
        jwt.encode(claims, otra, algorithm="RS256"),  # firmado por otra llave
        jwt.encode({**claims, "iss": "https://falso/"}, llave, algorithm="RS256"),
        jwt.encode({**claims, "aud": "otra-api"}, llave, algorithm="RS256"),
        jwt.encode({k: v for k, v in claims.items() if k != "exp"}, llave, algorithm="RS256"),
        jwt.encode(claims, "secreto-simetrico-de-32-caracteres!!", algorithm="HS256"),  # confusión de algoritmo
    ):
        with pytest.raises(TokenInvalidoError):
            verificador.verificar(malo)


# ------------------------------------------------------------------ autorización de datos


def test_primer_ingreso_y_autorizacion(cliente):
    h = cab("ana")
    yo = cliente.get("/v1/yo", headers=h).json()
    assert (yo["email"], yo["autorizacion_vigente"], yo["es_administrador"]) == ("ana@example.com", False, False)

    r = cliente.get("/v1/portafolios", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "autorizacion_requerida"
    assert cliente.post("/v1/yo/autorizacion", json={"version": "2020-01", "acepto": True}, headers=h).status_code == 422
    assert cliente.post("/v1/yo/autorizacion", json={"version": VERSION, "acepto": False}, headers=h).status_code == 422

    r = cliente.post("/v1/yo/autorizacion", json={"version": VERSION, "acepto": True}, headers=h)
    assert r.json()["autorizacion_vigente"] is True and r.json()["autorizacion_datos_en"]
    assert cliente.get("/v1/portafolios", headers=h).json() == []


def test_nueva_version_de_politica_pide_aceptar_de_nuevo(url, cliente):
    autorizado(cliente, "ana")
    app2 = crear_app(Configuracion(url, secreto_local=SECRETO, version_politica="2027-01"))
    r = TestClient(app2).get("/v1/portafolios", headers=cab("ana"))
    assert r.status_code == 403 and r.json()["detail"]["version"] == "2027-01"
    app2.state.motor.dispose()


def test_correo_existente_no_se_vincula_solo(url, cliente):
    """Un token con el correo de un usuario existente no toma su cuenta."""
    with fabrica_sesiones(crear_motor(url))() as s:
        from portafolio.services import registro

        registro.crear_usuario(s, "Ana personal", "ana@example.com")
        s.commit()
    r = cliente.get("/v1/yo", headers=cab("otro-sujeto", "ana@example.com"))
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "conflicto_identidad"


def test_correo_no_verificado_no_se_usa(cliente):
    t = jwt.encode(
        {"iss": "portafolio-local", "aud": "portafolio-api", "sub": "x1", "iat": int(time.time()), "exp": int(time.time()) + 60,
         "email": "victima@example.com", "email_verified": False},
        SECRETO, algorithm="HS256",
    )
    yo = cliente.get("/v1/yo", headers={"Authorization": f"Bearer {t}"}).json()
    assert yo["email"] != "victima@example.com" and yo["email"].endswith(".invalid")


# ------------------------------------------------------------------ aislamiento entre usuarios


def test_un_usuario_no_ve_ni_toca_lo_de_otro(cliente):
    ana, beto = autorizado(cliente, "ana"), autorizado(cliente, "beto")
    p_ana = cliente.post("/v1/portafolios", json={"nombre": "Retiro"}, headers=ana).json()["id"]
    i_ana = cliente.post(f"/v1/portafolios/{p_ana}/instrumentos", json={"nombre": "FIC", "tipo": "FIC"}, headers=ana).json()["id"]
    m_ana = cliente.post(
        f"/v1/portafolios/{p_ana}/movimientos",
        json={"fecha": "2025-01-02", "tipo": "APORTE", "monto": "1000", "instrumento_id": i_ana},
        headers=ana,
    ).json()["id"]
    p_beto = cliente.post("/v1/portafolios", json={"nombre": "Retiro"}, headers=beto).json()["id"]

    assert cliente.get("/v1/portafolios", headers=beto).json() == [{"id": p_beto, "nombre": "Retiro", "descripcion": None}]
    for ruta in (
        f"/v1/portafolios/{p_ana}",
        f"/v1/portafolios/{p_ana}/movimientos",
        f"/v1/portafolios/{p_ana}/resumen",
        f"/v1/portafolios/{p_ana}/movimientos.csv",
        f"/v1/portafolios/{p_ana}/instrumentos/{i_ana}/cdt/pagos",
        f"/v1/portafolios/{p_beto}/instrumentos/{i_ana}/cdt/pagos",  # instrumento ajeno bajo portafolio propio
    ):
        r = cliente.get(ruta, headers=beto)
        assert r.status_code == 404, ruta
    assert cliente.delete(f"/v1/portafolios/{p_ana}/movimientos/{m_ana}", headers=beto).status_code == 404
    assert cliente.delete(f"/v1/portafolios/{p_beto}/movimientos/{m_ana}", headers=beto).status_code == 404
    # Usar el instrumento de Ana dentro del portafolio de Beto.
    r = cliente.post(
        f"/v1/portafolios/{p_beto}/movimientos",
        json={"fecha": "2025-01-02", "tipo": "COMPRA", "monto": "1", "instrumento_id": i_ana},
        headers=beto,
    )
    assert r.status_code == 422 and "no pertenece" in r.json()["detail"]["detalle"]
    assert len(cliente.get(f"/v1/portafolios/{p_ana}/movimientos", headers=ana).json()) == 1


# ------------------------------------------------------------------ montos


def test_montos_como_texto(cliente):
    h = autorizado(cliente, "ana")
    p = cliente.post("/v1/portafolios", json={"nombre": "P"}, headers=h).json()["id"]
    base = {"fecha": "2025-01-02", "tipo": "APORTE"}
    r = cliente.post(f"/v1/portafolios/{p}/movimientos", json={**base, "monto": 1500000.5}, headers=h)
    assert r.status_code == 422 and "como texto" in r.text
    r = cliente.post(f"/v1/portafolios/{p}/movimientos", json={**base, "monto": "12345678901234.123456"}, headers=h)
    assert r.status_code == 201 and r.json()["monto"] == "12345678901234.123456"
    r = cliente.post(f"/v1/portafolios/{p}/movimientos", json={**base, "monto": "1.1234567"}, headers=h)
    assert r.status_code == 422 and "6 decimales" in r.json()["detail"]["detalle"]
    assert cliente.post(f"/v1/portafolios/{p}/movimientos", json={**base, "monto": 1000}, headers=h).json()["monto"] == "1000"


# ------------------------------------------------------------------ flujo completo


def test_flujo_completo(url, cliente):
    h = autorizado(cliente, "ana")
    admin = autorizado(cliente, "admin")
    with fabrica_sesiones(crear_motor(url))() as s:
        cuenta.definir_administrador(s, "admin@example.com")
        s.commit()

    # Los datos globales solo los carga un administrador.
    parametros = ("parametros.csv", "nombre,vigente_desde,valor\nretencion_rendimientos_cdt,2000-01-01,0.04\n", "text/csv")
    assert cliente.post("/v1/parametros/importar", files={"archivo": parametros}, headers=h).status_code == 403
    assert cliente.post("/v1/parametros/importar", files={"archivo": parametros}, headers=admin).json() == {"registros": 1}
    uvr = "fecha,valor\n" + "".join(f"{date.fromordinal(date(2025, 1, 1).toordinal() + i)},{300 + i / 100}\n" for i in range(400))
    r = cliente.post("/v1/series/UVR/importar", files={"archivo": ("uvr.csv", uvr, "text/csv")}, headers=admin)
    assert r.json()["nuevas"] == 400
    assert [s["codigo"] for s in cliente.get("/v1/series", headers=h).json()] == ["UVR"]

    p = cliente.post("/v1/portafolios", json={"nombre": "Retiro"}, headers=h).json()["id"]
    cuenta_id = cliente.post(f"/v1/portafolios/{p}/instrumentos", json={"nombre": "Cuenta", "tipo": "CUENTA"}, headers=h).json()["id"]
    cdt_id = cliente.post(f"/v1/portafolios/{p}/instrumentos", json={"nombre": "CDT", "tipo": "CDT"}, headers=h).json()["id"]
    cliente.post(f"/v1/portafolios/{p}/movimientos", json={"fecha": "2025-03-03", "tipo": "APORTE", "monto": "10000000", "instrumento_id": cuenta_id}, headers=h)
    cliente.post(f"/v1/portafolios/{p}/valoraciones", json={"instrumento_id": cuenta_id, "fecha": "2025-03-03", "valor": "0"}, headers=h)
    r = cliente.put(
        f"/v1/portafolios/{p}/instrumentos/{cdt_id}/cdt",
        json={"capital": "10000000", "fecha_emision": "2025-03-03", "fecha_vencimiento": "2026-03-03", "tasa": "0.10"},
        headers=h,
    )
    assert r.status_code == 204, r.text
    pagos = cliente.get(f"/v1/portafolios/{p}/instrumentos/{cdt_id}/cdt/pagos", headers=h).json()
    # Los intereses y la retención vienen redondeados a centavos, como en una liquidación.
    assert pagos == [{"corte": "2026-03-03", "fecha_pago": "2026-03-03", "dias": 365, "interes": "1000000.00",
                      "retencion": "40000.00", "capital": "10000000", "total_recibido": "10960000.00"}]
    r = cliente.post(f"/v1/portafolios/{p}/instrumentos/{cdt_id}/cdt/sincronizar", params={"hasta": "2025-12-31"}, headers=h)
    assert r.json() == {"movimientos_creados": 1, "valoraciones_creadas": 11}
    cliente.post(f"/v1/portafolios/{p}/valoraciones", json={"instrumento_id": cuenta_id, "fecha": "2025-12-31", "valor": "0"}, headers=h)

    resumen = cliente.get(f"/v1/portafolios/{p}/resumen", params={"fecha": "2025-12-31"}, headers=h).json()
    assert resumen["aportes_netos"] == "10000000" and resumen["avisos"] == []
    assert resumen["tir"] == pytest.approx(0.10, abs=1e-4)
    rend = cliente.get(f"/v1/portafolios/{p}/rendimientos", params={"desde": "2025-03-03", "hasta": "2025-12-31"}, headers=h).json()
    assert rend["twr"]["exacto"] and rend["twr"]["inflacion"] is not None and rend["tir"]["tasa_real"] is not None
    atrib = cliente.get(f"/v1/portafolios/{p}/atribucion", params={"desde": "2025-03-03", "hasta": "2025-12-31"}, headers=h).json()
    assert sum(parte["contribucion"] for parte in atrib["partes"]) == pytest.approx(atrib["rendimiento"])
    assert cliente.get(f"/v1/portafolios/{p}/evolucion", params={"desde": "2025-03-03", "hasta": "2025-12-31"}, headers=h).status_code == 200

    # Algo que no se puede calcular responde 409 con el motivo.
    r = cliente.get(f"/v1/portafolios/{p}/atribucion", params={"desde": "2025-12-31", "hasta": "2025-12-31"}, headers=h)
    assert r.status_code == 422
    r = cliente.get(f"/v1/portafolios/{p}/instrumentos/{cuenta_id}/cdt/pagos", headers=h)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "no_calculable"


def test_csv_por_api(cliente):
    h = autorizado(cliente, "ana")
    p = cliente.post("/v1/portafolios", json={"nombre": "P"}, headers=h).json()["id"]
    csv = "fecha,instrumento,tipo,monto,nota\n2025-01-02,,APORTE,1000,Inicial\n"
    assert cliente.post(f"/v1/portafolios/{p}/movimientos/importar", files={"archivo": ("m.csv", csv, "text/csv")}, headers=h).json() == {"registros": 1}
    assert cliente.get(f"/v1/portafolios/{p}/movimientos.csv", headers=h).text == csv
    r = cliente.post(f"/v1/portafolios/{p}/movimientos/importar", files={"archivo": ("m.csv", "fecha,tipo\nx,y\n", "text/csv")}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "archivo_invalido"
    grande = "fecha,instrumento,tipo,monto\n" + "2025-01-02,,APORTE,1\n" * 300_000
    r = cliente.post(f"/v1/portafolios/{p}/movimientos/importar", files={"archivo": ("m.csv", grande, "text/csv")}, headers=h)
    assert r.status_code == 413


# ------------------------------------------------------------------ derechos del titular


def test_exportar_y_eliminar_cuenta(url, cliente):
    h, beto = autorizado(cliente, "ana"), autorizado(cliente, "beto")
    p = cliente.post("/v1/portafolios", json={"nombre": "Retiro"}, headers=h).json()["id"]
    cliente.post(f"/v1/portafolios/{p}/movimientos", json={"fecha": "2025-01-02", "tipo": "APORTE", "monto": "1000.5"}, headers=h)
    cliente.post("/v1/portafolios", json={"nombre": "De Beto"}, headers=beto)

    datos = cliente.get("/v1/yo/datos", headers=h).json()
    assert datos["usuario"]["email"] == "ana@example.com"
    assert [m["monto"] for m in datos["movimiento"]] == ["1000.5"]
    assert [x["nombre"] for x in datos["portafolio"]] == ["Retiro"]  # nada de Beto

    assert cliente.delete("/v1/yo", headers=h).status_code == 422  # falta confirmar
    r = cliente.delete("/v1/yo", params={"confirmar": True}, headers=h)
    assert r.json()["registros"]["movimiento"] == 1 and r.json()["registros"]["usuario"] == 1
    # Los datos de Beto siguen intactos.
    assert [x["nombre"] for x in cliente.get("/v1/portafolios", headers=beto).json()] == ["De Beto"]
    # Con el mismo token, Ana vuelve como usuario nuevo y sin datos.
    yo = cliente.get("/v1/yo", headers=h).json()
    assert yo["autorizacion_vigente"] is False
