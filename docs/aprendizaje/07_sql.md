# 07 — Subir a PostgreSQL (`sql/esquema_contratos.sql`, `publicar.py`)

**Problema:** la API (más adelante) leerá los contratos desde la base `cmg_cen`. Cada carga tiene
que reemplazar los datos sin que nadie vea nunca una tabla vacía o a medias.

**El esquema** (lo corrió el usuario una vez): esquema `contratos` dentro de `cmg_cen`, con
`contrato`, `contrato_barra` y `carga`. Escribe `contratos_carga` (no puede tocar `cmg`); lee
`cmg_lectura`.

**La carga**, en una sola transacción:

```
validar Silver (IDs no vacíos ni repetidos, puntos con contrato)  ← si falla, no se toca la base
BEGIN
  DELETE contrato_barra ; DELETE contrato
  COPY contrato ; COPY contrato_barra
  INSERT carga (fecha de los datos, archivo de origen, huella, filas)
COMMIT                                                            ← recién aquí se ve lo nuevo
```

| Situación | Qué pasa |
|---|---|
| Silver no cambió desde la última carga (misma huella) | no se sube nada |
| `--forzar` | se sube igual |
| algo falla a la mitad (red, un dato que viola una regla de la tabla) | ROLLBACK: la base queda exactamente como estaba |
| alguien consulta durante la carga | ve los datos viejos hasta el COMMIT (DELETE, no TRUNCATE: no lo bloquea) |

**Configuración** (`.env`), la clave aparte para no tener que codificar `;` o `)`:

```
CONT_PG_CONEXION=host=192.168.0.85 port=5433 dbname=cmg_cen user=contratos_carga
CONT_PG_CLAVE=la-clave-de-contratos_carga
```

```powershell
uv run contratos publicar-sql
uv run contratos publicar-sql --forzar
uv run contratos actualizar      # ahora también publica si hay CONT_PG_CONEXION
```

**Vista `contratos.contrato_hoy` (mejora 8.1):** recalcula `vigente` y `dias_para_vencer` con el
día de Chile en cada consulta; la API debe leer la vista, no la tabla.

**Medido (copia local, 2026-10-15):** 11.237 contratos + 14.328 puntos en 2,7 s.

**Frase:** la base se reemplaza entera o no se toca; nunca queda a medias.
