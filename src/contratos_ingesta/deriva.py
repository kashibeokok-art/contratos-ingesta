"""Deriva de la fuente: ¿el Excel del CEN cambió de forma? (mejora 8.7). Funciones puras.

El programa solo se detiene si falta una columna que USA. Esta revisión avisa además de lo que
cambió sin romper nada todavía, para enterarse antes de que rompa algo o, peor, de que
produzca un dato equivocado sin error (como una coma de miles leída como decimal, §7.8).

Lo conocido (las columnas fijas, las plantillas de cada año y su rango, las formas de
fecha) está en config/excel.toml. Si el CEN cambia la forma a propósito, se corrige ahí.
"""

from typing import Any

import pandas as pd

from contratos_ingesta import alertas, excel
from contratos_ingesta.dominio import energia, fechas

# `deriva.COLUMNAS_CONOCIDAS`, `ANIO_MIN`, `ANIO_MAX` y `COLUMNAS_FECHA` se siguen pudiendo
# usar: los resuelve `__getattr__`, al final del módulo.


def _anio(columna: str, forma: excel.FormatoExcel) -> int | None:
    """El año de una columna `Energía AAAA` / `Potencia AAAA` (nombre exacto), o None."""
    for patron in forma["por_anio"].values():
        if m := patron.match(columna):
            return int(m.group(1))
    return None


#: Un hallazgo: tipo, severidad (aviso = código 3; info = no), detalle y qué hacer.
Hallazgo = alertas.Hallazgo


def _ejemplos(valores: list[str], n: int = 3) -> str:
    return ", ".join(repr(v) for v in valores[:n])


def revisar(tabla: pd.DataFrame) -> list[Hallazgo]:
    """Compara la forma del Excel con la conocida. Vacío = nada distinto."""
    forma = excel.vigente()
    conocidas = forma["conocidas"]
    hallazgos: list[Hallazgo] = []
    columnas = [str(c) for c in tabla.columns]
    fijas = [c for c in columnas if _anio(c, forma) is None]

    nuevas = [c for c in fijas if c not in conocidas]
    if nuevas:
        hallazgos.append(
            alertas.hallazgo("columnas_nuevas", "aviso", f"el Excel trae columnas nuevas: {nuevas}")
        )
    faltan = [c for c in conocidas if c not in fijas]
    if faltan:
        hallazgos.append(
            alertas.hallazgo(
                "columnas_que_faltan", "aviso", f"columnas que el Excel ya no trae: {faltan}"
            )
        )

    anios = sorted({a for c in columnas if (a := _anio(c, forma)) is not None})
    fuera = [a for a in anios if not forma["anio_min"] <= a <= forma["anio_max"]]
    if fuera:
        hallazgos.append(
            alertas.hallazgo("anios_nuevos", "info", f"años nuevos en energía/potencia: {fuera}")
        )

    for columna in forma["fecha"]:
        if columna not in tabla.columns:
            continue
        valores = [str(v).strip() for v in tabla[columna].dropna() if str(v).strip()]
        ilegibles = [v for v in valores if fechas.leer_fecha(v) is None]
        if ilegibles:
            hallazgos.append(
                alertas.hallazgo(
                    "fecha_formato_desconocido",
                    "aviso",
                    f"{columna}: {len(ilegibles)} fecha(s) con un formato desconocido "
                    f"(quedan vacías), p. ej. {_ejemplos(ilegibles)}",
                )
            )

    con_coma: list[str] = []
    ilegibles_num: list[str] = []
    for columna in columnas:
        if _anio(columna, forma) is None:
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
            alertas.hallazgo(
                "energia_con_coma",
                "aviso",
                f"{len(con_coma)} valor(es) de energía/potencia con coma: se leen como "
                f"decimal; si fueran miles, el dato quedaría 1.000 veces menor. "
                f"P. ej. {_ejemplos(con_coma)}",
            )
        )
    if ilegibles_num:
        hallazgos.append(
            alertas.hallazgo(
                "energia_no_numerica",
                "aviso",
                f"{len(ilegibles_num)} valor(es) de energía/potencia que no son "
                f"números (quedan vacíos), p. ej. {_ejemplos(ilegibles_num)}",
            )
        )
    return hallazgos


def __getattr__(nombre: str) -> Any:
    """Los nombres de antes, leídos de config/excel.toml al usarlos."""
    if nombre == "COLUMNAS_CONOCIDAS":
        return tuple(excel.vigente()["conocidas"])
    if nombre == "COLUMNAS_FECHA":
        return tuple(excel.vigente()["fecha"])
    if nombre == "ANIO_MIN":
        return excel.vigente()["anio_min"]
    if nombre == "ANIO_MAX":
        return excel.vigente()["anio_max"]
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
