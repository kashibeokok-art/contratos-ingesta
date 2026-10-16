"""Línea de comandos `contratos`.

    uv run contratos actualizar     # descargar + procesar (para la tarea programada diaria)
    uv run contratos descargar      # API -> Bronze, solo si el Excel cambió
    uv run contratos procesar       # último Excel de Bronze -> Silver
    uv run contratos estado         # qué hay en Bronze y en Silver

Códigos de salida (A15: click ya usa el 2 para sus errores de uso):
0 bien · 1 no se pudo cumplir · 2 comando mal escrito · 3 terminó con algo que revisar.
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import pandas as pd
import psycopg
import typer
from pydantic import ValidationError

from contratos_ingesta import bronze, publicar, rutas, silver
from contratos_ingesta.config import Settings

OK, ERROR, USO, REVISAR = 0, 1, 2, 3

app = typer.Typer(help="Contratos de suministro del CEN: Bronze -> Silver.", no_args_is_help=True)


def _salir(codigo: int, mensaje: str | None = None) -> NoReturn:
    if mensaje:
        typer.echo(mensaje, err=codigo not in (OK, REVISAR))
    raise typer.Exit(codigo)


def _config() -> Settings:
    try:
        return Settings()
    except (ValidationError, ValueError) as e:
        _salir(ERROR, f"Configuración inválida (.env):\n{e}")


def fecha_del_archivo(ruta: Path) -> date:
    """La fecha de los datos sale del nombre que puso Bronze: Contratos_publica_AAAAMMDD_HHMMSS."""
    m = re.search(r"_(\d{8})_\d{6}\.xlsx$", ruta.name)
    if not m:
        raise ValueError(f"el nombre {ruta.name} no trae la fecha (Contratos_publica_AAAAMMDD_...)")
    return datetime.strptime(m.group(1), "%Y%m%d").date()


@app.command()
def descargar() -> None:
    """Baja el Excel de contratos a Bronze. Si no cambió, no guarda otra copia."""
    cfg = _config()
    try:
        res = bronze.descargar(rutas.bronze(cfg))
    except (bronze.ErrorDescarga, ValueError, OSError) as e:
        _salir(ERROR, f"No se pudo descargar: {e}")
    estado = "nuevo" if res["nuevo"] else "sin cambios desde el último"
    _salir(OK, f"Bronze: {res['ruta'].name} ({estado}).")


@app.command()
def procesar(
    archivo: Annotated[
        Path | None, typer.Option(help="Un Excel de Bronze en particular (por defecto, el último).")
    ] = None,
) -> None:
    """Excel de Bronze -> Silver (contratos + contrato_barra)."""
    cfg = _config()
    if archivo is not None and not archivo.is_file():
        _salir(USO, f"Error de uso: no existe el archivo {archivo}")
    try:
        ruta = archivo or bronze.ultimo(rutas.bronze(cfg))
        if ruta is None:
            _salir(ERROR, "Bronze está vacío: corre primero `contratos descargar`.")
        destino = rutas.silver(cfg)
        dia = fecha_del_archivo(ruta)
        typer.echo(f"Procesando {ruta.name} (datos del {dia})...")
        contratos, puntos, conteo = silver.transformar(silver.leer_excel(ruta), dia, date.today())
        contratos, fechas = silver.marcar_fecha_ingreso(
            contratos, silver.leer_control(destino), dia
        )
        silver.escribir(destino, contratos, puntos, fechas, ruta.name, conteo)
    except (silver.FormatoDesconocido, ValueError, OSError) as e:
        _salir(ERROR, f"No se pudo procesar: {e}")
    typer.echo(
        f"Silver: {conteo['contratos']:,} contratos ({conteo['vigentes']:,} vigentes), "
        f"{conteo['puntos']:,} puntos."
    )
    revisar = {
        "estado_distinto": "con 'Estado Contrato' distinto de la vigencia por fecha",
        "puntos_no_reconocidos": "puntos con una forma desconocida (se conservan completos)",
        "ids_repetidos": "IDs de contrato repetidos",
        "sin_id": "filas sin ID de contrato (omitidas)",
    }
    hay = {k: v for k, v in revisar.items() if conteo[k]}  # type: ignore[literal-required]
    for clave, texto in hay.items():
        typer.echo(f"  revisar: {conteo[clave]:,} {texto}")  # type: ignore[literal-required]
    _salir(REVISAR if conteo["ids_repetidos"] or conteo["sin_id"] else OK)


@app.command(name="publicar-sql")
def publicar_sql(
    forzar: Annotated[bool, typer.Option(help="Sube aunque Silver no haya cambiado.")] = False,
) -> None:
    """Silver -> PostgreSQL (cmg_cen, esquema contratos), reemplazo completo en UNA transacción."""
    cfg = _config()
    if cfg.pg_conexion is None or cfg.pg_clave is None:
        _salir(ERROR, "Falta CONT_PG_CONEXION o CONT_PG_CLAVE en el .env (ver .env.example).")
    try:
        destino = rutas.silver(cfg)
        if not (destino / publicar.CONTRATOS).is_file():
            _salir(ERROR, "Silver está vacío: corre primero `contratos procesar`.")
        with psycopg.connect(
            cfg.pg_conexion, password=cfg.pg_clave.get_secret_value(), connect_timeout=15
        ) as con:
            res = publicar.publicar(con, destino, forzar)
    except publicar.DatosInvalidos as e:
        _salir(ERROR, f"No se subió nada (Silver no pasó la validación): {e}")
    except (psycopg.Error, ValueError, OSError) as e:
        _salir(ERROR, f"No se pudo publicar: {e}")
    if res["subido"]:
        _salir(OK, f"SQL: {res['contratos']:,} contratos y {res['puntos']:,} puntos reemplazados.")
    _salir(OK, "SQL: sin cambios desde la última carga (usa --forzar para subir igual).")


@app.command()
def actualizar() -> None:
    """descargar + procesar (+ publicar-sql si hay conexión en el .env). Tarea diaria."""
    try:
        descargar()
    except typer.Exit as fin:
        if fin.exit_code != OK:
            raise
    try:
        procesar(archivo=None)
    except typer.Exit as fin:
        if fin.exit_code != OK:
            raise
    if _config().pg_conexion is None:
        _salir(OK, "SQL: sin CONT_PG_CONEXION en el .env, no se publica.")
    publicar_sql(forzar=False)


@app.command()
def estado() -> None:
    """Qué hay en Bronze y en Silver."""
    cfg = _config()
    try:
        entradas = bronze.leer_manifiesto(rutas.bronze(cfg))
        destino = rutas.silver(cfg)
    except ValueError as e:
        _salir(ERROR, str(e))
    typer.echo(f"Bronze: {len(entradas)} Excel distinto(s).")
    for entrada in entradas[-3:]:
        typer.echo(f"  {entrada['archivo']}  {entrada['bytes'] / 1e6:,.1f} MB")
    if not (destino / "contratos.parquet").is_file():
        _salir(REVISAR, "Silver: vacío. Corre `contratos procesar`.")
    tabla = pd.read_parquet(destino / "contratos.parquet")
    vigentes = tabla[tabla["vigente"]]
    por_vencer = vigentes[vigentes["dias_para_vencer"] <= 180]
    typer.echo(
        f"Silver: {len(tabla):,} contratos, {len(vigentes):,} vigentes "
        f"(Excel del {tabla['fecha_datos'].iloc[0]}, "
        f"vigencia al {tabla['fecha_calculo'].iloc[0]}); "
        f"{len(por_vencer):,} vencen en 180 días."
    )
    _salir(OK)


def main() -> None:
    app()
