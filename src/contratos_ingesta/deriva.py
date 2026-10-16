"""Deriva de la fuente: ¿el Excel del CEN cambió de forma? (mejora 8.7). Funciones puras.

El programa solo se detiene si falta una columna que USA. Esta revisión avisa además de lo que
cambió sin romper nada todavía, para enterarse antes de que rompa algo o, peor, de que
produzca un dato equivocado sin error (como una coma de miles leída como decimal, §7.8).

Lo conocido son las 30 columnas fijas del Excel real (2026-10-15) + `Energía AAAA` y
`Potencia AAAA` de 1986 a 2060. Si el CEN cambia la forma a propósito, se actualiza esta lista.
"""

import re
from typing import TypedDict

import pandas as pd

from contratos_ingesta.dominio import energia, fechas

#: Las columnas fijas del Excel (encabezado de la 2.a fila), verificadas el 2026-10-15.
COLUMNAS_CONOCIDAS = (
    "Id Contrato", "Empresa Suministradora", "Rut Suministradora", "Tipo Suministrador",
    "Tipo Contrato", "Red Distribuidora", "Tipo Cliente", "Empresa Cliente", "Rut Empresa Cliente",
    "Suscripción", "Inicio", "Término", "Fecha Renovación", "Fecha Inicio Renovación",
    "Fecha Término Renovación", "Estado Contrato", "Afecto Ley", "Régimen Compra Potencia",
    "Correo Cliente", "Región", "Dirección Comercial", "Sector Económico", "Subsector Económico",
    "Listado de puntos de Suministro", "Listado de puntos de Retiro",
    "Listado de Potencia Conectada [MW]", "Listado Dirección de Referencia", "Numero Cliente",
    "Distribuidora Conectada", "Listado Región",
)  # fmt: skip
ANIO_MIN, ANIO_MAX = 1986, 2060
COLUMNAS_FECHA = ("Suscripción", "Inicio", "Término", "Fecha Término Renovación")

_POR_ANIO = re.compile(r"^(Energía|Potencia) (\d{4})$")


class Hallazgo(TypedDict):
    severidad: str  # aviso = mirarlo (termina con código 3) | info = solo informativo
    detalle: str


def _ejemplos(valores: list[str], n: int = 3) -> str:
    return ", ".join(repr(v) for v in valores[:n])


def revisar(tabla: pd.DataFrame) -> list[Hallazgo]:
    """Compara la forma del Excel con la conocida. Vacío = nada distinto."""
    hallazgos: list[Hallazgo] = []
    columnas = [str(c) for c in tabla.columns]
    fijas = [c for c in columnas if not _POR_ANIO.match(c)]

    nuevas = [c for c in fijas if c not in COLUMNAS_CONOCIDAS]
    if nuevas:
        hallazgos.append({"severidad": "aviso", "detalle": f"columnas nuevas: {nuevas}"})
    faltan = [c for c in COLUMNAS_CONOCIDAS if c not in fijas]
    if faltan:
        hallazgos.append({"severidad": "aviso", "detalle": f"columnas que ya no vienen: {faltan}"})

    anios = sorted({int(m.group(2)) for c in columnas if (m := _POR_ANIO.match(c))})
    fuera = [a for a in anios if not ANIO_MIN <= a <= ANIO_MAX]
    if fuera:
        hallazgos.append(
            {"severidad": "info", "detalle": f"años nuevos en energía/potencia: {fuera}"}
        )

    for columna in COLUMNAS_FECHA:
        if columna not in tabla.columns:
            continue
        valores = [str(v).strip() for v in tabla[columna].dropna() if str(v).strip()]
        ilegibles = [v for v in valores if fechas.leer_fecha(v) is None]
        if ilegibles:
            hallazgos.append(
                {
                    "severidad": "aviso",
                    "detalle": f"{columna}: {len(ilegibles)} fecha(s) con un formato desconocido "
                    f"(quedan vacías), p. ej. {_ejemplos(ilegibles)}",
                }
            )

    con_coma: list[str] = []
    ilegibles_num: list[str] = []
    for columna in columnas:
        if not _POR_ANIO.match(columna):
            continue
        for v in tabla[columna].dropna():
            texto = str(v).strip()
            if not texto:
                continue
            if "," in texto:
                con_coma.append(f"{columna}={texto}")
            elif energia.numero(texto) is None:
                ilegibles_num.append(f"{columna}={texto}")
    if con_coma:
        hallazgos.append(
            {
                "severidad": "aviso",
                "detalle": f"{len(con_coma)} valor(es) de energía/potencia con coma: se leen como "
                f"decimal; si fueran miles, el dato quedaría 1.000 veces menor. "
                f"P. ej. {_ejemplos(con_coma)}",
            }
        )
    if ilegibles_num:
        hallazgos.append(
            {
                "severidad": "aviso",
                "detalle": f"{len(ilegibles_num)} valor(es) de energía/potencia que no son "
                f"números (quedan vacíos), p. ej. {_ejemplos(ilegibles_num)}",
            }
        )
    return hallazgos
