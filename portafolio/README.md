# Portafolio

Seguimiento y cálculo de rendimientos de inversiones en Colombia (CDT, FIC,
acciones, ETF). Se construye para un usuario, pero la arquitectura ya contempla
varios.

> Herramienta de seguimiento y cálculo. No es asesoría de inversión.

## Capas

```
src/portafolio/
├── core/        # cálculos puros: xirr, dietz, twr, cdt, impuestos, calendario (luego inflacion)
├── data/        # modelos SQLAlchemy, tipos, conexión, repositorios
├── services/    # casos de uso: rendimientos, cdt, impuestos, parametros, csv_io
├── sources/     # conectores Banrep, DANE, Superfinanciera (fase posterior)
├── api/         # FastAPI (fase multiusuario)
└── ui/          # Streamlit
migrations/      # Alembic
datos/           # parametros_ejemplo.csv
tests/           # incluye casos/xirr_excel.csv, validados contra Excel
```

Reglas:

- `core` no importa nada de `data`, `services` ni `ui`. Recibe flujos y fechas, devuelve números.
- `ui` (y luego `api`) solo llama a `services`. Nunca ejecuta SQL.

## Decisiones de diseño

| Decisión | Dónde |
|---|---|
| Toda tabla personal lleva `usuario_id` y `portafolio_id`. Una llave foránea compuesta contra `portafolio(id, usuario_id)` impide que no coincidan. | `data/modelos.py` |
| Datos globales (`Serie`, `ValorSerie`, `Parametro`) separados de los personales. | `data/modelos.py` |
| Montos en `Decimal`. `DecimalExacto` es `NUMERIC` en PostgreSQL y texto en SQLite, y rechaza `float`. | `data/tipos.py` |
| Enums como `VARCHAR` (`native_enum=False`), así que agregar un tipo no requiere migración en PostgreSQL. | `data/modelos.py` |
| Nombres de restricciones deterministas y de menos de 63 caracteres (el límite de PostgreSQL). | `data/modelos.py` |
| Hora de Bogotá y días hábiles colombianos con la librería `holidays`. | `core/calendario.py` |
| Parámetros normativos con `vigente_desde`: el pasado se recalcula con la tarifa de su momento. | `Parametro`, `repositorios.parametro_vigente` |
| Importación y exportación de movimientos y valoraciones en CSV. | `services/csv_io.py` |

## Instalación

```bash
cd portafolio
pip install -e ".[dev]"
alembic upgrade head          # crea portafolio.db (SQLite)
pytest
```

Para usar PostgreSQL basta con cambiar la URL:

```bash
export PORTAFOLIO_DB_URL=postgresql+psycopg://usuario:clave@host/portafolio
alembic upgrade head
```

Después de cambiar los modelos, genere una migración nueva:

```bash
alembic revision --autogenerate -m "descripcion"
```

`tests/test_migraciones.py` falla si las migraciones y los modelos no coinciden.

## Convenciones de datos

**Movimientos.** El `monto` siempre es positivo y el signo lo da el `tipo`:

| Tipo | TIR del portafolio | TIR del instrumento |
|---|---|---|
| `APORTE` | − | − |
| `RETIRO` | + | + |
| `COMPRA` | (interno) | − |
| `VENTA`, `DIVIDENDO`, `INTERES` | (interno) | + |
| `IMPUESTO`, `COMISION` | (interno) | − |

**Valor final.** El valor del portafolio al corte es la suma de la última
valoración de cada instrumento, incluidas las cuentas de efectivo
(`TipoInstrumento.CUENTA`). Si un instrumento tiene un movimiento posterior a
su última valoración, el cálculo se detiene con `ValoracionFaltanteError`.
Para un instrumento ya liquidado, registre una valoración de 0.

**CSV.** Use UTF-8, fechas ISO (`2024-03-15`) y punto decimal sin separador de
miles (`1250000.50`). Se rechazan las filas con columnas de más, que es lo que
pasa cuando llega un `1.234,56`. El archivo se valida completo y solo se guarda
si no tiene errores.

```csv
fecha,instrumento,tipo,monto,nota
2024-01-02,,APORTE,10000000,Aporte inicial
2024-01-02,CDT Banco A,COMPRA,10000000,
```

## XIRR

`core.xirr.xirr` sigue la convención de `TIR.NO.PER` de Excel: días reales
sobre 365, con la fecha más antigua como base. Usa Newton-Raphson y, si no
converge, bisección. Los casos de `tests/casos/xirr_excel.csv` se comparan
con una tolerancia de 1e-8, que es la precisión con la que Excel detiene la
iteración. Para agregar un caso, calcúlelo en Excel y añada las filas.

## TWR y Dietz modificado

Hay tres medidas de rendimiento, y responden preguntas distintas:

| Medida | Pregunta | Función |
|---|---|---|
| TIR (XIRR) | ¿Cuánto gané yo, dado cuándo metí y saqué plata? | `tir_portafolio`, `tir_instrumento` |
| TWR | ¿Qué tan bien le fue a la inversión, sin importar mis aportes? Es la que se compara contra un índice. | `twr_portafolio`, `twr_instrumento` |
| Dietz modificado | Aproximación de la TIR en un periodo cuando solo hay valor inicial y final. | `dietz_portafolio`, `dietz_instrumento` |

Convenciones:

- Una valoración es el valor **al cierre del día** e incluye los flujos de ese día.
  Un flujo el día de inicio ya está en el valor inicial; uno el día final pesa 0.
- En `core.dietz` y `core.twr` el signo se ve desde el activo (aporte = +),
  al revés que en `xirr` (aporte = −). Los servicios hacen la conversión.
- El TWR corta el periodo en cada fecha con alguna valoración y mide cada
  tramo con Dietz. **Es exacto si hay valoración en cada fecha de aporte o
  retiro**; si no, el tramo con el flujo se aproxima y `exacto` queda en
  `False`.
- Una fecha de corte se omite (y aparece en `fechas_omitidas`) si ese día algún
  instrumento tuvo movimientos después de su última valoración. Un instrumento
  sin movimientos conserva su última valoración.
- Los intereses y dividendos pagados salen del instrumento: en el TWR del
  instrumento cuentan como rendimiento, netos de la retención (`IMPUESTO`).
- `anualizado` solo se calcula para periodos de 365 días o más (criterio GIPS).

## CDT, retención y GMF

### Parámetros

Ninguna tarifa está en el código. Cárguelas en la tabla `parametro`:

```python
from portafolio.services.csv_io import importar_parametros
with open("datos/parametros_ejemplo.csv", encoding="utf-8") as f:
    importar_parametros(sesion, f)
```

`datos/parametros_ejemplo.csv` trae **valores de ejemplo que debe verificar**.
Si falta un parámetro obligatorio, el cálculo se detiene con
`ParametroNoDefinidoError` en lugar de suponer una tarifa.

| Parámetro | Uso | Obligatorio |
|---|---|---|
| `retencion_rendimientos_cdt` | Tarifa de retención sobre intereses de CDT | Sí, para CDT |
| `componente_inflacionario` | Fracción del interés no gravada (personas naturales no obligadas a llevar contabilidad) | No (0) |
| `base_dias` | 365 o 360, si el CDT no lo especifica | No (365) |
| `gmf_tarifa` | 0.004 | Sí, para GMF |
| `uvt`, `gmf_tope_exento_uvt` | Tope mensual exento de la cuenta marcada | Si la cuenta es exenta |

### CDT

Registre el instrumento (`tipo=CDT`) y sus condiciones en `CondicionCDT`:
capital, emisión, vencimiento, tasa (fracción), tipo de tasa (E.A. o nominal),
periodicidad de pago y modalidad. Luego:

- `proyectar_cdt`: todos los pagos, con retención e interés neto.
- `estado_cdt`: capital e interés causado a una fecha, y la retención que se
  practicaría si se pagara ese día.
- `sincronizar_cdt`: registra la COMPRA, cada INTERES con su IMPUESTO
  (retención) y la VENTA del capital, más valoraciones en la emisión, en cada
  pago, en cada fin de mes y en la fecha de corte. Se puede correr las veces
  que quiera: no duplica movimientos (`clave_generacion`) ni reemplaza
  valoraciones que usted haya registrado.

Con eso, `tir_instrumento` y `twr_instrumento` ya dan el rendimiento neto de
retención del CDT.

Convenciones (verifíquelas contra su extracto):

- Una tasa nominal se convierte a E.A. según la periodicidad (N.M.V. → 12
  periodos). Una tasa anticipada se convierte a su equivalente vencida.
- El interés de un periodo es `capital × ((1 + EA)^(días/base) − 1)`, con
  días calendario reales.
- Los periodos se cuentan desde la emisión. Si el vencimiento no coincide con
  un periodo completo, el último es más corto.
- Un pago que cae en fin de semana o festivo se hace el siguiente día hábil,
  **sin intereses por los días de espera**.
- Aún no se proyectan CDT con intereses anticipados ni de tasa variable
  (IBR, IPC + puntos); la tasa variable llega con los conectores de la fase 4.

### GMF

`gmf_cuenta` calcula el 4 × 1.000 de los RETIRO de una cuenta. Si la cuenta
está marcada `exenta_gmf`, los primeros `gmf_tope_exento_uvt × uvt` pesos de
cada mes están exentos, y la exención se consume en orden cronológico. El GMF
de las transferencias para comprar un instrumento no se estima, porque el
modelo no registra de qué cuenta sale ese dinero.

## Fases

1. Esqueleto, modelo de datos y XIRR ✔
2. TWR y Dietz modificado ✔
3. Causación de CDT, retención y GMF ✔
4. Deflactación con UVR/IPC y conectores (Banrep, DANE, Superfinanciera)
5. Atribución de rendimientos e interfaz Streamlit
6. Multiusuario: API FastAPI, autenticación, PostgreSQL, despliegue, política
   de tratamiento de datos (Ley 1581 de 2012)
