"""Silver: el Excel de Bronze -> dos tablas conformadas, con las reglas de CLAUDE.md §1.4.

| tabla                    | una fila =                      | para qué                       |
|--------------------------|---------------------------------|--------------------------------|
| `contratos.parquet`      | un contrato (TODOS, ADR-C03)    | quién, con quién, hasta cuándo |
| `contrato_barra.parquet` | un punto de retiro o suministro | dónde                          |

Van separadas para no repetir la energía de un contrato en cada una de sus barras.

`fecha_ingreso` = el primer día en que el contrato apareció en la base (pedido del usuario).
Se guarda en `_control.json` y se conserva entre corridas: aunque el contrato cambie, su
fecha de ingreso no cambia. En la PRIMERA carga todos reciben la fecha de esa carga.

Datos personales: `Correo Cliente` y `Dirección Comercial` NO se leen.
"""

import json
from datetime import date
from pathlib import Path
from typing import TypedDict

import pandas as pd

from contratos_ingesta.dominio import energia, fechas, puntos

HOJA = "contratos"
CONTROL = "_control.json"

#: columna del Excel -> columna de Silver (texto)
TEXTOS = {
    "Id Contrato": "id_contrato",
    "Empresa Suministradora": "suministrador",
    "Rut Suministradora": "rut_suministrador",
    "Tipo Suministrador": "tipo_suministrador",
    "Tipo Contrato": "tipo_contrato",
    "Red Distribuidora": "red_distribuidora",
    "Tipo Cliente": "tipo_cliente",
    "Empresa Cliente": "cliente",
    "Rut Empresa Cliente": "rut_cliente",
    "Estado Contrato": "estado_fuente",
    "Región": "region",
    "Sector Económico": "sector_economico",
    "Subsector Económico": "subsector_economico",
}
FECHAS = {
    "Suscripción": "fecha_suscripcion",
    "Inicio": "fecha_inicio",
    "Término": "fecha_termino",
    "Fecha Término Renovación": "fecha_termino_renovacion",
}
PUNTOS = {"Listado de puntos de Retiro": "retiro", "Listado de puntos de Suministro": "suministro"}


class FormatoDesconocido(ValueError):
    """El Excel no tiene la forma conocida (falta una columna esperada)."""


class Conteo(TypedDict):
    contratos: int
    vigentes: int
    no_vigentes: int
    estado_distinto: int  # la vigencia calculada no coincide con 'Estado Contrato'
    sin_energia: int  # quedan en 0 (RN-09)
    anios_aislados: int  # años excluidos (RN-07)
    puntos: int
    puntos_no_reconocidos: int
    ids_repetidos: int
    sin_id: int


def _sin_tildes(texto: str) -> str:
    import unicodedata

    base = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).lower().split())


def leer_excel(ruta: Path) -> pd.DataFrame:
    """La hoja de contratos, con el encabezado real (2.a fila; la 1.a solo agrupa columnas)."""
    tabla = pd.read_excel(ruta, sheet_name=HOJA, header=1, dtype=str)
    tabla.columns = [str(c).strip() for c in tabla.columns]
    return tabla


def _columna(tabla: pd.DataFrame, nombre: str) -> str:
    """El nombre real de una columna, comparando sin tildes ni mayúsculas."""
    buscado = _sin_tildes(nombre)
    for c in tabla.columns:
        if _sin_tildes(str(c)) == buscado:
            return str(c)
    raise FormatoDesconocido(f"falta la columna {nombre!r} en el Excel de contratos")


def _por_anio(tabla: pd.DataFrame, magnitud: str) -> dict[int, str]:
    """{2026: 'Energía 2026', ...} para 'energia' o 'potencia'."""
    salida: dict[int, str] = {}
    for c in tabla.columns:
        partes = _sin_tildes(str(c)).split()
        if len(partes) == 2 and partes[0] == magnitud and partes[1].isdigit():
            salida[int(partes[1])] = str(c)
    if not salida:
        raise FormatoDesconocido(f"el Excel no trae columnas '{magnitud} AAAA'")
    return salida


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return None
    t = str(valor).strip()
    return t or None


def transformar(
    tabla: pd.DataFrame, fecha_datos: date, hoy: date
) -> tuple[pd.DataFrame, pd.DataFrame, Conteo]:
    """Excel -> (contratos, contrato_barra, conteo). Sin archivos: se prueba con datos a mano.

    - `fecha_datos`: la del Excel de Bronze (procedencia: de qué versión salió cada fila).
    - `hoy`: el día contra el que se calcula la vigencia (mejora 8.1). Antes era `fecha_datos`,
      y si el CEN no cambiaba el Excel por días, un contrato vencido seguía "vigente".
    """
    c_texto = {_columna(tabla, k): v for k, v in TEXTOS.items()}
    c_fecha = {_columna(tabla, k): v for k, v in FECHAS.items()}
    c_punto = {_columna(tabla, k): v for k, v in PUNTOS.items()}
    c_energia = _por_anio(tabla, "energia")
    c_potencia = _por_anio(tabla, "potencia")

    conteo: Conteo = {
        "contratos": 0, "vigentes": 0, "no_vigentes": 0, "estado_distinto": 0,
        "sin_energia": 0, "anios_aislados": 0, "puntos": 0, "puntos_no_reconocidos": 0,
        "ids_repetidos": 0, "sin_id": 0,
    }  # fmt: skip
    contratos: list[dict[str, object]] = []
    filas_puntos: list[dict[str, object]] = []
    for fila in tabla.to_dict(orient="records"):
        r: dict[str, object] = {
            destino: _texto(fila[origen]) for origen, destino in c_texto.items()
        }
        if r["id_contrato"] is None:
            conteo["sin_id"] += 1
            continue
        r["id_contrato"] = str(r["id_contrato"]).removesuffix(".0")
        for origen, destino in c_fecha.items():
            r[destino] = fechas.leer_fecha(fila[origen])
        termino = fechas.termino_efectivo(
            r["fecha_termino"],  # type: ignore[arg-type]
            r["fecha_termino_renovacion"],  # type: ignore[arg-type]
        )
        r["fecha_termino_efectiva"] = termino
        r["vigente"] = fechas.vigente(termino, hoy)
        r["dias_para_vencer"] = fechas.dias_para_vencer(termino, hoy)
        conteo["vigentes" if r["vigente"] else "no_vigentes"] += 1
        # Manda la fecha (decisión del usuario, 2026-10-15); `estado_distinto` marca los
        # contratos donde 'Estado Contrato' de la fuente dice otra cosa, para revisarlos.
        estado_vigente = _sin_tildes(str(r["estado_fuente"] or "")) == "vigente"
        distinto = estado_vigente != r["vigente"]
        r["estado_distinto"] = distinto
        conteo["estado_distinto"] += int(distinto)

        resumen = energia.resumir({a: energia.numero(fila[c]) for a, c in c_energia.items()})
        r["energia_max_anual_gwh"] = resumen["maximo_gwh"]
        r["energia_promedio_anual_gwh"] = resumen["promedio_gwh"]
        r["energia_min_anual_gwh"] = resumen["minimo_gwh"]
        r["anios_energia"] = ",".join(map(str, resumen["anios_usados"]))
        r["anios_aislados"] = ",".join(map(str, resumen["anios_aislados"]))
        conteo["sin_energia"] += int(not resumen["anios_usados"])
        conteo["anios_aislados"] += len(resumen["anios_aislados"])
        potencias = [p for p in (energia.numero(fila[c]) for c in c_potencia.values()) if p]
        r["potencia_max_anual_mw"] = max(potencias) if potencias else 0.0
        r["fecha_datos"] = fecha_datos
        r["fecha_calculo"] = hoy
        contratos.append(r)

        for origen, tipo_punto in c_punto.items():
            for orden, p in enumerate(puntos.separar_lista(fila[origen]), start=1):
                filas_puntos.append({"id_contrato": r["id_contrato"], "tipo_punto": tipo_punto,
                                     "orden": orden, **p})  # fmt: skip
                conteo["puntos_no_reconocidos"] += int(not p["reconocido"])

    tabla_contratos = pd.DataFrame(contratos)
    tabla_puntos = pd.DataFrame(
        filas_puntos,
        columns=["id_contrato", "tipo_punto", "orden", "texto", "subestacion", "propietario",
                 "tension_kv", "seccion", "reconocido"],
    )  # fmt: skip
    if len(tabla_contratos):  # entero con vacíos (contratos sin término), no float
        tabla_contratos["dias_para_vencer"] = tabla_contratos["dias_para_vencer"].astype("Int64")
    conteo["contratos"] = len(tabla_contratos)
    conteo["puntos"] = len(tabla_puntos)
    if len(tabla_contratos):
        conteo["ids_repetidos"] = int(tabla_contratos["id_contrato"].duplicated().sum())
    return tabla_contratos, tabla_puntos, conteo


def marcar_fecha_ingreso(
    contratos: pd.DataFrame, conocidas: dict[str, str], dia: date
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Agrega `fecha_ingreso`: la más antigua conocida, o `dia` si el contrato es nuevo.

    Si se procesa un Excel más viejo que lo ya cargado, se queda la fecha MÁS ANTIGUA.
    """
    nuevas = dict(conocidas)
    for id_contrato in contratos["id_contrato"] if len(contratos) else []:
        previa = nuevas.get(str(id_contrato))
        if previa is None or dia.isoformat() < previa:
            nuevas[str(id_contrato)] = dia.isoformat()
    if len(contratos):
        contratos = contratos.assign(
            fecha_ingreso=contratos["id_contrato"].map(lambda i: date.fromisoformat(nuevas[i]))
        )
    return contratos, nuevas


def leer_control(silver: Path) -> dict[str, str] | None:
    """{id_contrato: fecha_ingreso ISO} de las corridas anteriores.

    None = el control no existe o no se puede leer (borrado, dañado): hay que reconstruirlo
    desde Bronze (`reconstruir_fecha_ingreso`), no partir de cero en silencio (mejora 8.2).
    """
    ruta = silver / CONTROL
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))["fecha_ingreso"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(datos, dict):
        return None
    return {str(k): str(v) for k, v in datos.items()}


def ids_del_excel(ruta: Path) -> set[str]:
    """Solo la columna `Id Contrato` de un Excel de Bronze (rápido: no lee las 180 columnas)."""
    tabla = pd.read_excel(
        ruta,
        sheet_name=HOJA,
        header=1,
        dtype=str,
        usecols=lambda c: _sin_tildes(str(c)) == _sin_tildes("Id Contrato"),
    )
    if tabla.shape[1] != 1:
        raise FormatoDesconocido(f"{ruta.name}: no tiene la columna 'Id Contrato'")
    return {str(v).strip().removesuffix(".0") for v in tabla.iloc[:, 0].dropna() if str(v).strip()}


def reconstruir_fecha_ingreso(excels: list[tuple[date, Path]]) -> dict[str, str]:
    """Mejora 8.2: la fecha de ingreso de cada contrato = el Excel MÁS ANTIGUO de Bronze en que
    aparece. Se usa cuando el control se perdió; con un solo Excel, todos quedan con su fecha."""
    fechas: dict[str, str] = {}
    for dia, ruta in sorted(excels):
        for id_contrato in ids_del_excel(ruta):
            fechas.setdefault(id_contrato, dia.isoformat())
    return fechas


def escribir(
    silver: Path,
    contratos: pd.DataFrame,
    puntos_: pd.DataFrame,
    fecha_ingreso: dict[str, str],
    origen: str,
    conteo: Conteo,
) -> None:
    """Escribe las dos tablas y el control. Cada archivo: .tmp y reemplazo (atómico).

    Primero se escriben las tablas a .tmp, luego se reemplazan, y al final el control: si se
    corta antes del control, la próxima corrida recalcula lo mismo (las fechas de ingreso de
    los contratos nuevos vuelven a ser ese mismo día).
    """
    destinos = {"contratos.parquet": contratos, "contrato_barra.parquet": puntos_}
    for nombre, tabla in destinos.items():
        tabla.to_parquet(silver / (nombre + ".tmp"), index=False, compression="zstd")
    for nombre in destinos:
        (silver / (nombre + ".tmp")).replace(silver / nombre)
    control = {"origen": origen, "conteo": conteo, "fecha_ingreso": fecha_ingreso}
    tmp = silver / (CONTROL + ".tmp")
    tmp.write_text(json.dumps(control, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(silver / CONTROL)
