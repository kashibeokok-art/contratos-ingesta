# contratos-ingesta: cómo funciona, puntos débiles y mejoras

> Estado al 2026-10-16 (commit `2b785c1` + correcciones posteriores). Las cifras de este
> documento salen de corridas reales con su fecha; lo que no se midió se dice explícitamente.

---

## 1. En una frase

El programa baja el Excel público de contratos del Coordinador, lo guarda tal cual (Bronze), lo
convierte en dos tablas limpias (Silver) y las sube a PostgreSQL, sin que la base quede nunca a
medias.

```
                    contratos descargar          contratos procesar             contratos publicar-sql
API pública del CEN ───────────────────► Bronze ───────────────────► Silver ─────────────────────────► PostgreSQL
(Plataforma Mercado)   solo si cambió    .xlsx      reglas RN-05..09   .parquet   reemplazo en 1 transacción   cmg_cen.contratos
                                         + manifiesto  + fecha_ingreso  + _control.json                    + tabla carga
```

`contratos actualizar` hace los tres pasos en orden (el tercero solo si hay conexión en el `.env`).

---

## 2. Recorrido de una ejecución (`uv run contratos actualizar`)

| # | Qué pasa | Lee | Escribe | Si falla |
|---|---|---|---|---|
| 1 | Lee `.env` y valida la configuración | `.env`, variables `CONT_*` | — | sale con 1 y dice qué variable revisar |
| 2 | Pide a la API el enlace del Excel | API Gateway del CEN | — | reintenta 3 veces (red, 429, 5xx); un 403 no se reintenta |
| 3 | Baja el Excel y calcula su sha256 | enlace S3 | — | sale con 1 |
| 4 | Si es igual al último guardado, no lo guarda | `bronze/manifiesto.json` | — | — |
| 5 | Si cambió: `.part` → renombrar → manifiesto | — | `bronze/Contratos_publica_AAAAMMDD_HHMMSS.xlsx` | el `.part` queda a medio camino, nunca un `.xlsx` incompleto |
| 6 | Toma el **último Excel de Bronze** y su fecha (del nombre) | `bronze/` | — | sale con 1 |
| 7 | Lee la hoja `contratos` (encabezado en la 2.a fila) | el Excel | — | si falta una columna conocida: sale con 1 y la nombra |
| 8 | Aplica las reglas fila por fila | — | — | — |
| 9 | Agrega `fecha_ingreso` (la más antigua conocida) | `silver/_control.json` | — | — |
| 10 | Escribe las dos tablas (`.tmp` → renombrar) y el control | — | `silver/contratos.parquet`, `contrato_barra.parquet`, `_control.json` | los archivos anteriores quedan intactos hasta el renombre |
| 11 | Valida Silver (IDs, puntos huérfanos) | Silver | — | no toca la base, sale con 1 |
| 12 | Si Silver no cambió desde la última carga, no sube | `contratos.carga` | — | — |
| 13 | BEGIN → DELETE → COPY → INSERT carga → COMMIT | Silver | `cmg_cen.contratos.*` | ROLLBACK: la base queda exactamente como estaba |

Tiempos medidos: leer el Excel 2,8 s y transformar 2,7 s (2026-10-16); subir a una copia local de
PostgreSQL 2,7 s (2026-10-15). La primera corrida completa contra la red tardó 45 s; el desglose
de esa vez no se midió (error A23).

---

## 3. Mapa del código

| Archivo | Líneas | Responsabilidad |
|---|---:|---|
| `config.py` | 115 | Lee `.env` y variables `CONT_*`; ancla rutas al proyecto; detiene si algo está mal escrito |
| `rutas.py` | 39 | Dónde están Bronze y Silver; exige que las carpetas existan |
| `dominio/fechas.py` | 47 | Leer fechas con formato explícito; término efectivo; vigencia |
| `dominio/energia.py` | 74 | Números del Excel; años aislados; resumen de energía |
| `dominio/puntos.py` | 84 | Separar un punto de retiro/suministro en sus partes |
| `bronze.py` | 148 | API → Excel en Bronze, solo si cambió |
| `silver.py` | 240 | Excel → `contratos` + `contrato_barra` + `fecha_ingreso` |
| `publicar.py` | 142 | Silver → PostgreSQL en una transacción |
| `cli.py` | 171 | Comandos y códigos de salida |
| `sql/esquema_contratos.sql` | 118 | Esquema, tablas y permisos en `cmg_cen` (lo corre el administrador) |

Dependencias: `pydantic-settings` (configuración), `httpx` (HTTP), `pandas` + `openpyxl` (Excel),
`pyarrow` (Parquet), `psycopg` (PostgreSQL), `typer` (comandos).

Regla de diseño: **`dominio/` no lee ni escribe archivos**. Recibe valores y devuelve valores, por
eso se prueba con casos escritos a mano en milisegundos. Las piezas con archivos o red
(`bronze`, `silver.escribir`, `publicar`) usan esas funciones.

---

## 4. Cada pieza en detalle

### 4.1 Configuración (`config.py`, `rutas.py`)

**Problema:** las carpetas pueden estar en la red y las elige el usuario; el código no puede
tener rutas escritas a mano.

| Variable | Para qué | Si no está |
|---|---|---|
| `CONT_DATA_DIR` | carpeta local de trabajo | `contratos-ingesta\data` |
| `CONT_BRONZE_DIR` | dónde van los Excel | `data\bronze` |
| `CONT_SILVER_DIR` | dónde van las tablas | `data\silver` |
| `CONT_PG_CONEXION` | `host=... port=... dbname=cmg_cen user=contratos_carga` (sin clave) | `actualizar` no publica |
| `CONT_PG_CLAVE` | la clave, aparte (no hay que codificar `;` o `)`) | `publicar-sql` sale con 1 |

Protecciones:

| Situación | Qué hace | Por qué |
|---|---|---|
| ruta relativa (`data`) | se cuelga de la carpeta del proyecto | A10: ejecutar desde `C:\` no cambia la ruta |
| `CONT_SILVR_DIR` (mal escrita) | se detiene y lista las válidas | A17: no usar un valor por defecto en silencio |
| carpeta configurada que no existe | se detiene; **no la crea** | A17: una ruta mal escrita no termina en una carpeta nueva |
| ruta entre comillas dobles en `.env` | se detiene: "escribe las rutas SIN comillas" | caso real: el lector del `.env` convertía `\\SAFIRA` en `\SAFIRA` y `\b` en un carácter de control |
| `CONT_PG_CLAVE` | se guarda como `SecretStr` | no aparece si se imprime la configuración |

### 4.2 Reglas puras (`dominio/`)

**`fechas.leer_fecha(valor)`**. Prueba, en orden, `AAAA-MM-DD HH:MM:SS`, `AAAA-MM-DD`,
`DD-MM-AAAA`, `DD/MM/AAAA`; si ninguno calza devuelve vacío. Nunca deja adivinar a pandas: la
columna `Fecha Término Renovación` viene como texto `05-03-2027`, que pandas leía como **3 de mayo**
(error A21; un contrato cambiaba de vigencia).

**`fechas.termino_efectivo(termino, renovacion)`**: el mayor de los dos.
**`fechas.vigente(termino, dia)`**: término ≥ día. **`dias_para_vencer`**: término − día.

**`energia.resumir({año: MWh})`**:

| Paso | Ejemplo real de prueba |
|---|---|
| años con dato | 2026 (1.400), 2027 (2.000), 2040 (9.999) |
| años aislados (RN-07): el vecino con dato más cercano está a ≥ 2 años | 2040 |
| a GWh (RN-08) y máximo (RN-05) | **2,0 GWh** (con 2040 habría sido 10,0) |
| sin datos (RN-09) | 0 |

**`puntos.separar_punto(texto)`**: dos formas reconocidas (`CHACAHUIN 13` y
`BA S/E SAN JOAQUIN (CGE) 13.2KV C2` → subestación, propietario, kV, sección). El sufijo
`(AIS)`/`(GIS)` se descarta (decisión del usuario). `NULO` y vacío no son puntos. Lo que no calza
se conserva con el texto completo y `reconocido = false` (40 casos reales).

### 4.3 Bronze (`bronze.py`)

**Problema:** guardar cada versión de la fuente para poder reprocesar y auditar, sin acumular
copias idénticas.

- `enlace(respuesta)` acepta solo la forma actual de la API (`data.url`). La forma que esperaba
  `OLD/` (`data` como texto) se rechaza con un mensaje: si la API cambia, se nota.
- `pedir()` reintenta red caída, 429 y 5xx con espera creciente; un 403 no se reintenta.
- `descargar()` compara el sha256 con el último del manifiesto. Igual → no guarda. Distinto →
  `.part` + renombre + entrada en `manifiesto.json` (archivo, bytes, sha256, fecha, antigüedad
  que informa la API).
- Medido: la API informó `age_minutes = 3253` (~2,3 días): el CEN no regenera el Excel a diario.

### 4.4 Silver (`silver.py`)

**Problema:** un Excel de 180 columnas, 2 filas de encabezado y celdas con listas → dos tablas
limpias.

- `leer_excel()`: hoja `contratos`, encabezado de la 2.a fila, todo como texto.
- `transformar(tabla, dia)`: encuentra cada columna por nombre sin tildes ni mayúsculas (si falta
  una, se detiene y la nombra), y por cada fila arma un contrato y sus puntos. Devuelve también un
  **conteo** (vigentes, sin energía, años aislados, puntos no reconocidos, IDs repetidos, sin ID,
  estado distinto).
- `marcar_fecha_ingreso()`: `fecha_ingreso` = la fecha más antigua conocida para ese ID
  (guardada en `_control.json`), o la de esta carga si el contrato es nuevo.
- `escribir()`: los dos Parquet a `.tmp`, renombre, y al final el control.

Primera corrida real (2026-10-15): 11.237 contratos (6.978 vigentes), 14.328 puntos, 1.549 sin
energía, 58 años aislados excluidos, 2 con estado distinto.

### 4.5 PostgreSQL (`publicar.py`, `sql/esquema_contratos.sql`)

Esquema `contratos` en `cmg_cen`. Escribe `contratos_carga` (no puede tocar el esquema `cmg`); lee
`cmg_lectura`. Ambas cosas probadas en una copia local (intentos indebidos → "permission denied").

Carga: validar → si la huella sha256 de Silver es la misma de la última carga, no hacer nada →
`BEGIN; DELETE; COPY; COPY; INSERT carga; COMMIT`. Se usa DELETE y no TRUNCATE: quien consulta
mientras tanto ve los datos viejos hasta el COMMIT. Verificado: reprocesar el mismo Excel genera
Silver idéntico byte a byte (2026-10-16), así que la huella detecta "sin cambios" de verdad.

### 4.6 Comandos (`cli.py`)

| Comando | Hace |
|---|---|
| `actualizar` | descargar + procesar + publicar-sql (si hay conexión) |
| `descargar` | API → Bronze |
| `procesar [--archivo X]` | último Excel de Bronze (o X) → Silver |
| `publicar-sql [--forzar]` | Silver → PostgreSQL |
| `estado` | resumen de Bronze y Silver |

Códigos: 0 bien · 1 no se pudo · 2 comando mal escrito · 3 terminó con algo que revisar (IDs
repetidos, filas sin ID, Silver vacío en `estado`).

---

## 5. Diccionario de datos

### `contrato` (una fila por contrato; Silver y SQL tienen las mismas columnas)

| Columna | Tipo | Origen / regla |
|---|---|---|
| `id_contrato` | texto (PK) | `Id Contrato` (sin `.0`) |
| `suministrador`, `rut_suministrador`, `tipo_suministrador` | texto | columnas del mismo nombre |
| `tipo_contrato`, `red_distribuidora`, `tipo_cliente` | texto | ídem |
| `cliente`, `rut_cliente` | texto | `Empresa Cliente`, `Rut Empresa Cliente` |
| `estado_fuente` | texto | `Estado Contrato`, tal cual |
| `region`, `sector_economico`, `subsector_economico` | texto | ídem |
| `fecha_suscripcion`, `fecha_inicio`, `fecha_termino`, `fecha_termino_renovacion` | fecha | formatos explícitos (A21) |
| `fecha_termino_efectiva` | fecha | el mayor entre término y término de renovación |
| `vigente` | sí/no | término efectivo ≥ `fecha_calculo` (**manda la fecha**) |
| `estado_distinto` | sí/no | `estado_fuente` no coincide con `vigente` |
| `dias_para_vencer` | entero | término efectivo − `fecha_calculo` |
| `energia_max_anual_gwh` | número | RN-05/07/08/09: **la energía del contrato** |
| `energia_promedio_anual_gwh`, `energia_min_anual_gwh` | número | mismas reglas |
| `anios_energia`, `anios_aislados` | texto | años usados y excluidos, separados por coma |
| `potencia_max_anual_mw` | número | máximo de `Potencia AAAA` |
| `fecha_datos` | fecha | fecha del Excel de Bronze (de su nombre): de qué versión salió la fila |
| `fecha_calculo` | fecha | día contra el que se calcularon `vigente` y `dias_para_vencer` (el de `procesar`) |
| `fecha_ingreso` | fecha | primer día en que el contrato entró a la base |

No se guardan: `Correo Cliente`, `Dirección Comercial` (datos personales), `Afecto Ley`, `Régimen
Compra Potencia`, listados de potencia conectada, número de cliente, distribuidora conectada.

### `contrato_barra` (una fila por punto)

| Columna | Regla |
|---|---|
| `id_contrato` | FK a `contrato` |
| `tipo_punto` | `retiro` o `suministro` |
| `orden` | posición en la lista del Excel (1, 2, ...) |
| `texto` | el punto tal como venía |
| `subestacion`, `propietario`, `tension_kv`, `seccion` | partes reconocidas |
| `reconocido` | false = forma desconocida (texto completo en `subestacion`) |

### `contrato_hoy` (vista, solo SQL)

Las mismas columnas de `contrato`, pero `vigente`, `estado_distinto`, `dias_para_vencer` y
`fecha_calculo` se recalculan con el día de Chile en cada consulta. **Es la que debe leer la API.**

### `carga` (solo SQL)

Una fila por carga: `fecha_datos`, `archivo_origen`, `sha256_silver`, filas y `cargado_en`.

---

## 6. Qué garantiza hoy

| Garantía | Cómo | Probado con |
|---|---|---|
| Bronze no guarda copias idénticas | sha256 contra el último | test + API real |
| Ningún archivo queda a medias | `.part` / `.tmp` + renombre | por construcción; **no hay test que corte el proceso a la mitad** (mejora 8.10) |
| La base nunca queda a medias | una transacción; ROLLBACK si falla | test que inyecta un fallo a mitad del COPY |
| Silver malo no llega a la base | validación previa | tests (IDs repetidos, sin ID, huérfanos) |
| La lectura no puede escribir; la carga no toca `cmg` | permisos SQL | pruebas en copia local |
| Rutas y variables mal escritas se detienen | validadores de configuración | tests |
| Reprocesar da el mismo resultado | Silver determinista | huellas iguales (2026-10-16) |

Total: 83 tests + 6 de integración con PostgreSQL (`PRUEBA_PG_CONTRATOS`), `ruff` y `mypy --strict`.

---

## 7. Puntos débiles

Ordenados por impacto. Cada uno con el escenario concreto en que falla.

### 7.1 ✅ (resuelto 2026-10-16, mejora 8.1) La vigencia envejecía si el Excel no cambiaba

**Escenario:** el CEN no cambia el Excel durante 10 días. `descargar` dice "sin cambios" y no
guarda nada; `procesar` usa el **último Excel guardado** y su fecha (la de hace 10 días). Un
contrato que venció hace 5 días sigue con `vigente = sí` y `dias_para_vencer = 5`.
**Por qué pasa:** `vigente` y `dias_para_vencer` se calculan contra `fecha_datos` y se **guardan**;
`fecha_datos` sale del nombre del archivo (`cli.fecha_del_archivo`).
**Impacto:** la pregunta "¿qué contratos están por vencer?" responde con datos de días atrás.
**Arreglo aplicado (8.1):** Silver calcula `vigente` y `dias_para_vencer` contra el día en que se
procesa (`fecha_calculo`), y la vista SQL `contratos.contrato_hoy` los recalcula con la fecha de Chile
cada vez que se consulta. La API debe leer la vista. Probado: con un Silver calculado en 2020, la tabla
dice `vigente = sí` y la vista, `no`.

### 7.2 🟡 (en parte resuelto 2026-10-16, mejora 8.2) `fecha_ingreso` dependía de un solo archivo

**Escenario:** alguien borra o pisa `silver/_control.json`. En la siguiente corrida los 11.237
contratos quedan con `fecha_ingreso` = ese día.
**Además:** en la primera carga, todos quedaron con 2026-10-15 (la base empezó ese día): no es la
fecha real en que el CEN publicó cada contrato.
**Arreglo aplicado (8.2):** si el control falta o está dañado, `procesar` lo reconstruye desde
Bronze (el Excel más antiguo donde aparece cada ID; ~2,1 s por Excel) y lo avisa. **Sigue
vigente:** la primera carga deja a todos con la fecha de inicio de la base; `fecha_suscripcion` es
la referencia de antigüedad real.

### 7.3 🟠 Sin historia de los contratos

**Escenario:** el CEN modifica la energía de un contrato o lo quita del Excel. Silver y SQL se
reemplazan completos: el valor anterior (o el contrato que desapareció) ya no está. Solo queda el
Excel viejo en Bronze, que habría que reprocesar a mano.
**Impacto:** no se puede responder "¿cómo cambió este contrato?" ni "¿qué contratos desaparecieron?".

### 7.4 🟠 Los puntos no están unidos a las barras del CMg

`contrato_barra` tiene subestación y kV, pero no la barra canónica del CMg (`A.BLANCAS_____013`).
Unirlos es la homologación (H7): los nombres no coinciden siempre ("SAN JOAQUIN (CGE)",
abreviaturas, 13,2 kV vs 013) y requiere revisión humana. Hasta entonces, cruzar contratos con
retiros o CMg por barra no es confiable.

### 7.5 🟡 La tarea diaria no avisa si falla

Si `actualizar` falla en la madrugada (API caída, red, clave vencida), el código de salida es 1,
pero nadie lo ve: no hay archivo de log, ni correo, ni alerta. Y la tarea programada de Windows
todavía no existe.

### 7.6 🟡 Dependencia de una API no documentada

La API Gateway del CEN no es una API publicada con contrato: el CEN la usa en su sitio. Ya cambió
una vez (la forma de `data`, que rompió a `OLD/`). El programa se detiene con un mensaje claro si
cambia, pero no se adapta solo.

### 7.7 🟡 La clave está en texto plano en el `.env`

`SecretStr` evita que se imprima, pero el archivo `.env` la tiene legible para cualquiera con
acceso a la carpeta del proyecto. (Además, la clave de `postgres` apareció en el chat el
2026-10-15: se recomendó cambiarla.)

### 7.8 🟡 Reglas que dependen de la forma del Excel

- La fecha de los datos se deduce del **nombre** del archivo de Bronze; `procesar --archivo` con
  un Excel de otro nombre se detiene (código 1, no 2).
- `numero("1,400")` = 1,4: la coma se toma como decimal. Hoy el Excel real no trae ningún valor
  con coma (0 casos, verificado 2026-10-16); si el CEN empezara a usar coma de miles, la energía
  quedaría 1.000 veces menor sin error.
- La regla de años aislados (RN-07) se aplica a la energía, no a la potencia.
- `orden` en `contrato_barra` es la posición en la lista: si el CEN reordena los puntos de un
  contrato, cambian las filas aunque los puntos sean los mismos.

### 7.9 🔵 Detalles menores

- Dos `procesar` al mismo tiempo podrían pisarse `_control.json` (uso de un solo usuario: bajo riesgo).
- La consola de Windows (página de códigos 850) muestra mal las tildes de los mensajes; los datos
  están bien (UTF-8).
- `actualizar` reprocesa Silver aunque el Excel no haya cambiado (~6 s; inofensivo, la huella evita
  la subida).
- No hay integración continua (CI): los tests corren solo a mano.

---

## 8. Mejoras propuestas

| # | Mejora | Resuelve | Esfuerzo |
|---|---|---|---|
| 8.1 ✅ | Calcular `vigente` y `dias_para_vencer` **contra la fecha de hoy al consultar**: una vista SQL `contratos.contrato_hoy` con `current_date`, y en Silver guardar solo `fecha_termino_efectiva`. Alternativa mínima: que `procesar` use la fecha del día, no la del archivo | 7.1 | bajo |
| 8.2 ✅ | Guardar `fecha_ingreso` también en SQL y reconstruirla desde Bronze si falta el control (el Excel más antiguo donde aparece cada ID); `fecha_suscripcion` como referencia de antigüedad real | 7.2 | bajo |
| 8.3 | Tabla de historial en SQL (`contrato_historial`: una fila por contrato y versión, solo cuando algo cambia) y una lista de contratos que desaparecieron | 7.3 | medio |
| 8.4 | Homologación de puntos a barras CMg con tabla de equivalencias editable y revisión humana (como `domain/barras.py` de `cmg-ingesta`) | 7.4 | alto |
| 8.5 | Tarea programada diaria + log a archivo + alerta (correo o archivo en `data/alertas/`) cuando el código de salida no sea 0 | 7.5 | bajo |
| 8.6 | Guardar la clave en el Administrador de credenciales de Windows o en `pgpass.conf` en vez del `.env` | 7.7 | bajo |
| 8.7 | Contrato de datos del Excel: lista de columnas esperadas y aviso si aparecen columnas nuevas o cambian de forma (como `quality/deriva.py` de `cmg-ingesta`) | 7.6, 7.8 | medio |
| 8.8 | GitHub Actions con `ruff`, `mypy` y `pytest` en cada push | 7.9 | bajo |
| 8.9 | La API de descarga sobre `cmg_lectura` (ADR-C04) | objetivo pendiente | medio |
| 8.10 | Tests que simulen un corte entre escribir `.tmp` y renombrar (en Bronze y Silver), como `cmg-ingesta` B9 | garantía de la sección 6 | bajo |

**Orden sugerido:** ~~8.1~~, ~~8.2~~ (hechos) → 8.5 (que la operación diaria
avise) → 8.3 → el resto.

---

## 9. Cómo verificar que funciona

```powershell
uv run ruff check . ; uv run mypy ; uv run pytest           # 83 tests
$env:PRUEBA_PG_CONTRATOS = "host=localhost port=55433 user=postgres"
uv run pytest tests/test_publicar.py                        # 6 tests contra un PostgreSQL de prueba
uv run contratos estado
```

Guías paso a paso: `docs/aprendizaje/01` a `07`. Decisiones: `CLAUDE.md` §3. Errores ya
cometidos (para no repetirlos): `docs/errores_verificados.md`.
