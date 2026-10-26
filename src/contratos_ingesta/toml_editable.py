"""Lo común a los tres archivos editables de `config/`: leerlos y validar cada valor.

Cada error dice DÓNDE está (archivo y sección) y qué tiene que ir ahí, para que se
corrija sin abrir el código. `donde` es siempre algo como "[api] de config/fuente.toml".
"""

import hashlib
import tomllib
from pathlib import Path

from contratos_ingesta.config import RAIZ_PROYECTO

CARPETA = RAIZ_PROYECTO / "config"


def nombre(ruta: Path) -> str:
    """config/fuente.toml si está en el proyecto; la ruta completa si no (un archivo de prueba)."""
    try:
        return ruta.relative_to(RAIZ_PROYECTO).as_posix()
    except ValueError:
        return str(ruta)


def huella(*partes: object) -> str:
    """sha256 (16 caracteres) de lo que cambia Silver. Solo depende de los valores que se le
    pasan: un comentario o un espacio de más en el archivo no la cambian."""
    return hashlib.sha256(repr(partes).encode("utf-8")).hexdigest()[:16]


def leer(ruta: Path, error: type[ValueError]) -> dict[str, object]:
    try:
        return tomllib.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise error(
            f"no existe {nombre(ruta)}. Si se borró, recupéralo de la copia de config\\ "
            "(o de otro equipo con el programa)."
        ) from e
    except tomllib.TOMLDecodeError as e:
        raise error(
            f"{nombre(ruta)} no se puede leer ({e}). Lo típico: una comilla o un corchete sin "
            "cerrar, o un nombre repetido."
        ) from e


def tabla(
    datos: dict[str, object],
    clave: str,
    donde: str,
    error: type[ValueError],
    seccion: str | None = None,
) -> dict[str, object]:
    """La sección `clave` de `datos`. `seccion`: su nombre completo (api.parametros)."""
    valor = datos.get(clave)
    if not isinstance(valor, dict):
        raise error(f"falta la sección [{seccion or clave}] en {donde}")
    return valor


def texto(datos: dict[str, object], clave: str, donde: str, error: type[ValueError]) -> str:
    valor = datos.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise error(f"falta '{clave}' en {donde}: tiene que ser un texto entre comillas, no vacío")
    if valor != valor.strip():
        raise error(f"'{clave}' tiene espacios al principio o al final en {donde}: {valor!r}")
    return valor


def entero(
    datos: dict[str, object],
    clave: str,
    donde: str,
    error: type[ValueError],
    minimo: int,
    maximo: int | None = None,
) -> int:
    valor = datos.get(clave)
    rango = f"entre {minimo} y {maximo}" if maximo is not None else f"mayor o igual a {minimo}"
    if (
        not isinstance(valor, int)
        or isinstance(valor, bool)
        or valor < minimo
        or (maximo is not None and valor > maximo)
    ):
        raise error(
            f"'{clave}' tiene que ser un número entero {rango}, sin comillas, en {donde} "
            f"(dice {valor!r})"
        )
    return valor


def textos(datos: dict[str, object], clave: str, donde: str, error: type[ValueError]) -> list[str]:
    """Una lista no vacía de textos no vacíos, sin repetidos ni espacios sobrantes."""
    valor = datos.get(clave)
    if not isinstance(valor, list) or not valor:
        raise error(f'falta \'{clave}\' en {donde}: tiene que ser una lista ["...", "..."]')
    for v in valor:
        if not isinstance(v, str) or not v.strip():
            raise error(f"'{clave}' de {donde} tiene un valor que no es un texto: {v!r}")
        if v != v.strip():
            raise error(f"{v!r} de '{clave}' tiene espacios al principio o al final en {donde}")
    repetidos = sorted({v for v in valor if valor.count(v) > 1})
    if repetidos:
        raise error(f"'{clave}' de {donde} tiene valores repetidos: {repetidos}")
    return list(valor)
