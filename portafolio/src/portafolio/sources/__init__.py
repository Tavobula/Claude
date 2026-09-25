"""Conectores a fuentes externas de datos globales.

Cada conector devuelve observaciones ``(fecha, valor)`` de una serie; el
servicio ``services.series`` las guarda en ``Serie``/``ValorSerie``. Los
conectores nunca tocan datos personales.

* ``socrata``: API de datos abiertos (www.datos.gov.co).
* ``archivo``: CSV o Excel descargados a mano de Banrep, DANE o Superfinanciera.
* ``catalogo``: definiciones de las series conocidas (UVR, IPC, IBR, TRM).
"""
