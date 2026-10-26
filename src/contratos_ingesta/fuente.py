"""Archivo EDITABLE de la fuente: `config/fuente.toml`.

Antes esto vivía en `bronze.py` (URL_API, PARAMS, HEADERS, REINTENTOS). Si el Coordinador
cambia la dirección o un filtro de la descarga pública, se corrige en el archivo.

Al cargar se valida todo y un error se informa con su ubicación.
"""

from pathlib import Path
from typing import TypedDict

from contratos_ingesta import toml_editable as t

RUTA_POR_DEFECTO = t.CARPETA / "fuente.toml"


class ErrorFuente(ValueError):
    """El archivo de la fuente tiene un error. El mensaje dice cuál y dónde."""


class Fuente(TypedDict):
    ruta: str
    direccion: str
    reintentos: int
    parametros: dict[str, str]  # en el orden del archivo
    encabezados: dict[str, str]


def _pares(datos: dict[str, object], donde: str, vacios: bool) -> dict[str, str]:
    pares: dict[str, str] = {}
    for clave, valor in datos.items():
        if not isinstance(valor, str):
            raise ErrorFuente(
                f"{clave} = {valor!r} en {donde}: el valor va entre comillas"
                + (', aunque esté vacío ("")' if vacios else "")
            )
        if not vacios and not valor.strip():
            raise ErrorFuente(f"{clave} está vacío en {donde}")
        if valor != valor.strip():
            raise ErrorFuente(f"{clave} tiene espacios al principio o al final en {donde}")
        pares[str(clave)] = valor
    return pares


def cargar(ruta: Path | None = None) -> Fuente:
    """Lee y valida el archivo de la fuente. Lanza ErrorFuente con el detalle."""
    ruta = ruta or RUTA_POR_DEFECTO
    archivo = t.nombre(ruta)
    datos = t.leer(ruta, ErrorFuente)
    api = t.tabla(datos, "api", archivo, ErrorFuente)
    donde = f"[api] de {archivo}"

    direccion = t.texto(api, "direccion", donde, ErrorFuente)
    if not direccion.startswith("https://"):
        raise ErrorFuente(f"'direccion' tiene que empezar con https:// en {donde}: {direccion!r}")
    if "?" in direccion:
        raise ErrorFuente(
            f'\'direccion\' no lleva "?" en {donde}: lo que va después del "?" se escribe en '
            "[api.parametros]"
        )
    parametros = t.tabla(api, "parametros", archivo, ErrorFuente, "api.parametros")
    encabezados = t.tabla(api, "encabezados", archivo, ErrorFuente, "api.encabezados")
    if not encabezados:
        raise ErrorFuente(f"[api.encabezados] de {archivo} está vacía")
    return {
        "ruta": str(ruta),
        "direccion": direccion,
        "reintentos": t.entero(api, "reintentos", donde, ErrorFuente, 1, 10),
        "parametros": _pares(parametros, f"[api.parametros] de {archivo}", vacios=True),
        "encabezados": _pares(encabezados, f"[api.encabezados] de {archivo}", vacios=False),
    }


_VIGENTE: dict[str, Fuente] = {}


def vigente() -> Fuente:
    """La fuente del proyecto, leída una vez por ejecución."""
    if "f" not in _VIGENTE:
        _VIGENTE["f"] = cargar()
    return _VIGENTE["f"]
