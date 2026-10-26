"""Archivo EDITABLE de la forma del Excel de contratos: `config/excel.toml`.

Antes esto vivía en el código: `silver.py` (HOJA, header=1, TEXTOS, FECHAS, PUNTOS),
`deriva.py` (COLUMNAS_CONOCIDAS, ANIO_MIN/ANIO_MAX, COLUMNAS_FECHA, la expresión
`^(Energía|Potencia) (\\d{4})$`) y `dominio/fechas.py` (FORMATOS, en la notación de
strptime). Ahora se escribe con plantillas legibles:

    Energía {año}            en vez de  ^(Energía|Potencia) (\\d{4})$
    DD-MM-AAAA               en vez de  %d-%m-%Y

Las columnas de Silver (la izquierda de [columnas.texto], [columnas.fecha] y
[columnas.puntos]) y su orden SÍ están en el código: de ellas dependen las tablas y la
base de datos. Lo editable es de qué columna del Excel sale cada una.

Al cargar se valida todo y un error se informa con su ubicación: cada ejemplo tiene que
calzar con alguna plantilla (y cada ejemplo de fecha, dar la fecha que dice), y cada
plantilla tiene que tener al menos un ejemplo que la pruebe.
"""

import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import TypedDict

from contratos_ingesta import toml_editable as t

RUTA_POR_DEFECTO = t.CARPETA / "excel.toml"

#: Las columnas de Silver, en su orden. No son editables: las usan las tablas y la base.
SILVER_TEXTO = (
    "id_contrato", "suministrador", "rut_suministrador", "tipo_suministrador", "tipo_contrato",
    "red_distribuidora", "tipo_cliente", "cliente", "rut_cliente", "estado_fuente", "region",
    "sector_economico", "subsector_economico",
)  # fmt: skip
SILVER_FECHA = ("fecha_suscripcion", "fecha_inicio", "fecha_termino", "fecha_termino_renovacion")
SILVER_PUNTOS = ("retiro", "suministro")
MAGNITUDES = ("energia", "potencia")

MARCA_ANIO = "{año}"
#: Marcador de las formas de fecha -> el de strptime. Distingue mayúsculas (MM mes, mm minuto).
MARCAS_FECHA = {"AAAA": "%Y", "MM": "%m", "DD": "%d", "hh": "%H", "mm": "%M", "ss": "%S"}


class ErrorExcel(ValueError):
    """El archivo de la forma del Excel tiene un error. El mensaje dice cuál y dónde."""


class FormatoExcel(TypedDict):
    ruta: str
    hoja: str
    fila_encabezado: int  # como se ve en Excel: 1 = la primera fila
    conocidas: list[str]
    #: columna del Excel -> columna de Silver, en el orden de Silver
    texto: dict[str, str]
    fecha: dict[str, str]
    puntos: dict[str, str]
    plantillas_por_anio: dict[str, str]  # magnitud -> "Energía {año}"
    #: magnitud -> expresión del nombre EXACTO (la revisión de deriva); grupo 1 = el año
    por_anio: dict[str, re.Pattern[str]]
    #: magnitud -> lo mismo sobre el nombre sin tildes ni mayúsculas (la lectura de Silver)
    por_anio_tolerante: dict[str, re.Pattern[str]]
    anio_min: int
    anio_max: int
    formas_fecha: list[str]  # en la notación de strptime, en el orden en que se prueban
    #: sha256 de lo que cambia el CONTENIDO de Silver (hoja, encabezado, de qué columna sale
    #: cada una, plantillas de año, formas de fecha). Lo que solo avisa (conocidas, rango de
    #: años, ejemplos) no entra: cambiarlo no rehace Silver.
    huella_silver: str


def sin_tildes(texto: str) -> str:
    """'  Región  Metropolitana' -> 'region metropolitana'. Así se comparan los nombres."""
    base = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).lower().split())


def _normal(parte: str) -> str:
    """Como `sin_tildes`, pero sin quitar los espacios de las puntas (es un trozo de plantilla)."""
    base = unicodedata.normalize("NFKD", parte)
    return re.sub(r"\s+", " ", "".join(c for c in base if not unicodedata.combining(c)).lower())


# ------------------------------------------------------------------ plantillas


def compilar_anio(plantilla: str, donde: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """'Energía {año}' -> (expresión exacta, expresión sin tildes). Grupo 1 = el año."""
    if plantilla.count(MARCA_ANIO) != 1:
        raise ErrorExcel(
            f"la plantilla {plantilla!r} tiene que llevar {MARCA_ANIO} una vez ({donde})"
        )
    antes, despues = plantilla.split(MARCA_ANIO)
    if any(c in antes + despues for c in "{}"):
        raise ErrorExcel(
            f"la plantilla {plantilla!r} tiene un marcador desconocido ({donde}). "
            f"El único que se puede usar es {MARCA_ANIO}"
        )
    exacta = re.compile("^" + re.escape(antes) + r"(\d{4})" + re.escape(despues) + "$")
    tolerante = re.compile(
        "^" + re.escape(_normal(antes)) + r"(\d{4})" + re.escape(_normal(despues)) + "$"
    )
    return exacta, tolerante


def traducir_forma(forma: str, donde: str) -> str:
    """'DD-MM-AAAA' -> '%d-%m-%Y'. Exige día, mes y año una vez cada uno."""
    for marca, que in (("AAAA", "el año"), ("MM", "el mes"), ("DD", "el día")):
        if forma.count(marca) != 1:
            raise ErrorExcel(
                f"la forma {forma!r} tiene que llevar {marca} ({que}) una vez ({donde})"
            )
    partes: list[str] = []
    i = 0
    while i < len(forma):
        encontrada = next((m for m in MARCAS_FECHA if forma.startswith(m, i)), None)
        if encontrada is not None:
            partes.append(MARCAS_FECHA[encontrada])
            i += len(encontrada)
            continue
        if forma[i].isalpha():
            raise ErrorExcel(
                f"la forma {forma!r} tiene la letra {forma[i]!r}, que no es un marcador "
                f"({donde}). Se pueden usar: AAAA MM DD hh mm ss (distingue mayúsculas: "
                "MM es el mes y mm el minuto)"
            )
        partes.append("%%" if forma[i] == "%" else forma[i])
        i += 1
    return "".join(partes)


def leer_texto_fecha(texto: str, formas: list[str]) -> tuple[date, int] | None:
    """(fecha, número de la forma que la leyó) o None si ninguna calza."""
    for i, formato in enumerate(formas):
        try:
            return datetime.strptime(texto, formato).date(), i
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ secciones


def _hoja(datos: dict[str, object], archivo: str) -> tuple[str, int]:
    h = t.tabla(datos, "hoja", archivo, ErrorExcel)
    donde = f"[hoja] de {archivo}"
    return t.texto(h, "nombre", donde, ErrorExcel), t.entero(
        h, "fila_encabezado", donde, ErrorExcel, 1, 100
    )


def _mapa(
    columnas: dict[str, object],
    seccion: str,
    silver: tuple[str, ...],
    conocidas: list[str],
    archivo: str,
) -> list[tuple[str, str]]:
    """[columnas.<seccion>]: columna de Silver = columna del Excel -> [(Excel, Silver)].

    Una lista y no un diccionario: con un diccionario, la misma columna del Excel escrita
    para dos columnas de Silver se pisaría y una de ellas desaparecería sin aviso.
    """
    datos = t.tabla(columnas, seccion, archivo, ErrorExcel, f"columnas.{seccion}")
    donde = f"[columnas.{seccion}] de {archivo}"
    ajenas = [k for k in datos if k not in silver]
    if ajenas:
        raise ErrorExcel(
            f"{ajenas} no son columnas de Silver en {donde}. Las de esta sección son: "
            f"{', '.join(silver)}. El nombre de la izquierda no se cambia; el de la columna del "
            "Excel va a la derecha, entre comillas."
        )
    faltan = [k for k in silver if k not in datos]
    if faltan:
        raise ErrorExcel(f"faltan {faltan} en {donde}: cada columna de Silver necesita su línea")
    normales = {sin_tildes(c) for c in conocidas}
    pares: list[tuple[str, str]] = []
    for destino in silver:  # el orden de Silver, no el del archivo
        origen = t.texto(datos, destino, donde, ErrorExcel)
        if sin_tildes(origen) not in normales:
            raise ErrorExcel(
                f"{destino} = {origen!r} en {donde}: esa columna no está en 'conocidas' de "
                f"[columnas]. Si es el nombre nuevo de la columna, cámbialo también ahí."
            )
        pares.append((origen, destino))
    return pares


def _por_anio(
    columnas: dict[str, object], archivo: str
) -> tuple[dict[str, str], dict[str, re.Pattern[str]], dict[str, re.Pattern[str]], int, int]:
    datos = t.tabla(columnas, "por_anio", archivo, ErrorExcel, "columnas.por_anio")
    donde = f"[columnas.por_anio] de {archivo}"
    plantillas = {m: t.texto(datos, m, donde, ErrorExcel) for m in MAGNITUDES}
    compiladas = {m: compilar_anio(p, donde) for m, p in plantillas.items()}
    ejemplos = t.textos(datos, "ejemplos", donde, ErrorExcel)
    for ejemplo in ejemplos:
        if not any(exacta.match(ejemplo) for exacta, _ in compiladas.values()):
            raise ErrorExcel(
                f"el ejemplo {ejemplo!r} no calza con ninguna plantilla ({donde}). Revisa la "
                "plantilla o el ejemplo (tienen que ser iguales, con el año en el lugar de {año})."
            )
    for m, (exacta, _) in compiladas.items():
        if not any(exacta.match(e) for e in ejemplos):
            raise ErrorExcel(
                f"la plantilla {plantillas[m]!r} no tiene ningún ejemplo que la pruebe ({donde}). "
                "Agrega a 'ejemplos' un nombre real de columna."
            )
    anio_min = t.entero(datos, "anio_min", donde, ErrorExcel, 1900, 2200)
    anio_max = t.entero(datos, "anio_max", donde, ErrorExcel, 1900, 2200)
    if anio_min > anio_max:
        raise ErrorExcel(f"anio_min ({anio_min}) es mayor que anio_max ({anio_max}) en {donde}")
    return (
        plantillas,
        {m: c[0] for m, c in compiladas.items()},
        {m: c[1] for m, c in compiladas.items()},
        anio_min,
        anio_max,
    )


def _fechas(datos: dict[str, object], archivo: str) -> list[str]:
    f = t.tabla(datos, "fechas", archivo, ErrorExcel)
    donde = f"[fechas] de {archivo}"
    formas = t.textos(f, "formas", donde, ErrorExcel)
    traducidas = [traducir_forma(forma, donde) for forma in formas]
    ejemplos = t.tabla(f, "ejemplos", archivo, ErrorExcel, "fechas.ejemplos")
    donde_e = f"[fechas.ejemplos] de {archivo}"
    if not ejemplos:
        raise ErrorExcel(f"{donde_e} está vacía: cada forma necesita un ejemplo real")
    usadas: set[int] = set()
    for texto, esperada in ejemplos.items():
        try:
            fecha = date.fromisoformat(str(esperada))
        except ValueError:
            raise ErrorExcel(
                f'"{texto}" = {esperada!r} en {donde_e}: la fecha que tiene que dar se escribe '
                'AAAA-MM-DD y entre comillas, por ejemplo "2026-09-30"'
            ) from None
        leida = leer_texto_fecha(texto, traducidas)
        if leida is None:
            raise ErrorExcel(
                f"el ejemplo {texto!r} no calza con ninguna forma de 'formas' ({donde_e}). "
                "Revisa la forma o el ejemplo."
            )
        if leida[0] != fecha:
            raise ErrorExcel(
                f"el ejemplo {texto!r} se lee como {leida[0]} con la forma "
                f"{formas[leida[1]]!r}, pero tendría que dar {fecha} ({donde_e}). Revisa el orden "
                "de DD y MM en esa forma."
            )
        usadas.add(leida[1])
    for i, forma in enumerate(formas):
        if i not in usadas:
            raise ErrorExcel(
                f"la forma {forma!r} no lee ningún ejemplo ({donde}). Agrega a [fechas.ejemplos] "
                "una fecha real escrita así, o revisa si una forma anterior ya la lee."
            )
    return traducidas


def cargar(ruta: Path | None = None) -> FormatoExcel:
    """Lee y valida el archivo de la forma del Excel. Lanza ErrorExcel con el detalle."""
    ruta = ruta or RUTA_POR_DEFECTO
    archivo = t.nombre(ruta)
    datos = t.leer(ruta, ErrorExcel)
    hoja, fila = _hoja(datos, archivo)

    columnas = t.tabla(datos, "columnas", archivo, ErrorExcel)
    donde_c = f"[columnas] de {archivo}"
    conocidas = t.textos(columnas, "conocidas", donde_c, ErrorExcel)
    normales = [sin_tildes(c) for c in conocidas]
    parecidas = sorted(
        {c for c, n in zip(conocidas, normales, strict=True) if normales.count(n) > 1}
    )
    if parecidas:
        raise ErrorExcel(
            f"'conocidas' de {donde_c} tiene columnas que solo difieren en tildes o mayúsculas: "
            f"{parecidas}. El programa las ve como la misma: deja una."
        )
    plantillas, por_anio, tolerante, anio_min, anio_max = _por_anio(columnas, archivo)
    de_anio = [c for c in conocidas if any(p.match(c) for p in por_anio.values())]
    if de_anio:
        raise ErrorExcel(
            f"{de_anio} están en 'conocidas' de {donde_c}, pero son columnas de un año: ya las "
            "cubre [columnas.por_anio]. Sácalas de 'conocidas'."
        )

    texto = _mapa(columnas, "texto", SILVER_TEXTO, conocidas, archivo)
    fecha = _mapa(columnas, "fecha", SILVER_FECHA, conocidas, archivo)
    puntos = _mapa(columnas, "puntos", SILVER_PUNTOS, conocidas, archivo)
    todas = [*texto, *fecha, *puntos]
    usadas = [sin_tildes(origen) for origen, _ in todas]
    repetidas = sorted(
        {
            f"{origen} ({destino})"
            for origen, destino in todas
            if usadas.count(sin_tildes(origen)) > 1
        }
    )
    if repetidas:
        raise ErrorExcel(
            f"una misma columna del Excel se usa para más de una columna de Silver en {donde_c}: "
            f"{repetidas}. Cada columna del Excel va una sola vez."
        )
    formas = _fechas(datos, archivo)
    return {
        "ruta": str(ruta),
        "hoja": hoja,
        "fila_encabezado": fila,
        "conocidas": conocidas,
        "texto": dict(texto),
        "fecha": dict(fecha),
        "puntos": dict(puntos),
        "plantillas_por_anio": plantillas,
        "por_anio": por_anio,
        "por_anio_tolerante": tolerante,
        "anio_min": anio_min,
        "anio_max": anio_max,
        "formas_fecha": formas,
        "huella_silver": t.huella(
            hoja, fila, texto, fecha, puntos, sorted(plantillas.items()), formas
        ),
    }


_VIGENTE: dict[str, FormatoExcel] = {}


def vigente() -> FormatoExcel:
    """La forma del Excel del proyecto, leída una vez por ejecución."""
    if "e" not in _VIGENTE:
        _VIGENTE["e"] = cargar()
    return _VIGENTE["e"]
