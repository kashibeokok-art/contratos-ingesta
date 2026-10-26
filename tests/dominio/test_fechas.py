"""Fechas y vigencia (A21: nunca adivinar el orden día/mes)."""

from datetime import date, datetime

import pytest

from contratos_ingesta.dominio import fechas


@pytest.mark.parametrize(
    ("valor", "esperada"),
    [
        ("2026-09-24 00:00:00", date(2026, 9, 24)),  # forma de Inicio/Término en el Excel
        ("05-03-2027", date(2027, 3, 5)),  # renovación en texto: 5 de MARZO, no 3 de mayo
        ("30-09-2026", date(2026, 9, 30)),
        # Formas nunca vistas en el Excel real: no se adivinan, quedan vacías y deriva avisa
        # (decisión del usuario, 2026-10-26; antes se aceptaban por precaución)
        ("2027-12-31", None),
        ("31/12/2027", None),
        (datetime(2026, 1, 2, 10, 0), date(2026, 1, 2)),
        ("31-02-2027", None),  # no existe
        ("", None),
        (None, None),
        ("pronto", None),
    ],
)
def test_leer_fecha(valor: object, esperada: date | None) -> None:
    assert fechas.leer_fecha(valor) == esperada


def test_termino_efectivo_es_el_mayor() -> None:
    assert fechas.termino_efectivo(date(2020, 1, 1), date(2030, 1, 1)) == date(2030, 1, 1)
    assert fechas.termino_efectivo(date(2027, 1, 1), None) == date(2027, 1, 1)
    assert fechas.termino_efectivo(None, None) is None


@pytest.mark.parametrize(
    ("termino", "vigente", "dias"),
    [
        (date(2026, 10, 15), True, 0),  # vence hoy: todavía vigente
        (date(2026, 10, 14), False, -1),
        (date(2027, 10, 15), True, 365),
        (None, False, None),
    ],
)
def test_vigencia_y_dias(termino: date | None, vigente: bool, dias: int | None) -> None:
    hoy = date(2026, 10, 15)
    assert fechas.vigente(termino, hoy) is vigente
    assert fechas.dias_para_vencer(termino, hoy) == dias
