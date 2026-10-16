# CLAUDE.md — `contratos-ingesta`

> Memoria del proyecto. Claude lo lee al iniciar cada sesión.

## ⚠️ Antes de hacer nada

1. Leer [`docs/errores_verificados.md`](docs/errores_verificados.md). **Regla del usuario:** cuando
   Claude descubra que se equivocó, agrega la entrada ahí **antes de seguir**.
2. Seguir [`docs/receta_programa_datos.md`](docs/receta_programa_datos.md): un paso por vez, cada
   paso termina funcionando y probado antes del siguiente.
3. **Método (pedido del usuario, 2026-10-15):** pasos cortos y visibles. Al cerrar cada paso,
   Claude muestra qué hizo en pocas líneas y espera antes de seguir. No avanzar varios pasos
   seguidos sin que el usuario lo vea (en `ppa-pipeline` el usuario "perdió el hilo").

---

## 0. Origen

El 2026-10-15 el usuario separó `ppa-pipeline` en tres proyectos:

| Proyecto | Datos |
|---|---|
| **`contratos-ingesta`** (este) | contratos de suministro (Plataforma Mercado del CEN) |
| `retiros-ingesta` | retiros de energía (R, L, L_D) |
| `inyecciones-ingesta` | inyecciones (G) y contratos físicos y financieros (C_FIS, C_FIN) |

`ppa-pipeline` queda **congelado** como referencia (su §12 y sus `docs/` tienen lo investigado).

## 1. Alcance

### 1.1 La fuente (verificado el 2026-10-15)

- API pública, sin clave: `https://icdp0af7ze.execute-api.us-east-1.amazonaws.com/prod/public`
  con `type=descarga_publica`. Responde `{"message": "ok", "data": {"url", "status", "cached",
  "age_minutes"}}`; `data.url` es un enlace temporal de S3 a `Contratos_publica.xlsx` (~1,4 MB).
  (El legado `OLD/` esperaba `data` como texto: hoy fallaría.)
- El Excel: hoja `contratos`, **2 filas de encabezado** (la 1.a agrupa, la 2.a es el nombre real),
  11.237 contratos, 180 columnas. Energía y potencia por año de 1986 a 2060 (MWh).
- Trampas encontradas:
  - `Fecha Término Renovación` viene como **texto `DD-MM-AAAA`**; las otras fechas son fechas reales
    (error A21: leerla adivinando cambia la vigencia de contratos).
  - Los puntos de retiro/suministro vienen separados por `;` en dos formas: `CHACAHUIN 13` y
    `BA S/E SAN JOAQUIN (CGE) 13.2KV C2`, más el literal `NULO` (1.536 casos).
  - Trae `Correo Cliente` y `Dirección Comercial`: datos personales.

### 1.2 Preguntas de negocio (de `ppa-pipeline/docs/contratos.md`)

¿Qué contratos están por vencer? · ¿Qué contratos tiene un suministrador? · ¿Dónde está el cliente?
· ¿Quién es el cliente? · ¿Qué volumen de energía contrató?

### 1.3 Reglas de negocio (de `ppa-pipeline/docs/requerimientos.md`)

- RN-05: energía = máximo anual · RN-06: solo vigentes · RN-07: sin años aislados
- RN-08: en GWh · RN-09: sin dato de energía = 0
- Fecha de término = también la de renovación · barras por NOMBRE, no por ID

### 1.4 Reglas de la salida (aprobadas por el usuario, 2026-10-15)

Salida: dos tablas. `contratos` (una fila por contrato) y `contrato_barra` (una fila por punto),
separadas para no repetir la energía del contrato en cada barra.

| # | Tema | Regla (entre paréntesis, lo que hacía `OLD/main_diario.py`) |
|---|---|---|
| 1 | Vigencia | término efectivo = mayor entre Término y Término de renovación; columna `vigente` calculada contra el día en que se procesa (`fecha_calculo`) y vista SQL `contrato_hoy` que la recalcula al consultar (mejora 8.1). Manda la fecha; `estado_distinto` marca si 'Estado Contrato' dice otra cosa (decisión del usuario, 2026-10-15) (OLD: `Término >= hoy`) |
| 2 | Contratos ya vistos | cada descarga reemplaza los datos; se conserva `fecha_ingreso` (OLD: nunca actualizaba un contrato existente) |
| 3 | Nuevo / antiguo | `fecha_ingreso` = fecha en que el contrato entró por primera vez a la base (pedido del usuario, 2026-10-15) y `dias_para_vencer` (OLD: regla Inicio ≥ ayer y visto < 1 semana) |
| 4 | Energía | promedio, máximo y mínimo anual en GWh, sin años aislados, vacío = 0; más años usados y aislados |
| 5 | Potencia | potencia máxima anual (OLD: no se usaba) |
| 6 | Puntos | formato largo contrato × punto: subestación, propietario, kV, sección; `NULO` = sin punto; sufijo `(AIS)`/`(GIS)` se descarta (no aporta, decisión del usuario) (OLD: texto en una celda + "ID puntos", columna que ya no existe) |
| 7 | Fechas | formatos explícitos (A21) |
| 8 | Tildes | se conservan, UTF-8 (OLD: las borraba) |
| 9 | Datos personales | correo y dirección del cliente NO entran |
| 10 | Carga | archivo atómico; SQL más adelante (OLD: TRUNCATE + append) |

## 2. Backlog

- [x] Paso 0a: carpeta, `CLAUDE.md` con alcance, `docs/` con las reglas (2026-10-15)
- [x] Paso 0b: decisiones del usuario (§3) y reglas de salida (§1.4)
- [x] Paso 1: andamiaje (uv, ruff, mypy strict, pytest, git init sin commit) — guía `docs/aprendizaje/01_andamiaje.md`
- [x] Paso 2: configuración (`config.py`, `rutas.py`, prefijo `CONT_`, 11 tests) — guía `02_configuracion.md`
- [x] Paso 3: dominio puro (`dominio/fechas.py`, `energia.py`, `puntos.py`; 61 tests en total) — guía `03_dominio.md`
- [x] Paso 4: Bronze (`bronze.py`: API → Excel solo si cambió, manifiesto sha256; 69 tests; probado con la API real) — guía `04_bronze.md`
- [x] Paso 5: Silver (`silver.py`; 76 tests; corrida real en `18. Contratos CEN`: 11.237 contratos, 14.328 puntos) — guía `05_silver.md`
- [x] Paso 6: comando `contratos` (actualizar/descargar/procesar/estado, códigos 0/1/2/3; 83 tests; probado en la red) — guía `06_comando.md`
- [x] Paso 7a: esquema SQL `sql/esquema_contratos.sql` en `cmg_cen` (probado en una copia local: permisos correctos)
- [x] Usuario: corrió el `.sql` en `cmg_cen` del servidor y puso la clave de `contratos_carga` (2026-10-15)
- [x] Paso 7b: `contratos publicar-sql` (reemplazo atómico; `CONT_PG_CONEXION` + `CONT_PG_CLAVE`; 6 tests de integración con `PRUEBA_PG_CONTRATOS`; real local: 11.237 + 14.328 filas en 2,7 s) — guía `07_sql.md`
- [ ] Usuario: poner `CONT_PG_CONEXION` y `CONT_PG_CLAVE` en `.env` y correr `uv run contratos publicar-sql` contra el servidor
- [ ] Más adelante: API de descarga (ADR-C04)

## 3. Decisiones (ADR)

- **ADR-C01 · 2026-10-15 · Claude escribe el código, paso a paso.** Cada paso se muestra en pocas
  líneas y se sigue solo con la aprobación del usuario. Cada paso lleva su guía de estudio.
- **ADR-C02 · 2026-10-15 · Rutas de Bronze y Silver configurables**, como en `cmg-ingesta`
  (`<PREFIJO>_BRONZE_DIR` / `<PREFIJO>_SILVER_DIR`; deben existir, el programa no las crea: A17).
- **ADR-C03 · 2026-10-15 · Silver guarda TODOS los contratos** con una columna `vigente`; los
  reportes filtran. (RN-06 se aplica en la salida, no al guardar: no se pierde historia.)
- **ADR-C04 · 2026-10-15 · Salida:** un archivo como el de `OLD/main_diario.py` (contratos), pero
  con reglas mejor pensadas y seleccionadas. **Más adelante** se sube a SQL y una API permitirá
  descargarlo (fuera del alcance de los primeros pasos, pero no diseñar nada que lo impida).
- **ADR-C05 · 2026-10-15 · Salida = los Parquet de Silver + PostgreSQL `cmg_cen`** (decisión del
  usuario: la misma base de `cmg-ingesta`, 192.168.0.85:5433, PostgreSQL 18.3), en un esquema propio
  `contratos`. Escribe `contratos_carga` (no puede tocar el esquema `cmg`); lee el `cmg_lectura` que
  ya existe (un solo lector para la API). Lo crea el usuario con `sql/esquema_contratos.sql`
  (idempotente; probado en una copia local de `cmg_cen`); la clave con `\password contratos_carga`.
- **ADR-C06 · 2026-10-15 · Carga = reemplazo completo atómico:** cada carga reemplaza las dos
  tablas dentro de UNA transacción (quien consulta nunca ve una tabla vacía ni a medias) y deja
  una fila en `contratos.carga`. `fecha_ingreso` viene de Silver, así que no se pierde.

## 4. Bitácora

### 2026-10-15 — Sesión 1
- Separación de `ppa-pipeline` en tres proyectos (decisión del usuario). Carpeta creada con el
  alcance y las reglas. Sin código todavía.
- Pasos 1–4 hechos (andamiaje, configuración `CONT_`, dominio puro, Bronze). Decisiones del
  usuario: puntos `(AIS)/(GIS)` se reconocen y el sufijo se descarta; columna `fecha_ingreso`
  (fecha en que el contrato entró a la base). Medido: la API sirve un Excel con ~2,3 días de
  antigüedad (`age_minutes = 3253`), así que no cambia todos los días.
- Paso 5 (Silver). El usuario creó `.env` con las rutas de red entre comillas dobles: python-dotenv
  interpreta las barras (se pierde una de las dos barras del inicio y "barra + b" se vuelve un
  carácter de retroceso) y la ruta llegaba deformada. Se quitaron
  las comillas y `config.py` ahora detecta una ruta deformada y dice "escribe las rutas SIN comillas".
- 2 contratos con `Estado Contrato = No vigente` y término futuro (13361, 8885). Decisión del
  usuario: manda la fecha y se agrega la marca `estado_distinto`.
- Paso 6: `estado_distinto` agregado; comando `contratos` probado contra `18. Contratos CEN` (exit 0).
- Paso 7: esquema en `cmg_cen` (decisión del usuario) corrido en el servidor por el usuario; `publicar-sql` probado en local. La clave de `postgres` apareció en el chat: se recomendó cambiarla.

### 2026-10-16 — Sesión 2
- `docs/funcionamiento.md`: funcionamiento detallado, diccionario de datos, garantías, 9 puntos débiles y 10 mejoras priorizadas (la más urgente: la vigencia envejece si el Excel no cambia, §7.1). Error A23 registrado (tiempo atribuido sin medir).
- Mejora 8.1 aplicada: `fecha_calculo` + vista `contratos.contrato_hoy` (día de Chile). El usuario debe volver a correr `sql/esquema_contratos.sql` en el servidor (agrega la columna y la vista).
