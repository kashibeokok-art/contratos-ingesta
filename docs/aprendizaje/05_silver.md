# 05 — Silver (`silver.py`)

**Problema:** el Excel tiene 180 columnas, 2 filas de encabezado, una celda con varios puntos y
fechas en dos formatos. Para responder "¿qué contratos vencen?" hace falta una tabla limpia.

**Con la pieza:** tres funciones, en orden.

| Función | Entra | Sale |
|---|---|---|
| `leer_excel` | el Excel de Bronze | la hoja `contratos` con el encabezado real (2.a fila) |
| `transformar` | esa tabla + la fecha de los datos | `contratos`, `contrato_barra` y un conteo para revisar |
| `marcar_fecha_ingreso` | `contratos` + las fechas de corridas anteriores | `fecha_ingreso` de cada contrato |
| `escribir` | todo lo anterior | `contratos.parquet`, `contrato_barra.parquet`, `_control.json` |

**`fecha_ingreso`:** se guarda en `_control.json` (`{id: fecha}`) y nunca se pisa: si un
contrato cambia, su fecha de ingreso sigue siendo la primera. En la **primera carga** todos
quedan con la fecha de esa carga (2026-10-15): la base empieza ese día.

**Primera corrida real (2026-10-15, en `18. Contratos CEN\silver`):**

| Dato | Valor |
|---|---|
| contratos | 11.237 (6.978 vigentes, 4.259 no vigentes) |
| puntos | 14.328 (40 con forma desconocida, conservados) |
| sin energía (quedan en 0, RN-09) | 1.549 |
| años aislados excluidos (RN-07) | 58 |
| vigencia calculada ≠ "Estado Contrato" | 2 |
| tiempo | 45 s en la primera corrida (medido después, 2026-10-16: leer el Excel 2,8 s y transformar 2,7 s; el resto no se midió, probablemente el primer acceso a la red) |

**Frase:** Silver deja el Excel en dos tablas limpias, con reglas probadas, sin repetir la
energía del contrato en cada barra y sin perder la fecha en que cada contrato llegó.
