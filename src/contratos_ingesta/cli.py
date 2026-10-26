"""Línea de comandos `contratos`.

    uv run contratos actualizar      # descargar + procesar + publicar-sql (tarea diaria)
    uv run contratos descargar       # API -> Bronze, solo si el Excel cambió
    uv run contratos procesar        # último Excel de Bronze -> Silver (si no está al día)
    uv run contratos publicar-sql    # Silver -> PostgreSQL, si cambió
    uv run contratos estado          # qué hay en Bronze y en Silver
    uv run contratos revisar-config  # revisa los archivos de config/
    uv run contratos probar-excel    # prueba un Excel con config/ sin escribir nada
    uv run contratos diagnostico     # revisa todo y dice qué hacer
    uv run contratos volver-a-bajar  # aparta un Excel de Bronze para bajarlo de nuevo

Antes de cualquier comando se validan los archivos de config/ (salvo revisar-config y
diagnostico, que sirven para arreglarlos).

Códigos de salida (A15: click ya usa el 2 para sus errores de uso):
0 bien · 1 no se pudo cumplir · 2 comando mal escrito · 3 terminó con algo que revisar.
"""

import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import pandas as pd
import psycopg
import typer
from pydantic import ValidationError

from contratos_ingesta import (
    alertas,
    bitacora,
    bronze,
    deriva,
    editables,
    mantencion,
    publicar,
    reglas,
    rutas,
    silver,
)
from contratos_ingesta.config import Settings, explicar

OK, ERROR, USO, REVISAR = 0, 1, 2, 3

app = typer.Typer(help="Contratos de suministro del CEN: Bronze -> Silver.", no_args_is_help=True)


#: Comandos que funcionan aunque un archivo de config/ esté mal: son para arreglarlo.
SIN_EXIGIR_CONFIG = {"revisar-config", "diagnostico"}
#: Herramientas que se corren a mano y muestran todo en pantalla: no dejan archivo de alerta.
SIN_ALERTA = {"revisar-config", "diagnostico", "probar-excel"}


def _salir(codigo: int, mensaje: str | None = None) -> NoReturn:
    if mensaje:
        bitacora.decir(mensaje, error=codigo not in (OK, REVISAR))
    raise typer.Exit(codigo)


def _config() -> Settings:
    try:
        return Settings()
    except ValidationError as e:  # nunca `{e}` entero: trae los valores leídos, clave incluida
        _salir(ERROR, alertas.mensaje("env_invalido", f"el .env está mal escrito:\n{explicar(e)}"))


@app.callback()
def principal(contexto: typer.Context) -> None:
    """Contratos de suministro del CEN: Bronze -> Silver -> PostgreSQL.

    Antes de cualquier comando se leen los archivos de config/: uno mal escrito detiene todo
    con su mensaje, antes de descargar o escribir nada.
    """
    if contexto.invoked_subcommand in SIN_EXIGIR_CONFIG or contexto.resilient_parsing:
        return
    editables.olvidar()  # cada corrida lee los archivos de nuevo
    try:
        editables.exigir()
    except ValueError as e:
        _salir(
            ERROR, alertas.mensaje("config_invalida", f"Error en un archivo de configuración: {e}")
        )


def fecha_del_archivo(ruta: Path) -> date:
    """La fecha de los datos sale del nombre que puso Bronze: Contratos_publica_AAAAMMDD_HHMMSS."""
    m = re.search(r"_(\d{8})_\d{6}\.xlsx$", ruta.name)
    if not m:
        raise ValueError(
            alertas.mensaje(
                "excel_nombre_sin_fecha", f"el nombre {ruta.name} no trae la fecha de los datos"
            )
        )
    return datetime.strptime(m.group(1), "%Y%m%d").date()


@app.command()
def descargar() -> None:
    """Baja el Excel de contratos a Bronze. Si no cambió, no guarda otra copia."""
    cfg = _config()
    try:
        res = bronze.descargar(rutas.bronze(cfg))
    except (bronze.ErrorDescarga, ValueError, OSError) as e:
        _salir(ERROR, "No se pudo descargar: " + alertas.error(e))
    estado = "nuevo" if res["nuevo"] else "sin cambios desde el último"
    _salir(OK, f"Bronze: {res['ruta'].name} ({estado}).")


def _hoy() -> date:
    """El día de la vigencia (aparte, para que las pruebas lo puedan fijar)."""
    return date.today()


@app.command()
def procesar(
    archivo: Annotated[
        Path | None, typer.Option(help="Un Excel de Bronze en particular (por defecto, el último).")
    ] = None,
    forzar: Annotated[
        bool,
        typer.Option(help="Rehace Silver aunque ya esté al día (mismo Excel, misma config, hoy)."),
    ] = False,
) -> None:
    """Excel de Bronze -> Silver (contratos + contrato_barra). Si ya está al día, no rehace nada."""
    cfg = _config()
    if archivo is not None and not archivo.is_file():
        _salir(USO, f"Error de uso: no existe el archivo {archivo}")
    hoy = _hoy()
    try:
        ruta = archivo or bronze.ultimo(rutas.bronze(cfg))
        if ruta is None:
            _salir(ERROR, alertas.mensaje("bronze_vacio", "Bronze está vacío: no hay Excel"))
        destino = rutas.silver(cfg)
        firma = silver.huella(silver.sha256(ruta))
        previo = silver.ultimo_proceso(destino)
        if not forzar and previo is not None and silver.al_dia(previo, firma, hoy):
            bitacora.decir(
                f"Silver ya está al día: se hizo hoy con {ruta.name} y la misma configuración. "
                "No se rehace (para rehacerlo igual: `contratos procesar --forzar`). Lo que "
                "informó:"
            )
            for linea in previo["lineas"]:
                bitacora.decir(linea)
            _salir(REVISAR if previo["revisar"] else OK)
        dia = fecha_del_archivo(ruta)
        bitacora.decir(f"Procesando {ruta.name} (datos del {dia})...")
        tabla = silver.leer_excel(ruta)
        hallazgos = deriva.revisar(tabla)  # mejora 8.7: ¿cambió la forma del Excel?
        contratos, puntos, conteo = silver.transformar(tabla, dia, hoy)
        conocidas = silver.leer_control(destino)
        if conocidas is None:  # mejora 8.2: el control falta o está dañado
            excels = [(fecha_del_archivo(p), p) for p in bronze.todos(rutas.bronze(cfg))]
            if len(excels) > 1:
                aviso = alertas.hallazgo(
                    "control_reconstruido",
                    "info",
                    f"no hay control de fechas de ingreso en Silver; se reconstruye desde "
                    f"{len(excels)} Excel de Bronze",
                )
                for linea in alertas.lineas(aviso):
                    bitacora.decir(linea)
            conocidas = silver.reconstruir_fecha_ingreso(excels)
        contratos, fechas = silver.marcar_fecha_ingreso(contratos, conocidas, dia)
        lineas = [
            f"Silver: {conteo['contratos']:,} contratos ({conteo['vigentes']:,} vigentes), "
            f"{conteo['puntos']:,} puntos."
        ]
        hallazgos = silver.revision(conteo) + hallazgos
        for h in hallazgos:
            lineas += alertas.lineas(h)
        revisar = any(h["severidad"] == "aviso" for h in hallazgos)
        proceso: silver.Proceso = {
            "huella": firma, "calculado": hoy.isoformat(), "lineas": lineas, "revisar": revisar
        }  # fmt: skip
        silver.escribir(destino, contratos, puntos, fechas, ruta.name, conteo, proceso)
    except (silver.FormatoDesconocido, ValueError, OSError) as e:
        _salir(ERROR, "No se pudo procesar: " + alertas.error(e))
    for linea in lineas:
        bitacora.decir(linea)
    _salir(REVISAR if revisar else OK)


@app.command(name="publicar-sql")
def publicar_sql(
    forzar: Annotated[bool, typer.Option(help="Sube aunque Silver no haya cambiado.")] = False,
) -> None:
    """Silver -> PostgreSQL (cmg_cen, esquema contratos), reemplazo completo en UNA transacción."""
    cfg = _config()
    if cfg.pg_conexion is None or cfg.pg_clave is None:
        _salir(
            ERROR,
            alertas.mensaje(
                "pg_sin_configurar", "falta CONT_PG_CONEXION o CONT_PG_CLAVE en el .env"
            ),
        )
    try:
        destino = rutas.silver(cfg)
        if not (destino / publicar.CONTRATOS).is_file():
            _salir(
                ERROR, alertas.mensaje("silver_vacio", "Silver está vacío: no hay nada que subir")
            )
        with psycopg.connect(
            cfg.pg_conexion, password=cfg.pg_clave.get_secret_value(), connect_timeout=15
        ) as con:
            res = publicar.publicar(con, destino, forzar)
    except publicar.DatosInvalidos as e:
        _salir(ERROR, "No se subió nada (Silver no pasó la validación): " + alertas.error(e))
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn) as e:
        _salir(
            ERROR,
            alertas.mensaje(
                "pg_esquema_antiguo",
                f"No se pudo publicar: {str(e).strip()}. La base es de una versión anterior.",
            ),
        )
    except psycopg.Error as e:
        _salir(ERROR, alertas.mensaje("pg_error", f"No se pudo publicar: {str(e).strip()}"))
    except (ValueError, OSError) as e:
        _salir(ERROR, "No se pudo publicar: " + alertas.error(e))
    if res["subido"]:
        _salir(
            OK,
            f"SQL: {res['contratos']:,} contratos y {res['puntos']:,} puntos reemplazados; "
            f"{res['historial']:,} cambio(s) anotado(s) en el historial.",
        )
    _salir(OK, "SQL: sin cambios desde la última carga (usa --forzar para subir igual).")


def _paso(titulo: str, correr: Callable[[], None]) -> int:
    """Corre un comando como paso de `actualizar` y devuelve su código de salida."""
    bitacora.decir(f"\n=== {titulo} ===")
    try:
        correr()
    except typer.Exit as fin:
        return int(fin.exit_code)
    return OK


@app.command()
def actualizar() -> None:
    """Todo al día en un paso: descargar, procesar y publicar-sql. Para la tarea diaria.

    1. Baja el Excel (solo guarda otra copia si cambió).
    2. Pasa a Silver el último Excel (si no está al día).
    3. Si hay CONT_PG_CONEXION en el .env, sube Silver a PostgreSQL (si cambió).

    Si un paso falla, los siguientes se corren igual con lo que haya (sin red, igual se
    recalcula la vigencia con el último Excel). Sale con el peor código: 1 si algún paso
    falló, 3 si hay algo que revisar, 0 si todo bien.
    """
    cfg = _config()
    codigos = {
        "Descarga": _paso("1/3 Descarga", descargar),
        "Silver": _paso("2/3 Silver", lambda: procesar(archivo=None, forzar=False)),
    }
    if cfg.pg_conexion is not None:
        codigos["PostgreSQL"] = _paso("3/3 PostgreSQL", lambda: publicar_sql(forzar=False))
    else:
        bitacora.decir("\n=== 3/3 PostgreSQL ===\nSe omite: no hay CONT_PG_CONEXION en el .env.")
    bitacora.decir("\n=== Resumen ===")
    for paso, codigo in codigos.items():
        bitacora.decir(f"  {paso:<11} {bitacora.NOMBRES.get(codigo, f'código {codigo}')}")
    if ERROR in codigos.values() or USO in codigos.values():
        _salir(ERROR)
    _salir(REVISAR if REVISAR in codigos.values() else OK)


@app.command()
def estado() -> None:
    """Qué hay en Bronze y en Silver, y si Silver está al día con el último Excel y config/."""
    cfg = _config()
    try:
        base = rutas.bronze(cfg)
        entradas = bronze.leer_manifiesto(base)
        destino = rutas.silver(cfg)
        dias = reglas.vigente()["dias_por_vencer"]
        existentes = [e for e in entradas if (base / e["archivo"]).is_file()]
        firma = silver.huella(existentes[-1]["sha256"]) if existentes else None
    except ValueError as e:
        _salir(ERROR, alertas.error(e))
    bitacora.decir(f"Bronze: {len(entradas)} Excel distinto(s).")
    for entrada in entradas[-3:]:
        bitacora.decir(f"  {entrada['archivo']}  {entrada['bytes'] / 1e6:,.1f} MB")
    if not (destino / "contratos.parquet").is_file():
        _salir(REVISAR, alertas.mensaje("silver_vacio", "Silver está vacío."))
    tabla = pd.read_parquet(destino / "contratos.parquet")
    vigentes = tabla[tabla["vigente"]]
    por_vencer = vigentes[vigentes["dias_para_vencer"] <= dias]
    bitacora.decir(
        f"Silver: {len(tabla):,} contratos, {len(vigentes):,} vigentes "
        f"(Excel del {tabla['fecha_datos'].iloc[0]}, "
        f"vigencia al {tabla['fecha_calculo'].iloc[0]}); "
        f"{len(por_vencer):,} vencen en {dias} días."
    )
    previo = silver.ultimo_proceso(destino)
    if previo is None:
        _salir(
            OK, "Silver sin huella (lo hizo una versión anterior): el próximo `procesar` la anota."
        )
    if previo["huella"] != firma:
        _salir(
            REVISAR,
            alertas.mensaje(
                "silver_no_al_dia",
                "Silver no está al día: se hizo con otro Excel o con otra configuración "
                "de config/.",
            ),
        )
    _salir(OK, "Silver está al día con el último Excel de Bronze y la configuración actual.")


# =============================================================== mantención


@app.command()
def revisar_config() -> None:
    """Revisa los archivos de config/ y dice qué corregir en cada uno.

    Se corre después de editar cualquiera de ellos. Funciona aunque estén mal escritos (es
    para eso). No consulta la red ni la base.
    """
    editables.olvidar()
    revisiones = editables.revisar()
    for r in revisiones:
        bitacora.decir(f"  [{'OK ' if r['ok'] else 'MAL'}] {r['archivo']}")
        bitacora.decir(f"        {r['detalle']}")
    if all(r["ok"] for r in revisiones):
        _salir(OK, "\nTodo bien.")
    _salir(ERROR, "\nCorrige lo marcado MAL y vuelve a correr este comando.")


@app.command()
def probar_excel(
    ruta: Annotated[
        Path | None,
        typer.Argument(help="El Excel a probar (por defecto, el último de Bronze)."),
    ] = None,
) -> None:
    """Procesa UN Excel con la configuración actual y dice si entraría a Silver. No escribe nada.

    Muestra cuántos contratos y puntos saca, cuántas fechas lee de cada columna y la energía
    (mínimo, máximo y promedio). Sirve para probar un cambio en config/excel.toml o
    config/reglas.toml antes de procesar. Sale con el código que tendría `procesar`.
    """
    cfg = _config()
    if ruta is None:
        try:
            ruta = bronze.ultimo(rutas.bronze(cfg))
        except ValueError as e:
            _salir(ERROR, alertas.error(e))
        if ruta is None:
            _salir(
                ERROR,
                alertas.mensaje(
                    "bronze_vacio",
                    "Bronze está vacío: indica un Excel (contratos probar-excel RUTA)",
                ),
            )
    try:
        fecha_datos = fecha_del_archivo(ruta)
    except ValueError:
        fecha_datos = _hoy()  # un Excel bajado a mano: su nombre no trae la fecha
    try:
        p = mantencion.probar_excel(ruta, fecha_datos, _hoy())
    except ValueError as e:
        _salir(USO, f"Error de uso: {e}")
    d = bitacora.decir
    d(f"{p['excel']}  ({p['filas']:,} filas)")
    if p["contratos"]:
        d(f"  contratos     : {p['contratos']:,} ({p['vigentes']:,} vigentes al {_hoy()})")
        d(
            f"  puntos        : {p['puntos']:,} "
            f"({p['puntos_no_reconocidos']:,} con forma desconocida)"
        )
        for columna, (leidas, escritas) in p["fechas"].items():
            d(f"  fechas        : {columna}: {leidas:,} leídas de {escritas:,} escritas")
        if p["anios_energia"]:
            d(f"  años          : energía de {p['anios_energia'][0]} a {p['anios_energia'][1]}")
        if p["energia_gwh"]:
            minimo, maximo, promedio = p["energia_gwh"]
            d(
                f"  energía [GWh] : mín {minimo:,.4f}, máx {maximo:,.4f}, "
                f"promedio {promedio:,.4f} (máximo anual de cada contrato; "
                f"{p['sin_energia']:,} sin energía)"
            )
    for h in p["hallazgos"]:
        for linea in alertas.lineas(h):
            d(linea)
    if not p["entra"]:
        _salir(ERROR, f"NO entraría a Silver: {p['error']}")
    if p["revisar"]:
        _salir(REVISAR, "\nEntraría a Silver, con algo que revisar (arriba).")
    _salir(OK, "\nEntraría a Silver.")


@app.command()
def diagnostico(
    sin_red: Annotated[
        bool, typer.Option(help="No consultar la descarga del Coordinador ni PostgreSQL.")
    ] = False,
) -> None:
    """Revisa todo aquello de lo que depende el programa y dice qué hacer si algo falla.

    Archivos de config/, el .env, las carpetas (existen y se puede escribir: crea y borra un
    archivo de prueba), el espacio en disco, la descarga del Coordinador (sin bajar el Excel)
    y PostgreSQL. Es el primer paso ante cualquier problema. Sale con 0 si todo está bien, 3
    si hay avisos y 1 si algo está mal. Funciona aunque config/ o el .env estén mal escritos.
    """
    editables.olvidar()
    chequeos = mantencion.diagnostico(_hoy(), con_red=not sin_red)
    marcas = {"ok": "OK   ", "aviso": "AVISO", "mal": "MAL  "}
    for c in chequeos:
        bitacora.decir(f"  [{marcas[c['estado']]}] {c['tema']}: {c['detalle']}")
        if c["estado"] != "ok" and c["que_hacer"]:
            bitacora.decir(f"           qué hacer: {c['que_hacer']}")
    peor = mantencion.peor(chequeos)
    if peor == "mal":
        _salir(ERROR, "\nHay algo que corregir (MAL).")
    if peor == "aviso":
        _salir(REVISAR, "\nFunciona, pero hay avisos.")
    _salir(OK, "\nTodo bien.")


@app.command()
def volver_a_bajar(
    nombre: Annotated[
        str, typer.Argument(help="Nombre del Excel de Bronze, tal como lo muestra `estado`.")
    ],
) -> None:
    """Aparta un Excel de Bronze (por ejemplo, uno dañado) para que se baje de nuevo.

    Lo saca del registro de Bronze (manifiesto.json) y lo mueve a la carpeta _apartados de
    Bronze. No borra nada. El próximo `descargar` (o `actualizar`) baja el Excel de nuevo.
    """
    cfg = _config()
    try:
        base = rutas.bronze(cfg)
    except ValueError as e:
        _salir(ERROR, alertas.error(e))
    try:
        _entrada, destino = bronze.apartar(base, nombre)
    except KeyError:
        nombres = [e["archivo"] for e in bronze.leer_manifiesto(base)][-3:]
        _salir(
            USO,
            f"Error de uso: {nombre} no está en el registro de {base}. Copia el nombre tal como "
            f"lo muestra `contratos estado` (los últimos: {', '.join(nombres) or 'ninguno'}).",
        )
    except OSError as e:
        _salir(
            ERROR,
            alertas.mensaje(
                "apartar_fallo", f"No se pudo apartar {nombre}: {e}. No se cambió el registro."
            ),
        )
    if destino is None:
        bitacora.decir(f"  {nombre} ya no estaba en la carpeta; se sacó del registro.")
    else:
        bitacora.decir(f"  apartado en: {destino}")
    _salir(OK, "Para bajarlo de nuevo:  uv run contratos actualizar")


def main() -> None:
    """Punto de entrada de `contratos`: corre el comando, anota la bitácora y, si terminó con
    1 o 3, deja el archivo de alerta (mejora 8.5)."""
    import sys

    from contratos_ingesta.config import RAIZ_PROYECTO

    try:
        data_dir = Settings().data_dir
    except (ValidationError, ValueError):
        data_dir = RAIZ_PROYECTO / "data"  # con el .env roto, igual se intenta anotar
    bitacora.iniciar(data_dir)
    comando = "contratos " + " ".join(sys.argv[1:])
    try:
        app()  # typer siempre termina con SystemExit, con el código del comando
        codigo = OK
    except SystemExit as fin:
        codigo = fin.code if isinstance(fin.code, int) else (OK if fin.code is None else ERROR)
    manual = len(sys.argv) > 1 and sys.argv[1] in SIN_ALERTA
    if not manual and (ruta := bitacora.alertar(comando, codigo)) is not None:
        typer.echo(f"(alerta: {ruta})", err=True)
    sys.exit(codigo)
