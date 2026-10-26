"""Fechas del Excel de contratos y vigencia. Funciones puras.

En el Excel (verificado el 2026-10-15) las fechas llegan de dos formas:
- `Suscripción`, `Inicio`, `Término`: fecha real -> texto "AAAA-MM-DD HH:MM:SS".
- `Fecha Término Renovación`: TEXTO "DD-MM-AAAA".

Nunca se deja adivinar el orden a pandas: "05-03-2027" leído mes-primero sería el 3 de
mayo, sin ningún error, y esa fecha decide si un contrato está vigente (error A21).

Las formas que se aceptan están en config/excel.toml ([fechas]), cada una con un ejemplo
real y la fecha que tiene que dar. `fechas.FORMATOS` se sigue pudiendo usar: lo resuelve
`__getattr__`, al final del módulo.
"""

from datetime import date, datetime
from typing import Any

from contratos_ingesta import excel


def leer_fecha(valor: object) -> date | None:
    """Texto o fecha del Excel -> date. Vacío o ilegible -> None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor is None:
        return None
    # Se prueban en el orden del archivo; si ninguna calza, queda vacía (no se inventa).
    leida = excel.leer_texto_fecha(str(valor).strip(), excel.vigente()["formas_fecha"])
    return None if leida is None else leida[0]


def termino_efectivo(termino: date | None, termino_renovacion: date | None) -> date | None:
    """El mayor entre Término y Término de renovación (contratos.md §7). None si no hay ninguno."""
    fechas = [f for f in (termino, termino_renovacion) if f is not None]
    return max(fechas) if fechas else None


def vigente(termino: date | None, dia: date) -> bool:
    """Vigente si su término efectivo es ese día o posterior. Sin término -> no vigente."""
    return termino is not None and termino >= dia


def dias_para_vencer(termino: date | None, dia: date) -> int | None:
    """Días entre `dia` y el término (negativo si ya venció). None si no hay término."""
    return None if termino is None else (termino - dia).days


def __getattr__(nombre: str) -> Any:
    """`fechas.FORMATOS`: las formas de config/excel.toml (notación de strptime), al usarlo."""
    if nombre == "FORMATOS":
        return tuple(excel.vigente()["formas_fecha"])
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
