# Guía de mantenimiento de contratos-ingesta

Esta guía es para quien mantiene el programa **sin leer el código**. Todo lo que cambia con el
tiempo (dónde están las carpetas, de dónde se baja el Excel, cómo se lee, las reglas que se
ajustan) se corrige en **archivos de texto**: el `.env` y los tres archivos de la carpeta
`config/`. Esta guía dice cuál tocar en cada caso, cómo probar el cambio y cuándo sí hace falta
un programador.

Los comandos se escriben en **PowerShell**, desde la carpeta del programa:

```powershell
cd C:\ruta\a\contratos-ingesta
uv run contratos diagnostico
```

## Contenido

1. [Qué hace el programa](#1-qué-hace-el-programa)
2. [Lo que necesita](#2-lo-que-necesita)
3. [Instalar en un equipo nuevo](#3-instalar-en-un-equipo-nuevo)
4. [La rutina](#4-la-rutina)
5. [Ante cualquier problema](#5-ante-cualquier-problema)
6. [Recetas: si pasa X, haz Y](#6-recetas-si-pasa-x-haz-y)
7. [Fichas de alertas](#7-fichas-de-alertas)
8. [Los archivos editables](#8-los-archivos-editables)
9. [Todos los comandos](#9-todos-los-comandos)
10. [Lo que no hay que tocar](#10-lo-que-no-hay-que-tocar)
11. [Cuándo hace falta un programador](#11-cuándo-hace-falta-un-programador)
12. [Problemas conocidos](#12-problemas-conocidos)
13. [Glosario](#13-glosario)

## 1. Qué hace el programa

Junta los **contratos de suministro** que publica el Coordinador Eléctrico Nacional en su
Plataforma de Mercado: quién le vende a quién, desde cuándo y hasta cuándo, cuánta energía y en
qué puntos de la red. Los deja en tablas limpias y en una base de datos.

```
 Coordinador: descarga pública de la Plataforma de Mercado   (config/fuente.toml)
          │  descargar
          ▼
 BRONZE   el Excel tal como lo entrega el Coordinador:
          Contratos_publica_AAAAMMDD_HHMMSS.xlsx   (una copia solo cuando cambia)
          + manifiesto.json (la lista de los Excel bajados)
          │  procesar   (lee el Excel según config/excel.toml y config/reglas.toml)
          ▼
 SILVER   contratos.parquet        un contrato por fila (todos, vigentes o no)
          contrato_barra.parquet   un punto de retiro o suministro por fila
          _control.json            fecha de ingreso de cada contrato y la huella
          │  publicar-sql
          ▼
 PostgreSQL (base cmg_cen, esquema contratos)  ──►  consultas, otros programas
```

- **Qué guarda de cada contrato:** empresas, RUT, tipo, región, fechas, si está **vigente**,
  cuántos días le quedan, la energía anual (máximo, promedio y mínimo, en GWh) y la potencia.
- **Vigente:** cuando su fecha de término (la mayor entre "Término" y "Fecha Término
  Renovación") es hoy o posterior. Se recalcula **cada día**. La columna "Estado Contrato" del
  Coordinador no decide: si dice otra cosa, queda marcado en `estado_distinto`.
- **Fecha de ingreso:** el primer día en que el contrato apareció. Se conserva entre corridas.
- **Datos personales:** "Correo Cliente" y "Dirección Comercial" no se leen.
- **El Excel del Coordinador no cambia todos los días:** el programa guarda una copia nueva
  solo cuando cambia.

## 2. Lo que necesita

| Qué | Para qué |
|---|---|
| Windows con PowerShell | Todo |
| [uv](https://docs.astral.sh/uv/) | Instala Python y las librerías del programa |
| Internet hacia la descarga del Coordinador | Bajar el Excel (la dirección está en `config/fuente.toml`) |
| Una carpeta para Bronze y otra para Silver | Guardar los datos (en la red de la empresa o en el equipo) |
| La clave del usuario `contratos_carga` de PostgreSQL | Solo si este equipo publica en la base (`publicar-sql`) |
| El archivo `.env` de este equipo | Dónde están las carpetas, la conexión y la clave |

## 3. Instalar en un equipo nuevo

1. **Copia la carpeta del programa**, sin las subcarpetas `.venv` ni `data`: se recrean.
2. **Instala uv** (una vez por equipo), en PowerShell:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   Cierra y vuelve a abrir PowerShell.
3. **Instala el programa:** desde la carpeta, `uv sync`. Baja Python 3.13 y las librerías.
4. **Crea la carpeta de datos:** `mkdir data`. Ahí van los registros de cada corrida
   (`data\logs`) y las alertas (`data\alertas`). El programa no crea carpetas que tú no creaste,
   a propósito: una ruta mal escrita terminaría en una carpeta nueva y equivocada.
5. **Crea el `.env`** desde la plantilla y complétalo con una de las dos opciones de abajo:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   **El `.env` tiene la clave: no lo mandes por correo ni chat, y no lo copies a otro equipo.**
6. **Comprueba:** `uv run contratos diagnostico`. Tiene que decir "Todo bien", o solo avisos que
   entiendas (en un equipo nuevo, "no hay ningún Excel descargado" es normal).
7. **Pon todo al día:** `uv run contratos actualizar`.

> Siempre corre los comandos **desde la carpeta del programa** (`cd` primero).

### 3.1 Opción A: en la red de la empresa (Safira)

Bronze y Silver quedan en la carpeta compartida, y se publica en la base de datos:

```ini
CONT_DATA_DIR=data
CONT_BRONZE_DIR=\\SAFIRA_CL1\FrontOffice\Comercial\00. Información\18. Contratos CEN\bronze
CONT_SILVER_DIR=\\SAFIRA_CL1\FrontOffice\Comercial\00. Información\18. Contratos CEN\silver
CONT_PG_CONEXION=host=192.168.0.85 port=5433 dbname=cmg_cen user=contratos_carga
CONT_PG_CLAVE=la-clave-de-contratos_carga
```

- La clave la entrega quien administra la base. **Nunca** va dentro de `CONT_PG_CONEXION`: si la
  escribes ahí, el programa se detiene y lo dice.
- Las carpetas de red ya existen. Si el equipo no las ve (no está conectado a la red), el
  programa se detiene sin escribir nada.

### 3.2 Opción B: en un computador cualquiera

Todo queda en el equipo, en una carpeta que elijas, con Bronze y Silver separados. Sin base de
datos (se puede agregar después):

```powershell
mkdir C:\Datos\Contratos\bronze
mkdir C:\Datos\Contratos\silver
```

```ini
CONT_DATA_DIR=data
CONT_BRONZE_DIR=C:\Datos\Contratos\bronze
CONT_SILVER_DIR=C:\Datos\Contratos\silver
CONT_PG_CONEXION=
CONT_PG_CLAVE=
```

- Las dos carpetas se crean **una vez a mano** (los `mkdir` de arriba).
- Con `CONT_PG_CONEXION` vacía, `actualizar` se salta la publicación y `diagnostico` lo muestra
  como aviso.

### 3.3 Reglas del `.env`

- **Rutas sin comillas.** Entre comillas, las barras `\` se deforman y el programa se detiene
  diciendo "llegó deformada".
- **Vacío = valor por defecto.** `CONT_BRONZE_DIR` y `CONT_SILVER_DIR` vacías usan
  `data\bronze` y `data\silver` (esas sí se crean solas, dentro de `data`).
- **Una variable `CONT_` mal escrita detiene el programa** y dice cuál es y cuáles son las
  válidas.

## 4. La rutina

### 4.1 Poner todo al día

```powershell
uv run contratos actualizar
```

Hace tres pasos y termina con un resumen:

1. **Descarga** el Excel. Si es igual al último, no guarda otra copia.
2. **Pasa a Silver** el último Excel. Si ya se hizo hoy con el mismo Excel y la misma
   configuración, no lo rehace.
3. **Sube a PostgreSQL**, si hay `CONT_PG_CONEXION` en el `.env` y Silver cambió desde la última
   carga.

Si un paso falla, los siguientes se corren igual: sin internet, igual se recalcula la vigencia
con el último Excel. Correrlo dos veces no hace daño.

### 4.2 Cada cuánto

**Una vez al día.** La vigencia y los días que le quedan a cada contrato se calculan contra el
día en que se corre: si no corre, Silver queda con la vigencia de la última vez (la base no,
porque la vista `contrato_hoy` la recalcula sola, ver [6.10](#610-cambió-la-clave-la-dirección-o-el-puerto-de-postgresql)).

### 4.3 Dejarlo automático (Programador de tareas de Windows)

1. Abre el **Programador de tareas** y elige **Crear tarea básica**. Ponle un nombre (por
   ejemplo "Contratos actualizar") y frecuencia **diaria**, a una hora en que el equipo esté
   encendido.
2. En **Acción**, elige "Iniciar un programa" y completa:
   - **Programa:** `powershell.exe`
   - **Argumentos:** `-NoProfile -Command "uv run contratos actualizar *>> data\tarea.log; exit $LASTEXITCODE"`.
     El `exit $LASTEXITCODE` hace falta: sin él, la tarea muestra 1 aunque el programa haya
     terminado con 3. El `*>> data\tarea.log` guarda lo que se vería en pantalla, también si
     el programa no alcanza a arrancar.
   - **Iniciar en:** la carpeta del programa, por ejemplo
     `C:\Users\usuario\Desktop\Scripts\contratos-ingesta`.
3. En las propiedades de la tarea, marca **"Ejecutar solo cuando el usuario haya iniciado
   sesión"**: las carpetas de red solo se ven en la sesión del usuario.
4. Al otro día, mira el **último resultado** de la tarea:
   - `0x0`: todo bien.
   - `0x1`: algo falló. Mira el último archivo de `data\alertas\`.
   - `0x3`: hay algo que revisar. Mira el último archivo de `data\alertas\`.

## 5. Ante cualquier problema

### 5.1 Primero el diagnóstico

```powershell
uv run contratos diagnostico
```

Revisa todo aquello de lo que depende el programa y marca cada cosa `OK`, `AVISO` o `MAL`. Bajo
cada `AVISO` o `MAL` dice **qué hacer**.

- **Los archivos de `config/`:** que estén bien escritos.
- **El `.env`:** que exista y se lea.
- **Las carpetas** de datos, Bronze y Silver: que existan y se pueda escribir (crea y borra al
  instante un archivo de prueba).
- **Bronze:** cuántos Excel hay y si falta alguno de los registrados.
- **Silver:** si está al día con el último Excel y con `config/`, y si la vigencia se calculó
  hace más de un día (la tarea diaria no está corriendo).
- **El disco:** aviso con menos de 1 GB libre; MAL con menos de 0,1 GB.
- **La descarga del Coordinador:** que responda (no baja el Excel).
- **PostgreSQL:** que conecte, cuántas cargas tiene y cuántos contratos.

`uv run contratos diagnostico --sin-red` hace solo lo local. `diagnostico` funciona aunque el
`.env` o `config/` estén mal escritos: es para eso.

### 5.2 Los códigos de salida

Todos los comandos terminan con un número; las tareas programadas lo muestran como "último
resultado".

| Código | Significa | Qué haces |
|---|---|---|
| 0 | Todo bien | Nada |
| 1 | No se pudo: sin red, el Coordinador no responde, PostgreSQL apagado, un archivo de config mal escrito | Lee el mensaje; corre `diagnostico` |
| 2 | El comando está mal escrito (una opción que no existe, un archivo que no está) | Corrige el comando |
| 3 | Se hizo, pero hay algo que revisar | Lee los avisos (o el último archivo de `data\alertas\`) |

### 5.3 Cómo leer una alerta

Cada problema se muestra igual, en pantalla y en el registro:

```
NO entraría a Silver: no_es_excel.xlsx no se pudo leer como Excel de contratos con la hoja 'contratos' (…)
  qué hacer: Revisar que sea el .xlsx del Coordinador (…). Si la hoja de los contratos cambió de
  nombre, corregir 'nombre' en [hoja] de config/excel.toml.
  (alerta excel_ilegible en la guía)
```

1. **La primera línea** dice qué pasó, con los datos de ese caso.
2. **"qué hacer"** dice qué archivo y sección editar, qué comando correr, o que es trabajo de
   programador.
3. **"(alerta …)"** es el tipo: búscalo en la [sección 7](#7-fichas-de-alertas).

Los avisos dicen además su severidad: **aviso** (hay que mirarlo; el comando termina con 3) o
**info** (solo para saber).

**Los registros:**

- `data\logs\contratos_AAAAMMDD.log`: todo lo que mostró cada comando ese día, con la hora.
- `data\alertas\ALERTA_AAAAMMDD_HHMMSS.txt`: lo deja cada comando de rutina que termina con 1
  o 3. Trae el comando, el código, qué hacer en general y la salida completa de esa corrida.
  `revisar-config`, `diagnostico` y `probar-excel` no dejan alerta: lo muestran todo en pantalla.

## 6. Recetas: si pasa X, haz Y

> **Antes de editar cualquier archivo de `config/`, haz una copia de la carpeta `config`**
> (por ejemplo `config_respaldo_2026-10-26`). Si algo sale mal, vuelves a la copia.
> Después de editar: `uv run contratos revisar-config`.

### 6.1 El Coordinador renombró una columna que se lee

**Cómo te enteras:** `excel_falta_columna` (el proceso se detiene), junto con `columnas_nuevas`
y `columnas_que_faltan` en `probar-excel`.

Por ejemplo, "Empresa Cliente" pasa a llamarse "Cliente Final". En `config/excel.toml`, cambia
el nombre en `conocidas` de `[columnas]` **y** en la sección donde se lee.

Antes:

```toml
conocidas = [
    ...
    "Empresa Cliente",
    ...
]

[columnas.texto]
cliente = "Empresa Cliente"
```

Después:

```toml
conocidas = [
    ...
    "Cliente Final",
    ...
]

[columnas.texto]
cliente = "Cliente Final"
```

El nombre de la izquierda (`cliente`) **no se cambia**: es la columna de Silver y de la base.

**Prueba:** `uv run contratos revisar-config` y luego `uv run contratos probar-excel`. Tiene que
decir "Entraría a Silver", sin `columnas_nuevas` ni `columnas_que_faltan`. Después,
`uv run contratos actualizar`: como cambió cómo se lee, Silver se rehace solo.

### 6.2 El Coordinador agregó o quitó una columna que no se lee

**Cómo te enteras:** `columnas_nuevas` o `columnas_que_faltan` (aviso, código 3). Los datos se
procesaron igual.

- **Columna nueva que no hace falta:** agrégala a `conocidas` de `[columnas]` en
  `config/excel.toml`, tal como viene en el Excel. Deja de avisar.
- **Columna que ya no viene:** sácala de `conocidas`. Si es una de las que se leen (está en
  `[columnas.texto]`, `[columnas.fecha]` o `[columnas.puntos]`), no se puede sacar: es la
  receta 6.1 o, si de verdad desapareció, trabajo de programador.

Cambiar `conocidas` solo cambia los avisos: no rehace Silver.

### 6.3 Una fecha llega escrita de otra forma

**Cómo te enteras:** `fecha_formato_desconocido` (aviso, código 3). Esas fechas quedaron vacías,
y un contrato sin fecha de término queda **no vigente**.

Por ejemplo, el Término llega como `2027/12/31`. En `[fechas]` de `config/excel.toml` agrega la
forma a `formas` y un ejemplo real a `[fechas.ejemplos]`, con la fecha que **tiene que dar**:

Antes:

```toml
formas = [
    "AAAA-MM-DD hh:mm:ss",
    "DD-MM-AAAA",
]

[fechas.ejemplos]
"2026-09-24 00:00:00" = "2026-09-24"
"30-09-2026" = "2026-09-30"
"01-09-2026" = "2026-09-01"
```

Después:

```toml
formas = [
    "AAAA-MM-DD hh:mm:ss",
    "DD-MM-AAAA",
    "AAAA/MM/DD",
]

[fechas.ejemplos]
"2026-09-24 00:00:00" = "2026-09-24"
"30-09-2026" = "2026-09-30"
"01-09-2026" = "2026-09-01"
"2027/12/31" = "2027-12-31"
```

**Los marcadores:** `AAAA` año, `MM` mes, `DD` día, `hh` hora, `mm` minuto, `ss` segundo.
Distinguen mayúsculas: `MM` es el mes y `mm` el minuto. El ejemplo con la fecha que tiene que dar
es lo que detecta un día y un mes cambiados de lugar (`05-03-2027` es el 5 de marzo, no el 3 de
mayo).

**Prueba:** `revisar-config`, `probar-excel` (tiene que leer todas las fechas escritas) y luego
`actualizar`.

### 6.4 Cambiaron las columnas de cada año

**Cómo te enteras:** `excel_sin_columnas_anio` (el proceso se detiene), o `anios_nuevos` (info).

- **Cambió el nombre** (por ejemplo, "Energía 2026" pasa a "Energía (MWh) 2026"): corrige la
  plantilla en `[columnas.por_anio]` de `config/excel.toml` y su ejemplo:

  ```toml
  energia = "Energía (MWh) {año}"
  ejemplos = ["Energía (MWh) 2026", "Potencia 2026"]
  ```

  `{año}` es un año de 4 dígitos. Cada plantilla necesita un ejemplo real que calce. Silver se
  rehace solo.
- **El Excel trae años fuera del rango** (`anios_nuevos`): se leen igual. Para que deje de
  informarlo, amplía `anio_min` o `anio_max` en `[columnas.por_anio]`. No rehace nada.

### 6.5 Cambió la hoja o la fila de los títulos

**Cómo te enteras:** `excel_ilegible` (la hoja no existe) o `excel_falta_columna` en todas las
columnas (la fila de títulos se movió).

Abre el Excel y mira el nombre de la pestaña y en qué fila están los títulos de las columnas.
Corrige `nombre` o `fila_encabezado` en `[hoja]` de `config/excel.toml` (la fila se cuenta como
en Excel: la primera es la 1). Prueba con `probar-excel`.

### 6.6 Un texto nuevo de "sin punto", o un sufijo nuevo en los puntos

**Cómo te enteras:** `puntos_no_reconocidos` (info) crece, y en `contrato_barra` aparecen puntos
como `SIN PUNTO` o `BA S/E X 220KV C1 (HIB)` sin separar.

En `[puntos]` de `config/reglas.toml`:

- **Un texto que significa "sin punto"** (como el `NULO`): agrégalo a `vacios`.
- **Un sufijo que hay que quitar** (como `(AIS)` y `(GIS)`): agrégalo a
  `sufijos_que_se_quitan` y agrega a `ejemplos` un punto real que termine con él.

Silver se rehace solo en el próximo `actualizar`. Una **forma nueva de escribir un punto** (que no
sea ninguna de las dos de siempre) es trabajo de programador.

### 6.7 Cambiar los días "por vencer"

`contratos estado` cuenta los contratos vigentes que vencen dentro de `dias_por_vencer` días
(hoy 180). Se cambia en `[avisos]` de `config/reglas.toml`. No rehace nada.

### 6.8 La descarga del Coordinador cambió

**Cómo te enteras:** `api_rechazo` (403 o 404) o `api_respuesta_desconocida`, todos los días.
`diagnostico` muestra "Descarga del Coordinador" en MAL.

- **Si es un 403 o 404:** cambió la dirección o algún filtro. Abre la Plataforma de Mercado del
  Coordinador en el navegador y busca la descarga pública de contratos. Corrige `direccion` en
  `[api]` o los valores de `[api.parametros]` de `config/fuente.toml`, y prueba con
  `uv run contratos diagnostico` (pide el enlace sin bajar el Excel).
- **Si es `api_respuesta_desconocida`:** el Coordinador cambió la forma de su respuesta. Es
  trabajo de programador.

Mientras tanto, `actualizar` sigue recalculando la vigencia con el último Excel.

### 6.9 Un Excel llegó dañado

**Cómo te enteras:** `excel_ilegible` con un Excel de Bronze, o `descarga_no_es_excel`.

```powershell
uv run contratos estado                                   # muestra los nombres de los últimos Excel
uv run contratos volver-a-bajar Contratos_publica_20261015_165541.xlsx
uv run contratos actualizar
```

`volver-a-bajar` saca el Excel del registro y lo mueve a la carpeta `_apartados` de Bronze. **No
borra nada.** El próximo `actualizar` lo baja de nuevo.

### 6.10 Cambió la clave, la dirección o el puerto de PostgreSQL

**Cómo te enteras:** `pg_error`.

- **La clave:** quien administra la base la cambia con `\password contratos_carga` en `psql`.
  Escribe la nueva en `CONT_PG_CLAVE` del `.env`.
- **La dirección o el puerto:** corrígelos en `CONT_PG_CONEXION` del `.env`.
- **Prueba:** `uv run contratos diagnostico` (la línea PostgreSQL tiene que decir "conecta").

**Sobre la base:**

- El esquema `contratos` vive en la base `cmg_cen` y se crea **una vez**, como administrador,
  con `sql/esquema_contratos.sql` (se puede volver a correr sin daño):
  `psql -h 192.168.0.85 -p 5433 -U postgres -d cmg_cen -f sql/esquema_contratos.sql`.
- **Usuarios:** `contratos_carga` escribe (lo usa `publicar-sql`); `cmg_lectura` solo lee.
- **Tablas:** `contrato`, `contrato_barra`, `carga` (una fila por carga) y `contrato_historial`
  (qué contratos aparecieron, cambiaron o desaparecieron en cada carga).
- **Para consultar, usar la vista `contrato_hoy`:** recalcula la vigencia con el día de hoy cada
  vez, aunque la carga no haya corrido.
- Cada `publicar-sql` reemplaza las tablas en **una sola transacción**: quien consulta ve la
  versión anterior hasta que termina. Si falla a la mitad, la base queda como estaba.

### 6.11 Cambió la carpeta de red, o se cambia de equipo

**Cómo te enteras:** `carpeta_no_encontrada`.

- **La carpeta se movió:** corrige `CONT_BRONZE_DIR` o `CONT_SILVER_DIR` en el `.env` (sin
  comillas). Mueve **todo** el contenido de la carpeta vieja a la nueva: los Excel, el
  `manifiesto.json` y los archivos de Silver.
- **Equipo nuevo:** sigue la [sección 3](#3-instalar-en-un-equipo-nuevo). No corras la rutina en
  dos equipos a la vez sobre las mismas carpetas.

### 6.12 Rehacer Silver o volver a subir a la base

- `uv run contratos procesar --forzar`: rehace Silver aunque esté al día.
- `uv run contratos publicar-sql --forzar`: sube Silver aunque no haya cambiado.

### 6.13 Se borró el control de Silver

**Cómo te enteras:** `control_reconstruido` (info).

`_control.json` guarda la fecha de ingreso de cada contrato. Si se borra, el programa la rehace
con el Excel más antiguo de Bronze en que aparece cada contrato. Por eso **no hay que borrar los
Excel viejos de Bronze**.

## 7. Fichas de alertas

Cada alerta dice su tipo: "(alerta `tipo` en la guía)". **Código** es con qué termina el comando.

### 7.1 Configuración

#### `env_invalido`

- **Código:** 1. Sale en cualquier comando, salvo `revisar-config` y `diagnostico`.
- **Qué pasó:** el `.env` está mal escrito: una variable `CONT_` que no existe, una ruta entre
  comillas o la clave dentro de `CONT_PG_CONEXION`. El mensaje dice cuál, sin mostrar valores.
- **Qué hacer:** corregir el `.env` ([3.3](#33-reglas-del-env)); las variables válidas están en
  `.env.example`. Probar con `diagnostico`.

#### `config_invalida`

- **Código:** 1. Sale en cualquier comando, salvo `revisar-config` y `diagnostico`. No se
  descargó ni se escribió nada.
- **Qué pasó:** un archivo de `config/` está mal escrito. El mensaje dice el archivo, la sección
  y qué corregir.
- **Qué hacer:** corregirlo (o volver a la copia de `config`) y probar con `revisar-config`.

#### `carpeta_no_encontrada`

- **Código:** 1.
- **Qué pasó:** no existe la carpeta de datos, de Bronze o de Silver que dice el `.env`.
- **Qué hacer:** si es de red, revisar que el equipo esté conectado; si la ruta está mal,
  corregirla en el `.env`; si es nueva, crearla una vez a mano ([6.11](#611-cambió-la-carpeta-de-red-o-se-cambia-de-equipo)).

#### `archivo_inaccesible`

- **Código:** 1.
- **Qué pasó:** Windows no dejó leer o escribir un archivo: la red se cortó o alguien lo tiene
  abierto (por ejemplo, un parquet o el Excel abierto en Excel).
- **Qué hacer:** cerrarlo, revisar la red y volver a correr. Nada quedó a medias.

#### `archivo_no_existe`

- **Código:** 2. Sale en `probar-excel`.
- **Qué pasó:** el archivo que se le pasó no existe.
- **Qué hacer:** revisar la ruta (si tiene espacios, va entre comillas).

### 7.2 Descarga

#### `api_sin_conexion`

- **Código:** 1. Sale en `descargar` y `actualizar` (que sigue con el resto).
- **Qué pasó:** no hubo conexión con la descarga del Coordinador, después de los intentos que
  dice `reintentos` en `[api]` de `config/fuente.toml` (hoy 3).
- **Qué hacer:** revisar internet y volver a correr más tarde. Si pasa varios días, `diagnostico`.

#### `api_rechazo`

- **Código:** 1.
- **Qué pasó:** el Coordinador respondió con un error HTTP (por ejemplo 403, 404, 500).
- **Qué hacer:** 429 o 5xx: volver a correr más tarde. 403 o 404: [6.8](#68-la-descarga-del-coordinador-cambió).

#### `api_respuesta_desconocida`

- **Código:** 1.
- **Qué pasó:** la respuesta no trae el enlace al Excel donde siempre.
- **Qué hacer:** trabajo de programador. Silver sigue con el último Excel.

#### `descarga_no_es_excel`

- **Código:** 1.
- **Qué pasó:** lo que se bajó no es un archivo .xlsx (por ejemplo, el enlace venció).
- **Qué hacer:** volver a correr más tarde; si se repite, trabajo de programador.

#### `bronze_vacio`

- **Código:** 1. Sale en `procesar` y `probar-excel`.
- **Qué pasó:** no hay ningún Excel en Bronze.
- **Qué hacer:** `actualizar` (o `descargar`). En un equipo nuevo es normal.

#### `apartar_fallo`

- **Código:** 1. Sale en `volver-a-bajar`.
- **Qué pasó:** no se pudo mover el Excel a `_apartados`. El registro no se cambió.
- **Qué hacer:** cerrar el Excel si está abierto, revisar el permiso de escritura en Bronze y
  volver a correr.

### 7.3 El Excel

#### `excel_ilegible`

- **Código:** 1.
- **Qué pasó:** el archivo no se pudo leer como el Excel de contratos: no es un .xlsx, está
  dañado o no tiene la hoja que dice `[hoja]`.
- **Qué hacer:** [6.5](#65-cambió-la-hoja-o-la-fila-de-los-títulos) o [6.9](#69-un-excel-llegó-dañado).

#### `excel_falta_columna`

- **Código:** 1. Silver no se tocó.
- **Qué pasó:** falta una columna que se lee.
- **Qué hacer:** [6.1](#61-el-coordinador-renombró-una-columna-que-se-lee).

#### `excel_sin_columnas_anio`

- **Código:** 1.
- **Qué pasó:** ninguna columna calza con la plantilla de energía o potencia por año.
- **Qué hacer:** [6.4](#64-cambiaron-las-columnas-de-cada-año).

#### `excel_sin_contratos`

- **Código:** 1. Sale en `probar-excel`.
- **Qué pasó:** ninguna fila trae el ID del contrato.
- **Qué hacer:** revisar el Excel; si la columna del ID cambió de nombre, corregir `id_contrato`
  en `[columnas.texto]` ([6.1](#61-el-coordinador-renombró-una-columna-que-se-lee)).

#### `excel_nombre_sin_fecha`

- **Código:** 1. Sale en `procesar --archivo`.
- **Qué pasó:** el nombre del Excel no trae la fecha de los datos (la pone la descarga:
  `Contratos_publica_AAAAMMDD_HHMMSS.xlsx`).
- **Qué hacer:** usar el Excel de Bronze, o renombrar la copia con ese formato.

#### `columnas_nuevas`

- **Código:** 3 (aviso). Silver se hizo igual.
- **Qué pasó:** el Excel trae columnas que no están en `conocidas`.
- **Qué hacer:** [6.2](#62-el-coordinador-agregó-o-quitó-una-columna-que-no-se-lee), o
  [6.1](#61-el-coordinador-renombró-una-columna-que-se-lee) si es un nombre nuevo.

#### `columnas_que_faltan`

- **Código:** 3 (aviso).
- **Qué pasó:** columnas de `conocidas` que el Excel ya no trae.
- **Qué hacer:** [6.2](#62-el-coordinador-agregó-o-quitó-una-columna-que-no-se-lee).

#### `anios_nuevos`

- **Código:** 0 (info).
- **Qué pasó:** columnas de años fuera de `anio_min` y `anio_max`. Se leen igual.
- **Qué hacer:** nada urgente; [6.4](#64-cambiaron-las-columnas-de-cada-año).

#### `fecha_formato_desconocido`

- **Código:** 3 (aviso).
- **Qué pasó:** fechas escritas de una forma que no está en `[fechas]`. Quedaron vacías.
- **Qué hacer:** [6.3](#63-una-fecha-llega-escrita-de-otra-forma).

#### `energia_con_coma`

- **Código:** 3 (aviso).
- **Qué pasó:** valores de energía o potencia con coma. Se leen como decimal (`1400,5`).
- **Qué hacer:** mirarlos en el Excel. Si la coma separa miles (`1,400`), el dato queda 1.000
  veces menor: trabajo de programador.

#### `energia_no_numerica`

- **Código:** 3 (aviso).
- **Qué pasó:** valores de energía o potencia que no son números. Quedaron vacíos.
- **Qué hacer:** mirarlos en el Excel; si se repite, trabajo de programador.

### 7.4 Silver

#### `ids_repetidos`

- **Código:** 3 (aviso) en `procesar`; 1 en `publicar-sql`, que no sube nada.
- **Qué pasó:** el Excel trae dos filas con el mismo ID de contrato.
- **Qué hacer:** revisar esos IDs en el Excel del Coordinador. La base queda como estaba hasta
  que llegue un Excel sin repetidos.

#### `sin_id`

- **Código:** 3 (aviso).
- **Qué pasó:** filas sin ID de contrato. No entraron a Silver.
- **Qué hacer:** revisarlas en el Excel; si siguen llegando, avisar al Coordinador.

#### `estado_distinto`

- **Código:** 0 (info).
- **Qué pasó:** contratos cuyo "Estado Contrato" no coincide con la vigencia por fecha.
- **Qué hacer:** nada: manda la fecha (decisión del 2026-10-15). La columna `estado_distinto`
  los marca para revisarlos.

#### `puntos_no_reconocidos`

- **Código:** 0 (info).
- **Qué pasó:** puntos que no calzan con ninguna de las dos formas conocidas. Se guardaron con el
  texto completo (el 2026-10-15 eran 40 de 14.328).
- **Qué hacer:** [6.6](#66-un-texto-nuevo-de-sin-punto-o-un-sufijo-nuevo-en-los-puntos) si es un
  texto vacío o un sufijo nuevo.

#### `control_reconstruido`

- **Código:** 0 (info).
- **Qué pasó:** faltaba `_control.json` y la fecha de ingreso se rehízo desde Bronze.
- **Qué hacer:** nada ([6.13](#613-se-borró-el-control-de-silver)).

#### `silver_vacio`

- **Código:** 3 en `estado`; 1 en `publicar-sql`.
- **Qué pasó:** Silver todavía no tiene datos.
- **Qué hacer:** `procesar` (o `actualizar`).

#### `silver_no_al_dia`

- **Código:** 3. Sale en `estado`.
- **Qué pasó:** Silver se hizo con otro Excel o con otra configuración de `config/`.
- **Qué hacer:** `procesar`.

### 7.5 PostgreSQL

#### `pg_sin_configurar`

- **Código:** 1. Sale en `publicar-sql` (`actualizar` se salta ese paso solo).
- **Qué pasó:** falta `CONT_PG_CONEXION` o `CONT_PG_CLAVE` en el `.env`.
- **Qué hacer:** completarlas ([3.1](#31-opción-a-en-la-red-de-la-empresa-safira)).

#### `pg_esquema_antiguo`

- **Código:** 1. No se cambió nada en la base.
- **Qué pasó:** a la base le falta una tabla o columna nueva.
- **Qué hacer:** un administrador corre `sql/esquema_contratos.sql` ([6.10](#610-cambió-la-clave-la-dirección-o-el-puerto-de-postgresql)).

#### `pg_error`

- **Código:** 1. No se cambió nada en la base.
- **Qué pasó:** no se pudo conectar o falló una consulta.
- **Qué hacer:** [6.10](#610-cambió-la-clave-la-dirección-o-el-puerto-de-postgresql).

#### `silver_invalido`

- **Código:** 1. No se cambió nada en la base.
- **Qué pasó:** Silver no pasó la revisión antes de subirlo: está vacío, le faltan columnas, hay
  contratos sin ID o puntos de contratos que no existen.
- **Qué hacer:** `procesar --forzar` y volver a publicar; si se repite, `probar-excel`; si
  sigue, trabajo de programador.

### 7.6 Lo inesperado

#### `error_inesperado`

- **Código:** 1.
- **Qué pasó:** un error que el programa no sabe explicar.
- **Qué hacer:** volver a correr. Si se repite, es trabajo de programador: entrégale el mensaje y
  el archivo de `data\alertas`.

## 8. Los archivos editables

### Cómo editar sin romper nada

1. **Haz una copia de la carpeta `config`** antes de tocarla.
2. Edita con el Bloc de notas o VS Code. Guarda en **UTF-8** (el Bloc de notas lo hace por
   defecto).
3. En los TOML, **los textos van entre comillas** y **los números sin comillas**. Una línea que
   empieza con `#` es un comentario. Cada archivo explica sus campos en sus comentarios.
4. Corre `uv run contratos revisar-config`: revisa los tres archivos y dice, para cada error, el
   archivo, la sección y qué corregir.
5. Si cambiaste cómo se lee el Excel, prueba con `uv run contratos probar-excel` antes de
   procesar.

**Qué rehace Silver:** solo lo que cambia el contenido. Lo demás cambia avisos y no rehace nada.

### 8.1 `.env`: dónde están las cosas

Uno por equipo, con la clave. Nunca se copia a otro equipo ni se versiona.

| Variable | Qué es | Vacía |
|---|---|---|
| `CONT_DATA_DIR` | Carpeta de los registros y alertas | `data`, dentro del programa |
| `CONT_BRONZE_DIR` | Carpeta de Bronze | `data\bronze` |
| `CONT_SILVER_DIR` | Carpeta de Silver | `data\silver` |
| `CONT_PG_CONEXION` | Conexión a PostgreSQL, **sin** la clave | No se publica |
| `CONT_PG_CLAVE` | La clave del usuario de la conexión | No se publica |

### 8.2 `config/fuente.toml`: de dónde se baja el Excel

| Campo | Qué es | ¿Rehace Silver? |
|---|---|---|
| `direccion` de `[api]` | La dirección de la descarga pública | No |
| `reintentos` de `[api]` | Intentos ante una falla de red (1 a 10; hoy 3) | No |
| `[api.parametros]` | Los filtros de la descarga (todos vacíos = todos los contratos) | No |
| `[api.encabezados]` | `origin` y `accept` que se mandan con la petición | No |

### 8.3 `config/excel.toml`: cómo se lee el Excel

| Campo | Qué es | ¿Rehace Silver? |
|---|---|---|
| `nombre` de `[hoja]` | La pestaña de los contratos | Sí |
| `fila_encabezado` de `[hoja]` | La fila con los títulos (hoy 2) | Sí |
| `conocidas` de `[columnas]` | Todas las columnas fijas que trae el Excel | No (solo avisos) |
| `[columnas.texto]`, `[columnas.fecha]`, `[columnas.puntos]` | De qué columna del Excel sale cada columna de Silver | Sí |
| `energia`, `potencia` de `[columnas.por_anio]` | Plantillas de las columnas de cada año (`{año}`) | Sí |
| `ejemplos` de `[columnas.por_anio]` | Nombres reales que prueban las plantillas | No |
| `anio_min`, `anio_max` de `[columnas.por_anio]` | Rango de años esperado | No (solo avisos) |
| `formas` de `[fechas]` | Cómo vienen escritas las fechas | Sí |
| `[fechas.ejemplos]` | Fechas reales y la fecha que tienen que dar | No |

### 8.4 `config/reglas.toml`: reglas que se ajustan

| Campo | Qué es | ¿Rehace Silver? |
|---|---|---|
| `dias_por_vencer` de `[avisos]` | Días para "vencen pronto" en `estado` (hoy 180) | No |
| `vacios` de `[puntos]` | Textos que significan "sin punto" (hoy `NULO`) | Sí |
| `sufijos_que_se_quitan` de `[puntos]` | Lo que se quita del final de un punto (hoy `(AIS)`, `(GIS)`) | Sí |
| `ejemplos` de `[puntos]` | Puntos reales que terminan en cada sufijo | No |

## 9. Todos los comandos

Todos se escriben `uv run contratos COMANDO`, desde la carpeta del programa. `--help` después
de cualquiera muestra su ayuda.

### Rutina

| Comando | Qué hace |
|---|---|
| `actualizar` | Descargar, procesar y publicar en un paso. Si uno falla, sigue con los demás. Para la tarea diaria |
| `estado` | Qué hay en Bronze y en Silver, cuántos contratos vencen pronto y si Silver está al día |

### Mantenimiento

| Comando | Qué hace |
|---|---|
| `diagnostico` | Revisa todo y dice qué hacer. `--sin-red` hace solo lo local |
| `revisar-config` | Revisa los tres archivos de `config/` y muestra todos los errores |
| `probar-excel` | Procesa un Excel con la configuración actual, sin escribir nada. Sin ruta, usa el último de Bronze |
| `volver-a-bajar NOMBRE` | Aparta un Excel de Bronze y lo saca del registro, para bajarlo de nuevo |

### Los pasos por separado

| Comando | Qué hace |
|---|---|
| `descargar` | Baja el Excel a Bronze, solo si cambió |
| `procesar` | Pasa a Silver el último Excel. `--archivo RUTA` usa otro; `--forzar` rehace aunque esté al día |
| `publicar-sql` | Sube Silver a PostgreSQL si cambió. `--forzar` sube igual |

## 10. Lo que no hay que tocar

| Archivo | Por qué |
|---|---|
| `manifiesto.json` (en Bronze) | La lista de los Excel bajados. Para sacar uno, `volver-a-bajar` |
| Los Excel de Bronze | Son la historia: de ellos sale la fecha de ingreso si se pierde el control |
| La carpeta `_apartados` (en Bronze) | Los Excel apartados; se pueden borrar a mano cuando ya no se necesiten |
| `contratos.parquet`, `contrato_barra.parquet`, `_control.json` (en Silver) | Se escriben juntos; editarlos a mano deja datos inconsistentes. Para rehacerlos, `procesar --forzar` |
| `src/`, `tests/`, `pyproject.toml`, `uv.lock` | Es el código: ver la [sección 11](#11-cuándo-hace-falta-un-programador) |
| `sql/esquema_contratos.sql` | Lo corre una vez un administrador de la base |
| `.env.example` | Es la plantilla; el que se edita es `.env` |

**No corras la rutina en dos equipos a la vez sobre las mismas carpetas.**

## 11. Cuándo hace falta un programador

Lo que **no** se resuelve en `config/` ni en el `.env`:

- El Coordinador cambia la forma de su respuesta (`api_respuesta_desconocida`), o la descarga
  deja de ser un Excel.
- Una forma nueva de escribir un punto de retiro o suministro.
- Una columna que se lee desaparece del Excel sin reemplazo, o hace falta guardar una columna
  nueva en Silver o en la base.
- Valores de energía con coma de miles.
- Cambiar una regla de negocio: la vigencia, el máximo anual como energía del contrato, el paso
  a GWh, los años aislados o "sin dato = 0".
- Un error que se repite como `error_inesperado`.

**Para el programador:**

- El código está en `src/contratos_ingesta/`.
- `CLAUDE.md` es la bitácora técnica.
- `docs/errores_verificados.md` registra los errores ya cometidos, para no repetirlos.
- `docs/aprendizaje/` son guías del código.
- Las pruebas se corren con `uv run pytest`: no tocan la red ni las carpetas reales.

## 12. Problemas conocidos

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `diagnostico` avisa "hace días que no se calcula" | La tarea diaria no está corriendo | Revisar el Programador de tareas ([4.3](#43-dejarlo-automático-programador-de-tareas-de-windows)) o correr `actualizar` |
| `estado` dice "Silver sin huella" | Silver lo hizo una versión anterior del programa | Nada: el próximo `actualizar` la anota |
| `descargar` dice "sin cambios" varios días seguidos | El Coordinador regenera su Excel cada cierto tiempo, no todos los días | Nada |
| `uv run contratos` no funciona | Se corrió desde otra carpeta | `cd` a la carpeta del programa |
| La tarea programada termina con `0x1` y no hay alerta | El programa no alcanzó a arrancar (por ejemplo, `uv` no se encontró) | Mirar `data\tarea.log` |
| Dos Excel distintos bajados en el mismo segundo tendrían el mismo nombre | El nombre lleva la hora al segundo | Nada en la rutina diaria; no correr dos descargas a la vez |

## 13. Glosario

| Término | Qué es |
|---|---|
| Coordinador (CEN) | El Coordinador Eléctrico Nacional, que publica los contratos |
| Contrato de suministro | Un acuerdo de venta de energía entre un suministrador y un cliente |
| Punto de retiro / suministro | Dónde se entrega la energía, por ejemplo `BA S/E SAN JOAQUIN (CGE) 13.2KV C2` |
| Vigente | Su fecha de término es hoy o posterior |
| Fecha de término efectiva | La mayor entre "Término" y "Fecha Término Renovación" |
| Fecha de ingreso | El primer día en que el contrato apareció en los datos |
| Bronze | Los Excel tal como los entrega el Coordinador |
| Silver | Las tablas limpias: `contratos.parquet` y `contrato_barra.parquet` |
| Manifiesto | `manifiesto.json`: la lista de los Excel bajados |
| Huella | Lo que identifica con qué Excel y qué configuración se hizo Silver; si cambia, Silver se rehace |
| TOML | El formato de los archivos de `config/`: secciones entre `[ ]` y líneas `campo = valor` |
| Alerta | Un mensaje con qué pasó, qué hacer y su tipo ([sección 7](#7-fichas-de-alertas)) |
| GWh / MWh | Unidades de energía: 1 GWh = 1.000 MWh. El Excel trae MWh; Silver guarda GWh |
