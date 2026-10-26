"""Publicar Silver en PostgreSQL (`cmg_cen`, esquema `contratos`): reemplazo completo atómico.

ADR-C06: cada carga reemplaza las dos tablas dentro de UNA transacción. Quien consulta en
ese momento ve los datos viejos hasta el COMMIT y los nuevos después: nunca una tabla vacía
ni a medias. Si algo falla a la mitad, ROLLBACK y la base queda como estaba.

Antes de tocar la base se valida lo que llega (receta §9, A20): IDs no vacíos ni repetidos,
y cada punto apunta a un contrato que existe.

Si Silver no cambió desde la última carga (misma huella sha256), no se sube de nuevo.
"""

import hashlib
import json
from pathlib import Path
from typing import TypedDict

import pandas as pd
import psycopg

CONTRATOS = "contratos.parquet"
PUNTOS = "contrato_barra.parquet"

#: El orden de las columnas en SQL (sql/esquema_contratos.sql). Silver debe traerlas todas.
COLUMNAS_CONTRATO = [
    "id_contrato", "suministrador", "rut_suministrador", "tipo_suministrador", "tipo_contrato",
    "red_distribuidora", "tipo_cliente", "cliente", "rut_cliente", "estado_fuente", "region",
    "sector_economico", "subsector_economico", "fecha_suscripcion", "fecha_inicio",
    "fecha_termino", "fecha_termino_renovacion", "fecha_termino_efectiva", "vigente",
    "estado_distinto", "dias_para_vencer", "energia_max_anual_gwh", "energia_promedio_anual_gwh",
    "energia_min_anual_gwh", "anios_energia", "anios_aislados", "potencia_max_anual_mw",
    "fecha_datos", "fecha_calculo", "fecha_ingreso",
]  # fmt: skip
COLUMNAS_PUNTO = [
    "id_contrato", "tipo_punto", "orden", "texto", "subestacion", "propietario", "tension_kv",
    "seccion", "reconocido",
]  # fmt: skip


#: Lo que depende del DÍA y no de la fuente: no cuenta como cambio de un contrato (ADR-C07).
COLUMNAS_DEL_DIA = {"vigente", "estado_distinto", "dias_para_vencer", "fecha_calculo",
                    "fecha_datos", "fecha_ingreso"}  # fmt: skip
COLUMNAS_HISTORIAL = [c for c in COLUMNAS_CONTRATO if c not in COLUMNAS_DEL_DIA]


def sql_historial() -> str:
    """INSERT del historial: compara `contrato` (lo que había) con `contrato_nuevo` (lo que llega).

    Se arma desde la lista de columnas para que agregar una columna a la tabla no obligue a
    acordarse de agregarla aquí.
    """
    distintas = ", ".join(
        f"CASE WHEN o.{c} IS DISTINCT FROM n.{c} THEN '{c}' END" for c in COLUMNAS_HISTORIAL
    )
    objeto_o = ", ".join(f"'{c}', o.{c}" for c in COLUMNAS_HISTORIAL)
    objeto_n = ", ".join(f"'{c}', n.{c}" for c in COLUMNAS_HISTORIAL)
    return f"""
    INSERT INTO contratos.contrato_historial
        (carga_id, id_contrato, cambio, columnas, antes, despues)
    SELECT %(carga_id)s, id_contrato, cambio, columnas, antes, despues FROM (
        SELECT coalesce(n.id_contrato, o.id_contrato) AS id_contrato,
            CASE WHEN o.id_contrato IS NULL THEN 'alta'
                 WHEN n.id_contrato IS NULL THEN 'baja' ELSE 'cambio' END AS cambio,
            CASE WHEN o.id_contrato IS NULL OR n.id_contrato IS NULL THEN '{{}}'::text[]
                 ELSE array_remove(ARRAY[{distintas}], NULL) END AS columnas,
            CASE WHEN o.id_contrato IS NOT NULL THEN jsonb_build_object({objeto_o}) END AS antes,
            CASE WHEN n.id_contrato IS NOT NULL THEN jsonb_build_object({objeto_n}) END AS despues
        FROM contratos.contrato o
        FULL JOIN contratos.contrato_nuevo n ON n.id_contrato = o.id_contrato
    ) x
    WHERE cambio <> 'cambio' OR cardinality(columnas) > 0
    """


class DatosInvalidos(ValueError):
    """Silver no cumple lo mínimo para subirlo: no se toca la base."""


class Resultado(TypedDict):
    subido: bool  # False = Silver igual a la última carga
    contratos: int
    puntos: int
    huella: str
    historial: int  # filas agregadas al historial en esta carga (altas, cambios, bajas)


def huella(silver: Path) -> str:
    """sha256 de los dos archivos de Silver juntos: si no cambia, no hay nada nuevo que subir."""
    h = hashlib.sha256()
    for nombre in (CONTRATOS, PUNTOS):
        h.update((silver / nombre).read_bytes())
    return h.hexdigest()


def _filas(tabla: pd.DataFrame, columnas: list[str]) -> list[tuple[object, ...]]:
    """Filas listas para COPY: los vacíos de pandas (NaN, NaT, <NA>) pasan a None (NULL)."""
    faltan = [c for c in columnas if c not in tabla.columns]
    if faltan:
        raise DatosInvalidos(f"a Silver le faltan columnas: {faltan}. Corre `contratos procesar`.")
    limpia = tabla[columnas].astype(object).where(tabla[columnas].notna(), None)
    return [tuple(fila) for fila in limpia.itertuples(index=False, name=None)]


def validar(contratos: pd.DataFrame, puntos: pd.DataFrame) -> None:
    """Lo mínimo antes de tocar la base (A20: cada capa valida lo que recibe)."""
    if contratos.empty:
        raise DatosInvalidos(
            "Silver no tiene contratos: no se reemplaza la base con una tabla vacía."
        )
    ids = contratos["id_contrato"]
    if ids.isna().any():
        raise DatosInvalidos(f"{int(ids.isna().sum())} contratos sin ID")
    if ids.duplicated().any():
        repetidos = sorted(ids[ids.duplicated()].unique())[:10]
        raise DatosInvalidos(f"IDs de contrato repetidos: {repetidos}")
    huerfanos = set(puntos["id_contrato"]) - set(ids)
    if huerfanos:
        raise DatosInvalidos(f"puntos de contratos que no existen: {sorted(huerfanos)[:10]}")


def _origen(silver: Path) -> str:
    """El Excel de Bronze del que salió Silver (lo anota `silver.escribir` en _control.json)."""
    control = silver / "_control.json"
    if not control.is_file():
        return "(desconocido)"
    return str(json.loads(control.read_text(encoding="utf-8")).get("origen", "(desconocido)"))


def ultima_huella(con: psycopg.Connection) -> str | None:
    fila = con.execute(
        "SELECT sha256_silver FROM contratos.carga ORDER BY carga_id DESC LIMIT 1"
    ).fetchone()
    return None if fila is None else str(fila[0])


def publicar(con: psycopg.Connection, silver: Path, forzar: bool = False) -> Resultado:
    """Silver -> PostgreSQL, en UNA transacción. Devuelve qué se hizo."""
    contratos = pd.read_parquet(silver / CONTRATOS)
    puntos = pd.read_parquet(silver / PUNTOS)
    validar(contratos, puntos)
    filas_c = _filas(contratos, COLUMNAS_CONTRATO)
    filas_p = _filas(puntos, COLUMNAS_PUNTO)
    actual = huella(silver)
    resultado: Resultado = {
        "subido": False, "contratos": len(filas_c), "puntos": len(filas_p), "huella": actual,
        "historial": 0,
    }  # fmt: skip
    if not forzar and ultima_huella(con) == actual:
        return resultado

    columnas_c = ", ".join(COLUMNAS_CONTRATO)
    with con.transaction():
        fila = con.execute(
            "INSERT INTO contratos.carga (fecha_datos, archivo_origen, sha256_silver, contratos,"
            " puntos) VALUES (%s, %s, %s, %s, %s) RETURNING carga_id",
            (contratos["fecha_datos"].iloc[0], _origen(silver), actual, len(filas_c), len(filas_p)),
        ).fetchone()
        assert fila is not None
        carga_id = int(fila[0])
        # 1) lo nuevo a la tabla de paso
        con.execute("TRUNCATE contratos.contrato_nuevo")
        with con.cursor() as cur:
            with cur.copy(f"COPY contratos.contrato_nuevo ({columnas_c}) FROM STDIN") as copia:
                for f in filas_c:
                    copia.write_row(f)
        # 2) historial: qué apareció, qué cambió y qué desapareció (mejora 8.3)
        resultado["historial"] = con.execute(sql_historial(), {"carga_id": carga_id}).rowcount
        # 3) reemplazo. DELETE y no TRUNCATE en las tablas que se consultan: quien está leyendo
        #    sigue viendo los datos viejos hasta el COMMIT (MVCC).
        con.execute("DELETE FROM contratos.contrato_barra")
        con.execute("DELETE FROM contratos.contrato")
        con.execute(
            f"INSERT INTO contratos.contrato ({columnas_c}) "
            f"SELECT {columnas_c} FROM contratos.contrato_nuevo"
        )
        with con.cursor() as cur:
            with cur.copy(
                f"COPY contratos.contrato_barra ({', '.join(COLUMNAS_PUNTO)}) FROM STDIN"
            ) as copia:
                for f in filas_p:
                    copia.write_row(f)
        con.execute("TRUNCATE contratos.contrato_nuevo")
    resultado["subido"] = True
    return resultado
