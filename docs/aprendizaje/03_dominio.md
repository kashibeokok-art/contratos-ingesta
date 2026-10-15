# 03 — Dominio puro (`dominio/fechas.py`, `energia.py`, `puntos.py`)

"Puro" = recibe valores y devuelve valores: no lee archivos ni la red. Por eso se prueba con
casos escritos a mano, en milisegundos.

## Fechas

**Problema:** `Fecha Término Renovación` viene como texto `05-03-2027`.

| Texto | pandas adivinando | `leer_fecha` |
|---|---|---|
| `30-09-2026` | 30-sep (no hay mes 30) | 30-sep |
| `05-03-2027` | **3-may** ❌ | 5-mar |
| `31-02-2027` | error o NaT | `None` (no existe: no se inventa) |

Vigencia: término efectivo = el mayor entre Término y Término de renovación; vigente si es hoy o después.

## Energía

**Problema:** un contrato trae MWh en 2026, 2027 y uno suelto en 2040.

| Paso | Resultado |
|---|---|
| años con dato | 2026 (1.400), 2027 (2.000), 2040 (9.999) |
| aislados (RN-07) | 2040: su vecino está a 13 años |
| máximo en GWh (RN-05/08) | **2,0** (sin 2040 habría sido 10,0) |
| sin ningún dato (RN-09) | 0 |

## Puntos

**Problema:** `BA S/E SAN JOAQUIN (CGE) 13.2KV C2;NULO` es una celda con dos "puntos".

| Texto | subestación | propietario | kV | sección |
|---|---|---|---|---|
| `CHACAHUIN 13` | CHACAHUIN | — | 13 | — |
| `BA S/E SAN JOAQUIN (CGE) 13.2KV C2` | SAN JOAQUIN | CGE | 13,2 | C2 |
| `NULO` | (no es un punto) | | | |
| `BA TAP OFF MAURO 220KV BP1` | el texto completo, `reconocido = False` | | | |

**Frase:** las reglas de negocio viven en funciones chicas y puras, probadas con los casos
reales del Excel, antes de tocar un solo archivo.
