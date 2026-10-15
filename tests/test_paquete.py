"""Primer test (A1/A2: mypy y pytest necesitan al menos un .py en src y en tests)."""

import contratos_ingesta


def test_el_paquete_se_importa() -> None:
    assert contratos_ingesta.__doc__ is not None
