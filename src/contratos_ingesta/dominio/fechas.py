"""Fechas del Excel de contratos y vigencia. Funciones puras.

En el Excel (verificado el 2026-10-15) las fechas llegan de dos formas:
- `Suscripción`, `Inicio`, `Término`: fecha real -> texto "AAAA-MM-DD HH:MM:SS".
- `Fecha Término Renovación`: TEXTO "DD-MM-AAAA".

Nunca se deja adivinar el orden a pandas: "05-03-2027" leído mes-primero sería el 3 de
mayo, sin ningún error, y esa fecha decide si un contrato está vigente (error A21).
"""

from datetime import date, datetime

#: Se prueban en este orden; si ninguno calza, la fecha queda vacía (no se inventa).
FORMATOS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


def leer_fecha(valor: object) -> date | None:
    """Texto o fecha del Excel -> date. Vacío o ilegible -> None."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor is None:
        return None
    texto = str(valor).strip()
    for formato in FORMATOS:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


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
