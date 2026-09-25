"""Series conocidas y sus conectores.

Solo la TRM tiene un conector automático configurado; los identificadores de
los demás conjuntos de datos abiertos cambian con frecuencia, así que UVR,
IPC, IBR y los valores de unidad de los FIC se cargan desde archivo
(``python -m portafolio series importar ...``) o con un ``ConectorSocrata``
configurado con el conjunto y los campos correctos.

Nota: los conectores no se pudieron probar contra la fuente real desde el
entorno donde se escribieron; verifique el conjunto y los campos en
www.datos.gov.co antes de confiar en ellos.
"""

from __future__ import annotations

from portafolio.core.inflacion import Frecuencia
from portafolio.data.modelos import TipoSerie
from portafolio.sources.base import DefinicionSerie, Transporte
from portafolio.sources.socrata import ConectorSocrata

UVR = DefinicionSerie(
    "UVR", "Unidad de valor real", TipoSerie.INDICADOR, Frecuencia.DIARIA, "Banco de la República", "COP"
)
IPC = DefinicionSerie(
    "IPC",
    "Índice de precios al consumidor (base dic-2018 = 100)",
    TipoSerie.INDICADOR,
    Frecuencia.MENSUAL,
    "DANE",
    "índice",
)
IBR_ON = DefinicionSerie(
    "IBR_ON", "IBR overnight (nominal, fracción)", TipoSerie.INDICADOR, Frecuencia.DIARIA, "Banco de la República", "tasa"
)
IBR_1M = DefinicionSerie(
    "IBR_1M", "IBR a un mes (nominal, fracción)", TipoSerie.INDICADOR, Frecuencia.DIARIA, "Banco de la República", "tasa"
)
IBR_3M = DefinicionSerie(
    "IBR_3M", "IBR a tres meses (nominal, fracción)", TipoSerie.INDICADOR, Frecuencia.DIARIA, "Banco de la República", "tasa"
)
TRM = DefinicionSerie(
    "TRM",
    "Tasa representativa del mercado",
    TipoSerie.INDICADOR,
    Frecuencia.DIARIA,
    "Superfinanciera (datos.gov.co)",
    "COP/USD",
)

DEFINICIONES: dict[str, DefinicionSerie] = {d.codigo: d for d in (UVR, IPC, IBR_ON, IBR_1M, IBR_3M, TRM)}


def definicion_fic(codigo: str, nombre: str) -> DefinicionSerie:
    """Valor de unidad de un FIC. Use un código estable, p. ej. ``FIC:<nit o nombre corto>``."""
    return DefinicionSerie(codigo, nombre, TipoSerie.VALOR_UNIDAD, Frecuencia.DIARIA, "Superfinanciera", "COP")


def conector_trm(transporte: Transporte | None = None) -> ConectorSocrata:
    """TRM desde el conjunto 32sa-8pi3; cada fila es una vigencia desde-hasta."""
    return ConectorSocrata(
        TRM,
        "32sa-8pi3",
        campo_fecha="vigenciadesde",
        campo_valor="valor",
        campo_fecha_hasta="vigenciahasta",
        transporte=transporte,
    )


CONECTORES = {"TRM": conector_trm}
