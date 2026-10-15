"""Energía: RN-05 (máximo), RN-07 (años aislados), RN-08 (GWh), RN-09 (sin dato = 0)."""

import pytest

from contratos_ingesta.dominio import energia


@pytest.mark.parametrize(
    ("texto", "valor"),
    [
        ("1400", 1400.0),
        ("1400.5", 1400.5),
        ("1400,5", 1400.5),
        ("1.400,5", 1400.5),
        (285, 285.0),
        (float("nan"), None),
        ("", None),
        (None, None),
        ("abc", None),
    ],
)
def test_numero(texto: object, valor: float | None) -> None:
    assert energia.numero(texto) == valor


@pytest.mark.parametrize(
    ("anios", "aislados"),
    [
        ([2026, 2027, 2028], set()),
        ([2020, 2026, 2027], {2020}),  # punta inicial lejos de su vecino
        ([2026, 2027, 2035], {2035}),  # punta final lejos de su vecino
        ([2026, 2027, 2029, 2030], set()),  # un hueco de 1 año en el medio no aísla
        ([2020, 2024, 2030], {2020, 2024, 2030}),
        ([2026], set()),  # un solo año no es aislado: es el único dato
        ([2026, 2028], {2026, 2028}),
        ([], set()),
    ],
)
def test_anios_aislados(anios: list[int], aislados: set[int]) -> None:
    assert energia.anios_aislados(anios) == aislados


def test_resumir_aplica_las_reglas() -> None:
    resumen = energia.resumir({2026: 1400.0, 2027: 2000.0, 2028: None, 2040: 9999.0})

    assert resumen == {
        "maximo_gwh": 2.0,  # RN-05 + RN-08: 2000 MWh = 2 GWh; 2040 no cuenta (RN-07)
        "promedio_gwh": 1.7,
        "minimo_gwh": 1.4,
        "anios_usados": [2026, 2027],
        "anios_aislados": [2040],
    }


def test_resumir_sin_datos_queda_en_cero() -> None:
    """RN-09."""
    resumen = energia.resumir({2026: None, 2027: None})

    assert (resumen["maximo_gwh"], resumen["promedio_gwh"], resumen["minimo_gwh"]) == (0, 0, 0)
    assert resumen["anios_usados"] == []
