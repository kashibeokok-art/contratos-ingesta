"""Deriva de la fuente (mejora 8.7): la forma conocida no da hallazgos; cada cambio sí."""

import pandas as pd
import pytest

from contratos_ingesta import deriva


def _tabla(**extra: list[str]) -> pd.DataFrame:
    """Una fila con TODAS las columnas conocidas + energía/potencia 1986..2060."""
    datos: dict[str, object] = {c: [None] for c in deriva.COLUMNAS_CONOCIDAS}
    for anio in range(1986, 2061):
        datos[f"Energía {anio}"] = [None]
        datos[f"Potencia {anio}"] = [None]
    datos.update({"Término": ["2027-12-31 00:00:00"], "Fecha Término Renovación": ["05-03-2027"],
                  "Energía 2026": ["1400"], "Potencia 2026": ["0.5"]})  # fmt: skip
    datos.update(extra)
    return pd.DataFrame(datos)


def test_la_forma_conocida_no_da_hallazgos() -> None:
    assert deriva.revisar(_tabla()) == []


def test_columna_nueva_y_columna_que_falta() -> None:
    tabla = _tabla(**{"Tipo de Precio": ["fijo"]}).drop(columns=["Afecto Ley"])

    detalles = [h["detalle"] for h in deriva.revisar(tabla)]

    assert "el Excel trae columnas nuevas: ['Tipo de Precio']" in detalles
    assert "columnas que el Excel ya no trae: ['Afecto Ley']" in detalles


def test_anio_nuevo_es_solo_informativo() -> None:
    hallazgos = deriva.revisar(_tabla(**{"Energía 2061": ["5"]}))

    assert [(h["tipo"], h["severidad"], h["detalle"]) for h in hallazgos] == [
        ("anios_nuevos", "info", "años nuevos en energía/potencia: [2061]")
    ]
    assert "[columnas.por_anio]" in hallazgos[0]["que_hacer"]


@pytest.mark.parametrize(
    ("columna", "valor", "texto"),
    [
        ("Fecha Término Renovación", "2027/03/05", "formato desconocido"),
        ("Energía 2027", "1,400", "con coma"),
        ("Potencia 2027", "n/a", "no son números"),
    ],
)
def test_valores_con_forma_nueva(columna: str, valor: str, texto: str) -> None:
    hallazgos = deriva.revisar(_tabla(**{columna: [valor]}))

    assert len(hallazgos) == 1 and hallazgos[0]["severidad"] == "aviso"
    assert texto in hallazgos[0]["detalle"] and valor in hallazgos[0]["detalle"]
