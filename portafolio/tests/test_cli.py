import json
from pathlib import Path

import pytest

from portafolio.cli import main
from portafolio.data.db import crear_motor
from portafolio.data.modelos import Base
from portafolio.sources import catalogo

EJEMPLO = Path(__file__).resolve().parents[1] / "datos" / "parametros_ejemplo.csv"


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    motor = crear_motor(url)
    Base.metadata.create_all(motor)
    motor.dispose()
    return url


def test_importar_listar(db, tmp_path, capsys):
    archivo = tmp_path / "uvr.csv"
    archivo.write_text("Fecha;Valor\n01/01/2025;376,1\n02/01/2025;376,2\n", encoding="utf-8")
    assert main(["--db", db, "series", "importar", "UVR", str(archivo), "--col-fecha", "Fecha", "--col-valor", "Valor", "--decimal", ","]) == 0
    assert "UVR: 2 nuevos, 0 corregidos, 0 sin cambio (2025-01-01 a 2025-01-02)" in capsys.readouterr().out
    assert main(["--db", db, "series", "listar"]) == 0
    assert "último dato: 2025-01-02" in capsys.readouterr().out


def test_importar_fic(db, tmp_path, capsys):
    archivo = tmp_path / "fic.csv"
    archivo.write_text("fecha,valor\n2025-01-01,12345.678901\n", encoding="utf-8")
    assert main(["--db", db, "series", "importar", "FIC:renta-fija", str(archivo), "--nombre", "FIC Renta Fija"]) == 0
    main(["--db", db, "series", "listar"])
    assert "FIC Renta Fija" in capsys.readouterr().out


def test_errores(db, tmp_path, capsys):
    with pytest.raises(SystemExit, match="Serie desconocida"):
        main(["--db", db, "series", "importar", "XYZ", "x.csv"])
    with pytest.raises(SystemExit, match="no tiene conector"):
        main(["--db", db, "series", "actualizar", "UVR"])
    malo = tmp_path / "malo.csv"
    malo.write_text("fecha,valor\n2025-01-01,abc\n", encoding="utf-8")
    assert main(["--db", db, "series", "importar", "UVR", str(malo)]) == 1
    assert "Fila 2" in capsys.readouterr().err


def test_actualizar_trm(db, monkeypatch, capsys):
    def transporte(url, parametros, encabezados):
        return json.dumps(
            [{"vigenciadesde": "2025-01-02T00:00:00.000", "vigenciahasta": "2025-01-02T00:00:00.000", "valor": "4400"}]
        ).encode()

    monkeypatch.setitem(catalogo.CONECTORES, "TRM", lambda: catalogo.conector_trm(transporte))
    assert main(["--db", db, "series", "actualizar", "TRM", "--desde", "2025-01-01", "--hasta", "2025-01-03"]) == 0
    assert "TRM: 1 nuevos" in capsys.readouterr().out


def test_parametros(db, capsys):
    assert main(["--db", db, "parametros", "importar", str(EJEMPLO)]) == 0
    assert "6 parámetros cargados" in capsys.readouterr().out
