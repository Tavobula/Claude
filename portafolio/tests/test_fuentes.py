import io
import json
from datetime import date
from decimal import Decimal as D

import pytest

from portafolio.sources import archivo
from portafolio.sources.base import ErrorFuente, transporte_urllib
from portafolio.sources.catalogo import IPC, TRM, UVR, conector_trm
from portafolio.sources.socrata import ConectorSocrata


class TransporteFalso:
    """Devuelve páginas predefinidas y guarda las consultas."""

    def __init__(self, *paginas):
        self.paginas = list(paginas)
        self.llamadas = []

    def __call__(self, url, parametros, encabezados):
        self.llamadas.append((url, dict(parametros), dict(encabezados)))
        return json.dumps(self.paginas.pop(0)).encode()


# ------------------------------------------------------------------ Socrata


def test_socrata_pagina_y_ordena():
    t = TransporteFalso(
        [{"fecha": "2025-01-01T00:00:00.000", "valor": "376.1"}, {"fecha": "2025-01-02T00:00:00.000", "valor": "376.2"}],
        [{"fecha": "2025-01-03T00:00:00.000", "valor": "376.3"}],
    )
    c = ConectorSocrata(UVR, "abcd-1234", "fecha", "valor", transporte=t, tamano_pagina=2)
    obs = c.descargar(date(2025, 1, 1), date(2025, 1, 3))
    assert [(o.fecha, o.valor) for o in obs] == [
        (date(2025, 1, 1), D("376.1")),
        (date(2025, 1, 2), D("376.2")),
        (date(2025, 1, 3), D("376.3")),
    ]
    assert [ll[1]["$offset"] for ll in t.llamadas] == ["0", "2"]
    url, parametros, _ = t.llamadas[0]
    assert url == "https://www.datos.gov.co/resource/abcd-1234.json"
    assert parametros["$where"] == "fecha <= '2025-01-03T23:59:59' AND fecha >= '2025-01-01T00:00:00'"
    assert parametros["$order"] == "fecha ASC"


def test_socrata_vigencias_se_expanden_por_dia():
    # La TRM del viernes rige hasta el lunes.
    t = TransporteFalso(
        [
            {"vigenciadesde": "2025-01-03T00:00:00.000", "vigenciahasta": "2025-01-06T00:00:00.000", "valor": "4300"},
            {"vigenciadesde": "2025-01-07T00:00:00.000", "vigenciahasta": "2025-01-07T00:00:00.000", "valor": "4310.5"},
        ]
    )
    obs = conector_trm(t).descargar(date(2025, 1, 4), date(2025, 1, 7))
    assert [(o.fecha.day, o.valor) for o in obs] == [(4, D("4300")), (5, D("4300")), (6, D("4300")), (7, D("4310.5"))]
    _, parametros, _ = t.llamadas[0]
    assert "32sa-8pi3" in t.llamadas[0][0]
    assert parametros["$where"] == (
        "vigenciadesde <= '2025-01-07T23:59:59' AND vigenciahasta >= '2025-01-04T00:00:00'"
    )


def test_socrata_filtros_escapan_comillas(monkeypatch):
    monkeypatch.setenv("PORTAFOLIO_SOCRATA_TOKEN", "secreto")
    t = TransporteFalso([])
    ConectorSocrata(UVR, "abcd-1234", "fecha", "valor", filtros={"nombre_fondo": "O'Brien"}, transporte=t).descargar(
        date(2025, 1, 1), date(2025, 1, 2)
    )
    _, parametros, encabezados = t.llamadas[0]
    assert parametros["$where"].endswith("nombre_fondo = 'O''Brien'")
    assert encabezados == {"X-App-Token": "secreto"}


@pytest.mark.parametrize(
    "argumentos",
    [
        {"dataset": "../etc"},
        {"campo_fecha": "fecha; drop"},
        {"filtros": {"a OR 1=1 --": "x"}},
    ],
)
def test_socrata_rechaza_identificadores_invalidos(argumentos):
    base = dict(definicion=UVR, dataset="abcd-1234", campo_fecha="fecha", campo_valor="valor")
    with pytest.raises(ValueError):
        ConectorSocrata(**{**base, **argumentos})


@pytest.mark.parametrize(
    "respuesta",
    [{"error": True, "message": "limite"}, [{"fecha": "2025-01-01"}], [{"fecha": "ayer", "valor": "1"}]],
    ids=["objeto", "sin_valor", "fecha_invalida"],
)
def test_socrata_respuestas_inesperadas(respuesta):
    c = ConectorSocrata(UVR, "abcd-1234", "fecha", "valor", transporte=TransporteFalso(respuesta))
    with pytest.raises(ErrorFuente):
        c.descargar(date(2025, 1, 1), date(2025, 1, 2))


def test_transporte_sin_conexion():
    with pytest.raises(ErrorFuente, match="No se pudo conectar"):
        transporte_urllib("http://127.0.0.1:9/nada", {}, {}, timeout=2)


# ------------------------------------------------------------------ archivos

BANREP_CSV = """Unidad de Valor Real (UVR);;
Serie histórica diaria;;
;;
Fecha (dd/mm/aaaa);Valor UVR;
01/01/2025;376,1234;
02/01/2025;376,2345;
;;
03/01/2025;n.d.;
Fuente: Banco de la República;;
"""


def test_csv_estilo_banrep():
    obs = archivo.leer_csv(
        io.StringIO(BANREP_CSV), columna_fecha="Fecha (dd/mm/aaaa)", columna_valor="valor uvr", decimal=","
    )
    assert [(o.fecha, o.valor) for o in obs] == [
        (date(2025, 1, 1), D("376.1234")),
        (date(2025, 1, 2), D("376.2345")),
    ]


def test_csv_mensual_con_miles_y_escala():
    texto = "mes,tasa\n2024-03,\"1,234.5\"\n04/2024,12.5\n"
    obs = archivo.leer_csv(io.StringIO(texto), columna_fecha="mes", columna_valor="tasa", escala=D("0.01"))
    assert [(o.fecha, o.valor) for o in obs] == [(date(2024, 3, 1), D("12.345")), (date(2024, 4, 1), D("0.125"))]


def test_csv_formato_de_fecha_explicito():
    texto = "fecha,valor\n2025.01.05,1\n"
    obs = archivo.leer_csv(io.StringIO(texto), columna_fecha="fecha", columna_valor="valor", formato_fecha="%Y.%m.%d")
    assert obs[0].fecha == date(2025, 1, 5)


def test_csv_errores():
    with pytest.raises(archivo.ErrorLectura, match="encabezado"):
        archivo.leer_csv(io.StringIO("a,b\n1,2\n"), columna_fecha="fecha", columna_valor="valor")
    texto = "fecha,valor\n2025-01-01,1\n31/02/2025,2\n2025-01-03,abc\n"
    with pytest.raises(archivo.ErrorLectura) as error:
        archivo.leer_csv(io.StringIO(texto), columna_fecha="fecha", columna_valor="valor")
    assert [e.split(":")[0] for e in error.value.errores] == ["Fila 3", "Fila 4"]


def test_excel(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from datetime import datetime

    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(["Índice de precios al consumidor"])
    hoja.append([])
    hoja.append(["Mes", "Índice"])
    hoja.append([datetime(2024, 1, 1), 137.72])
    hoja.append([datetime(2024, 2, 1), 139.19])
    ruta = tmp_path / "ipc.xlsx"
    libro.save(ruta)

    obs = archivo.leer_excel(ruta, columna_fecha="mes", columna_valor="índice")
    assert [(o.fecha, o.valor) for o in obs] == [(date(2024, 1, 1), D("137.72")), (date(2024, 2, 1), D("139.19"))]


def test_catalogo():
    assert IPC.frecuencia.value == "MENSUAL"
    assert TRM.frecuencia.value == "DIARIA"
