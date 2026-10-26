"""Los tres archivos editables de `config/`: revisarlos y cargarlos todos juntos.

Cada uno tiene su módulo que lo lee y valida (`fuente`, `excel`, `reglas`) y lanza un
ValueError con un mensaje claro si algo está mal. Este módulo los junta para dos usos:

- `revisar()`: el comando `contratos revisar-config`, que dice archivo por archivo si está
  bien y, si no, qué corregir. No se detiene en el primero: muestra todos.
- `exigir()`: al empezar cualquier otro comando. Un archivo mal escrito detiene el programa
  con su mensaje, antes de descargar o escribir nada, en vez de fallar a mitad de camino.
"""

from collections.abc import Callable
from typing import TypedDict

from contratos_ingesta import excel, fuente, reglas


class Revision(TypedDict):
    archivo: str
    ok: bool
    detalle: str  # resumen si está bien; el error si está mal


def _fuente() -> str:
    f = fuente.vigente()
    return f"{f['direccion']}, {len(f['parametros'])} filtros, {f['reintentos']} intentos"


def _excel() -> str:
    e = excel.vigente()
    leidas = len(e["texto"]) + len(e["fecha"]) + len(e["puntos"])
    return (
        f"hoja '{e['hoja']}', encabezado en la fila {e['fila_encabezado']}, "
        f"{len(e['conocidas'])} columnas conocidas ({leidas} se leen), "
        f"{len(e['formas_fecha'])} formas de fecha"
    )


def _reglas() -> str:
    r = reglas.vigente()
    return (
        f"vencen en {r['dias_por_vencer']} días, {len(r['vacios'])} texto(s) de punto vacío, "
        f"{len(r['sufijos'])} sufijo(s) que se quitan"
    )


#: (archivo, cómo se carga y resume). El orden es el de la guía.
ARCHIVOS: list[tuple[str, Callable[[], str]]] = [
    ("config/fuente.toml", _fuente),
    ("config/excel.toml", _excel),
    ("config/reglas.toml", _reglas),
]


def olvidar() -> None:
    """Descarta lo ya leído: la próxima consulta vuelve a leer los archivos."""
    fuente._VIGENTE.clear()
    excel._VIGENTE.clear()
    reglas._VIGENTE.clear()


def revisar() -> list[Revision]:
    """Cada archivo, con su resumen o su error. Nunca lanza."""
    salida: list[Revision] = []
    for archivo, resumir in ARCHIVOS:
        try:
            salida.append({"archivo": archivo, "ok": True, "detalle": resumir()})
        except ValueError as e:
            salida.append({"archivo": archivo, "ok": False, "detalle": str(e)})
    return salida


def exigir() -> None:
    """Carga los tres. Lanza ValueError con el primer error encontrado."""
    for _archivo, resumir in ARCHIVOS:
        resumir()  # el mensaje de cada módulo ya dice el archivo y la sección
