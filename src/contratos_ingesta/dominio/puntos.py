"""Puntos de retiro y suministro de un contrato. Funciones puras.

En el Excel cada contrato trae una lista separada por `;`. Formas reales (perfiladas el
2026-10-15 sobre 11.219 puntos):

| forma         | ejemplo                                 |
|---------------|-----------------------------------------|
| simple        | `CHACAHUIN 13`                          |
| Infotécnica   | `BA S/E SAN JOAQUIN (CGE) 13.2KV C2`    |
| sin punto     | `NULO` (1.536 casos)                    |

Lo que no calza con ninguna forma se conserva con el texto completo como nombre (y se
reporta), para no perder el dato. Unir estos nombres con las barras del CMg es otro paso
(homologación), con revisión humana.

Las 2 formas están aquí a propósito (decisión del usuario, 2026-10-26). Lo que significa
"sin punto" (NULO) y los sufijos que se quitan ((AIS), (GIS)) están en config/reglas.toml.
"""

import re
from typing import TypedDict

from contratos_ingesta import reglas

_INFOTECNICA = re.compile(
    r"^BA\s+S/E\s+(?P<nombre>.+?)(?:\s+\((?P<prop>[^)]*)\))?\s+"
    r"(?P<kv>\d+(?:[.,]\d+)?)\s*kv(?:\s+(?P<sec>\S+))?$",
    re.IGNORECASE,
)
_SIMPLE = re.compile(r"^(?P<nombre>.+?)\s+(?P<kv>\d+)$")


class Punto(TypedDict):
    texto: str  # tal como venía (espacios normalizados)
    subestacion: str
    propietario: str | None
    tension_kv: float | None
    seccion: str | None
    reconocido: bool  # False = no calzó con ninguna forma conocida


def separar_punto(texto: str) -> Punto | None:
    """Un punto -> sus partes. Vacío o "sin punto" (`NULO`, config/reglas.toml) -> None."""
    r = reglas.vigente()
    t = " ".join(texto.split())
    if not t or t.upper() in r["vacios"]:
        return None
    m = _INFOTECNICA.match(r["re_sufijo"].sub("", t))
    if m:
        return {
            "texto": t,
            "subestacion": m.group("nombre").strip(),
            "propietario": m.group("prop"),
            "tension_kv": float(m.group("kv").replace(",", ".")),
            "seccion": m.group("sec"),
            "reconocido": True,
        }
    m = _SIMPLE.match(t)
    if m:
        return {
            "texto": t,
            "subestacion": m.group("nombre"),
            "propietario": None,
            "tension_kv": float(m.group("kv")),
            "seccion": None,
            "reconocido": True,
        }
    return {
        "texto": t,
        "subestacion": t,
        "propietario": None,
        "tension_kv": None,
        "seccion": None,
        "reconocido": False,
    }


def separar_lista(texto: object) -> list[Punto]:
    """'A 13;B 13;NULO' -> [punto A, punto B]. Vacío o None -> []."""
    if texto is None or (isinstance(texto, float) and texto != texto):  # None o NaN
        return []
    salida = []
    for parte in str(texto).split(";"):
        punto = separar_punto(parte)
        if punto is not None:
            salida.append(punto)
    return salida
