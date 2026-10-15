# 04 — Bronze (`bronze.py`)

**Problema:** cada día se descarga el Excel de contratos. Si se guarda una copia diaria, en un
año hay 365 archivos casi siempre iguales; si no se guarda nada (como `OLD/`), no se puede
volver atrás ni auditar.

**Con la pieza:** se descarga, se calcula su huella (sha256) y **solo se guarda si cambió**.

| Situación | Qué pasa |
|---|---|
| primera descarga | `Contratos_publica_AAAAMMDD_HHMMSS.xlsx` + entrada en `manifiesto.json` |
| el Excel es idéntico al último | no se guarda otra copia; se usa el último |
| el Excel cambió | se guarda una copia nueva (la anterior se conserva) |
| la API responde 503/429 o falla la red | reintenta 3 veces con espera creciente |
| la API responde 403 | se detiene: un bloqueo no se arregla esperando |
| llega una página HTML en vez de un Excel | se detiene y no guarda nada |
| la API cambia la forma de su respuesta | se detiene con un mensaje claro (el legado fallaría en silencio) |

Cada archivo se escribe primero como `.part` y después se renombra: si se corta, nunca queda un
Excel a medias con el nombre bueno.

**Dato medido (2026-10-15):** la API informa `age_minutes = 3253`, o sea, su Excel tenía ~2,3 días.
El CEN no lo regenera a diario: varios días seguidos darán "sin cambios", y es lo esperado.

**Frase:** Bronze guarda cada versión distinta de la fuente, tal cual llegó, y nada repetido.
