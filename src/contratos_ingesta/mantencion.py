"""Herramientas para quien mantiene el programa sin leer el código.

- `probar_excel`: lee UN Excel real con la configuración actual de `config/` y dice si
  entraría a Silver y qué sacó. No escribe nada. Es la forma de probar un cambio en
  `config/excel.toml` o `config/reglas.toml` antes de procesar.
- `diagnostico`: revisa, una por una, las piezas de las que depende el programa (archivos
  de config, `.env`, carpetas, disco, la descarga del Coordinador y PostgreSQL) y dice qué
  hacer con cada una que falle. Es el primer paso ante cualquier problema.

Las dos devuelven datos; la CLI solo los muestra.
"""

import shutil
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, TypedDict

import httpx
import pandas as pd
import psycopg
from pydantic import ValidationError

from contratos_ingesta import (
    alertas,
    bronze,
    deriva,
    editables,
    excel,
    publicar,
    rutas,
    silver,
)
from contratos_ingesta.config import Settings, explicar

# ================================================================ probar-excel


class PruebaExcel(TypedDict):
    excel: str
    error: str | None  # por qué no se pudo leer o procesar (no entraría)
    hallazgos: list[deriva.Hallazgo]
    filas: int
    contratos: int
    vigentes: int
    sin_id: int
    ids_repetidos: int
    puntos: int
    puntos_no_reconocidos: int
    #: columna de fecha del Excel -> (fechas leídas, celdas con algo escrito)
    fechas: dict[str, tuple[int, int]]
    anios_energia: tuple[int, int] | None
    #: energía del contrato (máximo anual, GWh) de los que tienen energía: mín, máx, promedio
    energia_gwh: tuple[float, float, float] | None
    sin_energia: int
    entra: bool
    revisar: bool  # entraría, pero `procesar` terminaría con código 3


def probar_excel(ruta: Path, fecha_datos: date, hoy: date) -> PruebaExcel:
    """Lee y procesa un Excel como lo haría `procesar`, sin escribir nada."""
    if not ruta.is_file():
        raise ValueError(alertas.mensaje("archivo_no_existe", f"no existe el archivo {ruta}"))
    p: PruebaExcel = {
        "excel": ruta.name, "error": None, "hallazgos": [], "filas": 0, "contratos": 0,
        "vigentes": 0, "sin_id": 0, "ids_repetidos": 0, "puntos": 0, "puntos_no_reconocidos": 0,
        "fechas": {}, "anios_energia": None, "energia_gwh": None, "sin_energia": 0,
        "entra": False, "revisar": False,
    }  # fmt: skip
    try:
        tabla = silver.leer_excel(ruta)
    except (silver.FormatoDesconocido, OSError) as e:
        p["error"] = alertas.error(e)
        return p
    p["filas"] = len(tabla)
    p["hallazgos"] = deriva.revisar(tabla)
    try:
        contratos, puntos, conteo = silver.transformar(tabla, fecha_datos, hoy)
    except silver.FormatoDesconocido as e:
        p["error"] = str(e)
        return p

    p["contratos"], p["vigentes"] = conteo["contratos"], conteo["vigentes"]
    p["sin_id"], p["ids_repetidos"] = conteo["sin_id"], conteo["ids_repetidos"]
    p["puntos"], p["puntos_no_reconocidos"] = conteo["puntos"], conteo["puntos_no_reconocidos"]
    p["sin_energia"] = conteo["sin_energia"]
    p["hallazgos"] += silver.revision(conteo)
    forma = excel.vigente()
    for origen, destino in forma["fecha"].items():
        escritas = tabla[silver._columna(tabla, origen)].dropna().astype(str).str.strip()
        leidas = int(contratos[destino].notna().sum()) if len(contratos) else 0
        p["fechas"][origen] = (leidas, int((escritas != "").sum()))
    anios = sorted(silver._por_anio(tabla, "energia"))
    p["anios_energia"] = (anios[0], anios[-1])
    if len(contratos):
        con_energia = contratos.loc[contratos["energia_max_anual_gwh"] > 0, "energia_max_anual_gwh"]
        if len(con_energia):
            p["energia_gwh"] = (
                float(con_energia.min()),
                float(con_energia.max()),
                float(con_energia.mean()),
            )
    p["entra"] = p["contratos"] > 0
    if not p["entra"]:
        p["error"] = alertas.mensaje(
            "excel_sin_contratos", "no salió ningún contrato (todas las filas sin ID de contrato)"
        )
    p["revisar"] = any(h["severidad"] == "aviso" for h in p["hallazgos"])
    return p


# ================================================================ diagnostico

Estado = Literal["ok", "aviso", "mal"]
ORDEN_ESTADO: dict[Estado, int] = {"ok": 0, "aviso": 1, "mal": 2}

#: Menos que esto libre en un disco: aviso; menos que la décima parte: mal. Un Excel pesa
#: 1,4 MB y Silver unos 2 MB: 1 GB alcanza para años.
GB_AVISO = 1.0
#: Si la vigencia de Silver se calculó hace más días que esto, la tarea diaria no corrió.
DIAS_SIN_CALCULAR = 1


class Chequeo(TypedDict):
    tema: str
    estado: Estado
    detalle: str
    que_hacer: str


def _c(tema: str, estado: Estado, detalle: str, que_hacer: str = "") -> Chequeo:
    return {"tema": tema, "estado": estado, "detalle": detalle, "que_hacer": que_hacer}


def _configuracion() -> list[Chequeo]:
    return [
        _c(r["archivo"], "ok", r["detalle"])
        if r["ok"]
        else _c(
            r["archivo"], "mal", r["detalle"],
            "Corregir lo que dice el mensaje (o volver a la copia de config\\ hecha antes de "
            "editar) y repetir: uv run contratos revisar-config",
        )
        for r in editables.revisar()
    ]  # fmt: skip


def _escribible(carpeta: Path) -> str | None:
    """None si se puede escribir en la carpeta; si no, el error. Crea y borra un archivo."""
    prueba = carpeta / ".prueba_escritura_contratos"
    try:
        prueba.write_text("x", encoding="utf-8")
        prueba.unlink()
    except OSError as e:
        return str(e)
    return None


def _carpeta(
    tema: str, variable: str, obtener: Callable[[], Path]
) -> tuple[Path | None, list[Chequeo]]:
    """La carpeta (o None) y, si algo falla, su chequeo: que exista y se pueda escribir."""
    try:
        carpeta = obtener()
    except ValueError as e:
        return None, [_c(tema, "mal", str(e), f"Conectar la red o corregir {variable} en el .env.")]
    error = _escribible(carpeta)
    if error is not None:
        return carpeta, [
            _c(tema, "mal", f"no se puede escribir en {carpeta}: {error}",
               "Pedir permiso de escritura en esa carpeta (o elegir otra en el .env).")
        ]  # fmt: skip
    return carpeta, []


def _bronze(cfg: Settings) -> list[Chequeo]:
    base, chequeos = _carpeta("Bronze", "CONT_BRONZE_DIR", lambda: rutas.bronze(cfg))
    if base is None or chequeos:
        return chequeos
    entradas = bronze.leer_manifiesto(base)
    if not entradas:
        return [
            _c("Bronze", "aviso", f"{base}: no hay ningún Excel descargado",
               "Si es un equipo nuevo, es normal: correr uv run contratos actualizar.")
        ]  # fmt: skip
    faltan = [e["archivo"] for e in entradas if not (base / e["archivo"]).is_file()]
    ultimo = entradas[-1]
    detalle = (
        f"{base}: {len(entradas)} Excel, el último {ultimo['archivo']} "
        f"({ultimo['descargado_en'][:10]})"
    )
    if faltan:
        return [
            _c("Bronze", "aviso", f"{detalle}; faltan en la carpeta: {faltan}",
               f"Sacarlos del registro con: uv run contratos volver-a-bajar {faltan[0]}")
        ]  # fmt: skip
    return [_c("Bronze", "ok", detalle)]


def _silver(cfg: Settings, config_ok: bool, hoy: date) -> list[Chequeo]:
    destino, chequeos = _carpeta("Silver", "CONT_SILVER_DIR", lambda: rutas.silver(cfg))
    if destino is None or chequeos:
        return chequeos
    if not (destino / publicar.CONTRATOS).is_file():
        return [
            _c("Silver", "aviso", f"{destino}: vacío",
               "Correr uv run contratos actualizar (o procesar, si ya hay un Excel en Bronze).")
        ]  # fmt: skip
    tabla = pd.read_parquet(destino / publicar.CONTRATOS, columns=["fecha_calculo"])
    calculado = tabla["fecha_calculo"].iloc[0] if len(tabla) else None
    detalle = f"{destino}: {len(tabla):,} contratos, vigencia al {calculado}"
    salida: list[Chequeo] = []
    if calculado is None or calculado < hoy - timedelta(days=DIAS_SIN_CALCULAR):
        salida.append(
            _c("Silver", "aviso", f"{detalle}: hace días que no se calcula",
               "La tarea diaria no está corriendo: revisar el Programador de tareas de Windows "
               "(ver la guía) o correr uv run contratos actualizar.")
        )  # fmt: skip
    previo = silver.ultimo_proceso(destino)
    if config_ok and previo is not None:
        base = rutas.bronze(cfg)
        existentes = [e for e in bronze.leer_manifiesto(base) if (base / e["archivo"]).is_file()]
        firma = silver.huella(existentes[-1]["sha256"]) if existentes else None
        if previo["huella"] != firma:
            salida.append(
                _c("Silver", "aviso", f"{detalle}: se hizo con otro Excel o con otra config/",
                   "Correr uv run contratos procesar.")
            )  # fmt: skip
    return salida or [_c("Silver", "ok", detalle)]


def _disco(carpetas: dict[str, Path]) -> list[Chequeo]:
    salida: list[Chequeo] = []
    for tema, carpeta in carpetas.items():
        if not carpeta.is_dir():
            continue
        libre = shutil.disk_usage(carpeta).free / 1024**3
        texto = f"{libre:,.1f} GB libres donde está {carpeta}"
        if libre < GB_AVISO / 10:
            salida.append(_c(f"Disco ({tema})", "mal", texto, "Liberar espacio en ese disco."))
        elif libre < GB_AVISO:
            salida.append(_c(f"Disco ({tema})", "aviso", texto, "Queda poco espacio."))
        else:
            salida.append(_c(f"Disco ({tema})", "ok", texto))
    return salida


def _fuente(cliente: httpx.Client | None) -> list[Chequeo]:
    """Pide a la API el enlace del Excel. NO baja el Excel."""
    from contratos_ingesta import fuente

    f = fuente.vigente()
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        respuesta = bronze.pedir(
            cliente, f["direccion"], params=f["parametros"], headers=f["encabezados"]
        )
        _url, edad = bronze.enlace(respuesta.json())
    except (bronze.ErrorDescarga, ValueError) as e:
        return [
            _c("Descarga del Coordinador", "mal",
               f"no responde como se espera: {str(e).splitlines()[0]}",
               "Revisar la conexión a internet y reintentar más tarde. Si sigue, ver la receta "
               "'La descarga del Coordinador cambió' de la guía (config/fuente.toml).")
        ]  # fmt: skip
    finally:
        if propio:
            cliente.close()
    edad_txt = f"; el Excel que entrega tiene {edad / 60:,.0f} horas" if edad is not None else ""
    return [_c("Descarga del Coordinador", "ok", f"responde{edad_txt}")]


def _postgres(cfg: Settings) -> list[Chequeo]:
    if cfg.pg_conexion is None:
        return [
            _c("PostgreSQL", "aviso", "CONT_PG_CONEXION no está en el .env: no se publica",
               "Solo hace falta para publicar en la base. Ver .env.example.")
        ]  # fmt: skip
    if cfg.pg_clave is None:
        return [
            _c("PostgreSQL", "mal", "falta CONT_PG_CLAVE en el .env",
               "Escribir la clave del usuario de CONT_PG_CONEXION en CONT_PG_CLAVE.")
        ]  # fmt: skip
    try:
        with psycopg.connect(
            cfg.pg_conexion, password=cfg.pg_clave.get_secret_value(), connect_timeout=10
        ) as con:
            fila = con.execute(
                "SELECT count(*), max(cargado_en)::date, "
                "(SELECT count(*) FROM contratos.contrato) FROM contratos.carga"
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        return [
            _c("PostgreSQL", "mal", "conecta, pero la base no tiene el esquema contratos",
               "Un administrador debe correr una vez sql/esquema_contratos.sql (ver la guía).")
        ]  # fmt: skip
    except psycopg.OperationalError as e:
        return [
            _c("PostgreSQL", "mal", f"no se pudo conectar: {str(e).strip()}",
               "Revisar que el servidor esté encendido, la dirección y el puerto de "
               "CONT_PG_CONEXION y la clave de CONT_PG_CLAVE.")
        ]  # fmt: skip
    except psycopg.Error as e:
        return [
            _c("PostgreSQL", "mal", f"conecta, pero falló una consulta: {str(e).strip()}",
               "Es trabajo de programador o de quien administra la base.")
        ]  # fmt: skip
    cargas, ultima, contratos = fila if fila is not None else (0, None, 0)
    return [
        _c("PostgreSQL", "ok", f"conecta; {cargas} cargas, la última el {ultima}; "
           f"{contratos:,} contratos en la base")
    ]  # fmt: skip


def _env() -> tuple[Settings | None, Chequeo]:
    archivo = Settings.model_config.get("env_file")
    hay = isinstance(archivo, str | Path) and Path(archivo).is_file()
    try:
        cfg = Settings()
    except ValidationError as e:
        return None, _c(
            ".env", "mal", explicar(e),
            "Corregir el .env (las variables válidas y su explicación están en .env.example).",
        )  # fmt: skip
    detalle = "se lee bien" if hay else "no hay .env: se usan los valores por defecto"
    return cfg, _c(".env", "ok" if hay else "aviso", detalle,
                   "" if hay else "Copiar .env.example como .env y completarlo.")  # fmt: skip


def diagnostico(
    hoy: date, con_red: bool = True, cliente: httpx.Client | None = None
) -> list[Chequeo]:
    """Todas las revisiones, en orden. `con_red=False` no consulta la API ni la base."""
    chequeos = _configuracion()
    config_ok = all(c["estado"] == "ok" for c in chequeos)
    cfg, env = _env()
    chequeos.append(env)
    if cfg is None:
        return chequeos
    try:
        datos = rutas.exigir_carpeta(cfg.data_dir, "CONT_DATA_DIR")
    except ValueError as e:
        return [*chequeos, _c("Carpeta de datos", "mal", str(e), "Crearla o corregir el .env.")]
    error = _escribible(datos)
    chequeos.append(
        _c("Carpeta de datos", "ok", str(datos))
        if error is None
        else _c("Carpeta de datos", "mal", f"no se puede escribir en {datos}: {error}",
                "Revisar los permisos de la carpeta.")
    )  # fmt: skip
    chequeos += _bronze(cfg) + _silver(cfg, config_ok, hoy)
    carpetas = {"datos": datos}
    for tema, ruta in (("Bronze", cfg.bronze_dir), ("Silver", cfg.silver_dir)):
        if ruta is not None:
            carpetas[tema] = ruta
    chequeos += _disco(carpetas)
    if con_red:
        if config_ok:
            chequeos += _fuente(cliente)
        chequeos += _postgres(cfg)
    return chequeos


def peor(chequeos: list[Chequeo]) -> Estado:
    return max((c["estado"] for c in chequeos), key=ORDEN_ESTADO.__getitem__, default="ok")
