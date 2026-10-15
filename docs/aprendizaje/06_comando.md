# 06 — El comando `contratos` (`cli.py`)

**Problema:** las piezas existen (`bronze.py`, `silver.py`), pero usarlas exige escribir Python.
Una tarea programada necesita un comando, y saber si salió bien.

```powershell
uv run contratos actualizar     # descargar + procesar (tarea diaria)
uv run contratos descargar      # API -> Bronze, solo si el Excel cambió
uv run contratos procesar       # último Excel de Bronze -> Silver
uv run contratos procesar --archivo "ruta\Contratos_publica_20261015_165541.xlsx"
uv run contratos estado         # qué hay en Bronze y en Silver
$LASTEXITCODE                   # el código con que terminó el último comando
```

| Código | Significa | Ejemplo |
|---|---|---|
| 0 | terminó bien | `actualizar` normal (aunque haya cosas que mirar, como los 2 `estado_distinto`) |
| 1 | no se pudo | sin red, carpeta de red no encontrada, Bronze vacío |
| 2 | comando mal escrito | `--archivoo`, un `--archivo` que no existe |
| 3 | terminó, pero hay que revisar | IDs repetidos, filas sin ID, `estado` con Silver vacío |

**La fecha de los datos** sale del nombre que puso Bronze (`Contratos_publica_AAAAMMDD_...`):
reprocesar un Excel viejo calcula la vigencia contra SU fecha, no contra hoy.

**Frase:** un comando por acción y un código de salida que una tarea programada puede leer.
