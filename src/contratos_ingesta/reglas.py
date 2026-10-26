"""Archivo EDITABLE de reglas que se ajustan con el tiempo: `config/reglas.toml`.

Antes esto vivía en el código: los 180 días de `cli.estado`, el "NULO" y la expresión
`\\s*\\((?:AIS|GIS)\\)$` de `dominio/puntos.py`. Las reglas de energía (RN-05 a RN-09), la
de vigencia y las 2 formas de un punto NO están aquí a propósito (decisión del usuario,
2026-10-26): cambian el significado de los datos.

Al cargar se valida todo y un error se informa con su ubicación.
"""

import re
from pathlib import Path
from typing import TypedDict

from contratos_ingesta import toml_editable as t

RUTA_POR_DEFECTO = t.CARPETA / "reglas.toml"


class ErrorReglas(ValueError):
    """El archivo de reglas tiene un error. El mensaje dice cuál y dónde."""


class Reglas(TypedDict):
    ruta: str
    dias_por_vencer: int
    vacios: frozenset[str]  # en mayúsculas y con los espacios normalizados
    sufijos: list[str]
    re_sufijo: re.Pattern[str]  # un sufijo al final, con los espacios de antes
    #: sha256 de lo que cambia el CONTENIDO de Silver ([puntos]). Los días de aviso no entran.
    huella_silver: str


def _puntos(
    datos: dict[str, object], archivo: str
) -> tuple[frozenset[str], list[str], re.Pattern[str]]:
    p = t.tabla(datos, "puntos", archivo, ErrorReglas)
    donde = f"[puntos] de {archivo}"
    vacios = t.textos(p, "vacios", donde, ErrorReglas)
    con_punto_y_coma = [v for v in vacios if ";" in v]
    if con_punto_y_coma:
        raise ErrorReglas(
            f"'vacios' de {donde} no puede llevar ';' (separa los puntos): {con_punto_y_coma}"
        )
    sufijos = t.textos(p, "sufijos_que_se_quitan", donde, ErrorReglas)
    ejemplos = t.textos(p, "ejemplos", donde, ErrorReglas)
    patron = re.compile(r"\s*(?:" + "|".join(re.escape(s) for s in sufijos) + r")$", re.IGNORECASE)
    for ejemplo in ejemplos:
        if not patron.search(ejemplo):
            raise ErrorReglas(
                f"el ejemplo {ejemplo!r} no termina con ningún texto de 'sufijos_que_se_quitan' "
                f"({donde}). Revisa el sufijo o el ejemplo."
            )
    for sufijo in sufijos:
        if not any(e.upper().endswith(sufijo.upper()) for e in ejemplos):
            raise ErrorReglas(
                f"el sufijo {sufijo!r} no tiene ningún ejemplo que termine con él ({donde}). "
                "Agrega a 'ejemplos' un punto real."
            )
    return frozenset(" ".join(v.split()).upper() for v in vacios), sufijos, patron


def cargar(ruta: Path | None = None) -> Reglas:
    """Lee y valida el archivo de reglas. Lanza ErrorReglas con el detalle."""
    ruta = ruta or RUTA_POR_DEFECTO
    archivo = t.nombre(ruta)
    datos = t.leer(ruta, ErrorReglas)
    avisos = t.tabla(datos, "avisos", archivo, ErrorReglas)
    vacios, sufijos, patron = _puntos(datos, archivo)
    return {
        "ruta": str(ruta),
        "dias_por_vencer": t.entero(
            avisos, "dias_por_vencer", f"[avisos] de {archivo}", ErrorReglas, 1, 3650
        ),
        "vacios": vacios,
        "sufijos": sufijos,
        "re_sufijo": patron,
        # los sufijos en su orden: con dos que se solapan, el primero de la lista gana
        "huella_silver": t.huella(sorted(vacios), sufijos),
    }


_VIGENTE: dict[str, Reglas] = {}


def vigente() -> Reglas:
    """Las reglas del proyecto, leídas una vez por ejecución."""
    if "r" not in _VIGENTE:
        _VIGENTE["r"] = cargar()
    return _VIGENTE["r"]
