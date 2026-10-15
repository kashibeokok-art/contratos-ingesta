"""Energía contratada por año -> resumen del contrato (RN-05, RN-07, RN-08, RN-09). Puro.

El Excel trae una columna por año (`Energía 1986` ... `Energía 2060`) en MWh, casi todas
vacías. El resumen descarta los años AISLADOS (RN-07), pasa a GWh (RN-08) y deja en 0 un
contrato sin datos (RN-09). La energía del contrato es su máximo anual (RN-05).
"""

from typing import TypedDict


class ResumenEnergia(TypedDict):
    maximo_gwh: float  # RN-05: la energía del contrato
    promedio_gwh: float
    minimo_gwh: float
    anios_usados: list[int]
    anios_aislados: list[int]


def numero(texto: object) -> float | None:
    """'1400' / '1400.5' / '1400,5' / '1.400,5' -> 1400.5. Vacío o ilegible -> None."""
    if texto is None:
        return None
    if isinstance(texto, int | float):
        return None if texto != texto else float(texto)  # NaN != NaN
    s = str(texto).strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def anios_aislados(anios: list[int]) -> set[int]:
    """RN-07: años con dato cuyo vecino con dato más cercano está a 2 o más años.

    - en una punta: aislado si su único vecino está a >= 2 años;
    - en el medio: aislado si los DOS vecinos están a >= 2 años;
    - un año solo no es aislado: es el único dato del contrato.
    (Misma regla que OLD/funciones.py:161, escrita como función pura.)
    """
    orden = sorted(set(anios))
    aislados: set[int] = set()
    for i, anio in enumerate(orden):
        previo = orden[i - 1] if i > 0 else None
        siguiente = orden[i + 1] if i < len(orden) - 1 else None
        lejos_previo = previo is not None and anio - previo >= 2
        lejos_siguiente = siguiente is not None and siguiente - anio >= 2
        if previo is None and siguiente is not None and lejos_siguiente:
            aislados.add(anio)
        elif siguiente is None and previo is not None and lejos_previo:
            aislados.add(anio)
        elif previo is not None and siguiente is not None and lejos_previo and lejos_siguiente:
            aislados.add(anio)
    return aislados


def resumir(valores_mwh: dict[int, float | None]) -> ResumenEnergia:
    """{año: MWh o None} -> resumen en GWh sin años aislados. Sin datos -> todo en 0."""
    con_dato = {a: v for a, v in valores_mwh.items() if v is not None}
    aislados = anios_aislados(list(con_dato))
    usados = {a: v for a, v in con_dato.items() if a not in aislados}
    gwh = [v / 1000 for v in usados.values()]
    return {
        "maximo_gwh": max(gwh) if gwh else 0.0,
        "promedio_gwh": sum(gwh) / len(gwh) if gwh else 0.0,
        "minimo_gwh": min(gwh) if gwh else 0.0,
        "anios_usados": sorted(usados),
        "anios_aislados": sorted(aislados),
    }
