"""Puntos de retiro/suministro, con textos reales del Excel (2026-10-15)."""

import pytest

from contratos_ingesta.dominio import puntos


@pytest.mark.parametrize(
    ("texto", "subestacion", "propietario", "kv", "seccion"),
    [
        ("CHACAHUIN 13", "CHACAHUIN", None, 13.0, None),
        ("BA S/E CHARRUA 220KV BP1-1", "CHARRUA", None, 220.0, "BP1-1"),
        ("BA S/E SAN JOAQUIN (CGE) 13.2KV C2", "SAN JOAQUIN", "CGE", 13.2, "C2"),
        ("BA S/E POLPAICO (TRANSELEC) 220KV BP1", "POLPAICO", "TRANSELEC", 220.0, "BP1"),
        ("BA S/E MARISCAL 23 kV BP2A", "MARISCAL", None, 23.0, "BP2A"),
        ("BA S/E CACHAPOAL 15kV BT1", "CACHAPOAL", None, 15.0, "BT1"),
        ("BA S/E PANGUILEMO 15KV", "PANGUILEMO", None, 15.0, None),
        ("  BA S/E  ITAHUE   154KV BP1 ", "ITAHUE", None, 154.0, "BP1"),
        # 100 casos reales con (AIS)/(GIS): se descarta el sufijo (decisión del usuario)
        ("BA S/E LOS MAQUIS 220KV BP1-1 (AIS)", "LOS MAQUIS", None, 220.0, "BP1-1"),
        ("BA S/E LOS VILOS 220KV BP3 (GIS)", "LOS VILOS", None, 220.0, "BP3"),
    ],
)
def test_formas_reconocidas(
    texto: str, subestacion: str, propietario: str | None, kv: float, seccion: str | None
) -> None:
    p = puntos.separar_punto(texto)

    assert p is not None and p["reconocido"]
    assert (p["subestacion"], p["propietario"], p["tension_kv"], p["seccion"]) == (
        subestacion,
        propietario,
        kv,
        seccion,
    )


@pytest.mark.parametrize(
    "texto",
    [
        "BA S/E SAN PEDRO (FFCC) CBP1",
        "BA TAP OFF MAURO 220KV BP1",
    ],
)
def test_forma_desconocida_se_conserva_y_se_marca(texto: str) -> None:
    """Casos reales que no calzan: no se pierden, quedan con reconocido = False."""
    p = puntos.separar_punto(texto)

    assert p is not None
    assert (p["subestacion"], p["tension_kv"], p["reconocido"]) == (texto, None, False)


@pytest.mark.parametrize("texto", ["NULO", "nulo", "", "   "])
def test_nulo_y_vacio_no_son_puntos(texto: str) -> None:
    assert puntos.separar_punto(texto) is None


def test_separar_lista() -> None:
    lista = puntos.separar_lista("CHACAHUIN 13;L.ANGELES 13;NULO;")

    assert [p["subestacion"] for p in lista] == ["CHACAHUIN", "L.ANGELES"]
    assert puntos.separar_lista(None) == []
    assert puntos.separar_lista(float("nan")) == []
