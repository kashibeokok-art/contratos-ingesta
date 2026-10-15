# 02 — Configuración (`config.py` y `rutas.py`)

**Problema:** Bronze y Silver pueden estar en tu equipo o en la red, y la ruta la eliges tú.
El código no puede tener rutas escritas a mano.

**Sin la pieza:** `CARPETA = r"C:\Users\...\bronze"` dentro del código; cambiar de equipo es
editar el programa.

**Con la pieza:** el `.env` (copia de `.env.example`):
```
CONT_BRONZE_DIR=\\SAFIRA_CL1\...\contratos\bronze
CONT_SILVER_DIR=\\SAFIRA_CL1\...\contratos\silver
```

| Lo que escribes en `.env` | Lo que pasa |
|---|---|
| nada | Bronze y Silver quedan en `contratos-ingesta\data\` |
| `CONT_SILVER_DIR=` una carpeta que existe | se usa esa |
| `CONT_SILVER_DIR=` una carpeta que NO existe | se detiene y dice qué revisar; **no la crea** (A17) |
| `CONT_SILVR_DIR=...` (mal escrito) | se detiene al arrancar y lista las variables válidas (A17) |
| `CONT_DATA_DIR=data` (relativa) | es `contratos-ingesta\data`, aunque ejecutes desde `C:\` (A10) |
| `SQL_SERVIDOR=...` (sin `CONT_`) | se ignora: no es del programa |

**Frase:** las rutas se eligen fuera del código, y una ruta mala detiene el programa en vez de
crear carpetas equivocadas.
