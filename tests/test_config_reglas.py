"""config/reglas.toml: lo mismo que estaba en el código (días por vencer, NULO, sufijos),
errores de tipeo con su ubicación, y cambios que se resuelven sin tocar código."""

import re
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from contratos_ingesta import cli, reglas
from contratos_ingesta.dominio import puntos
from tests import referencia_config as viejo
from tests.conftest import Editado
from tests.test_silver import _excel, _fila

# ------------------------------------------------------------- equivalencia


def test_los_valores_son_los_que_estaban_en_el_codigo() -> None:
    r = reglas.cargar()

    assert r["dias_por_vencer"] == viejo.DIAS_POR_VENCER
    assert r["vacios"] == {"NULO"}
    assert r["sufijos"] == ["(AIS)", "(GIS)"]


@pytest.mark.parametrize(
    "punto",
    [
        "BA S/E LOS MAQUIS 220KV BP1-1 (AIS)", "BA S/E LOS MAQUIS 220KV B1-2 (GIS)",
        "BA S/E X 220KV C1 (ais)", "BA S/E X 220KV C1 (Gis)", "BA S/E X 220KV C1(AIS)",
        "BA S/E X 220KV C1   (AIS)", "BA S/E X 220KV C1 (AIS) (GIS)", "(AIS) BA S/E X 220KV",
        "BA S/E X (AIS) 220KV C1", "BA S/E X 220KV C1 (MIS)", "BA S/E X 220KV C1 AIS",
        "BA S/E X 220KV C1 (AIS", "(AIS)", "",
    ],
)  # fmt: skip
def test_los_sufijos_se_quitan_igual(punto: str) -> None:
    assert reglas.cargar()["re_sufijo"].sub("", punto) == viejo.SUFIJO_AIS_GIS.sub("", punto)


@pytest.mark.parametrize(
    "texto", ["NULO", "nulo", "Nulo", "  NULO  ", "NU LO", "NULOS", "NULO 13", "", "   ", "X 13"]
)
def test_los_puntos_vacios_son_los_mismos(texto: str) -> None:
    assert (puntos.separar_punto(texto) is None) == viejo.es_vacio(texto)


# ---------------------------------------------------------- errores de tipeo

SUFIJOS = 'sufijos_que_se_quitan = ["(AIS)", "(GIS)"]'
EJEMPLO_AIS = '    "BA S/E LOS MAQUIS 220KV BP1-1 (AIS)",\n'


@pytest.mark.parametrize(
    ("antes", "despues", "mensaje"),
    [
        ("dias_por_vencer = 180", 'dias_por_vencer = "180"', "sin comillas"),
        ("dias_por_vencer = 180", "dias_por_vencer = 0", "entre 1 y 3650"),
        ("dias_por_vencer = 180", "dias_por_vencer = 180.5", "número entero"),
        ("\n[avisos]\n", "\n[aviso]\n", "falta la sección [avisos]"),
        ('vacios = ["NULO"]', "vacios = []", "falta 'vacios' en [puntos]"),
        ('vacios = ["NULO"]', 'vacios = "NULO"', "tiene que ser una lista"),
        ('vacios = ["NULO"]', 'vacios = ["NULO;X"]', "no puede llevar ';'"),
        ('vacios = ["NULO"]', 'vacios = ["NULO", "NULO"]', "repetidos"),
        (SUFIJOS, 'sufijos_que_se_quitan = ["(AIS) ", "(GIS)"]', "espacios"),
        (SUFIJOS, 'sufijos_que_se_quitan = ["(AIS)", "(GIS)", "(HIB)"]',
         "el sufijo '(HIB)' no tiene ningún ejemplo"),
        (EJEMPLO_AIS, "", "el sufijo '(AIS)' no tiene ningún ejemplo"),
        ("220KV B1-2 (GIS)", "220KV B1-2", "no termina con ningún texto"),
        ('vacios = ["NULO"]', 'vacios = ["NULO"', "no se puede leer"),
    ],
)  # fmt: skip
def test_un_error_de_tipeo_se_detiene_y_dice_cual(
    editado: Editado, antes: str, despues: str, mensaje: str
) -> None:
    with pytest.raises(reglas.ErrorReglas, match=re.escape(mensaje)) as e:
        reglas.cargar(editado("reglas", (antes, despues)))
    assert "reglas.toml" in str(e.value)


# ------------------------------------------------------ de punta a punta

runner = CliRunner()


def test_los_dias_por_vencer_se_cambian_en_el_archivo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    editado: Editado,
    usar: Callable[[str, Path], None],
) -> None:
    datos = tmp_path / "datos"
    datos.mkdir()
    monkeypatch.setenv("CONT_DATA_DIR", str(datos))
    termino = date.today() + timedelta(days=100)
    ruta = _excel(
        tmp_path / "Contratos_publica_20261015_120000.xlsx",
        [_fila(**{"Id Contrato": "100", "Término": f"{termino:%Y-%m-%d} 00:00:00"})],
    )
    assert runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)]).exit_code == 0

    antes = runner.invoke(cli.app, ["estado"])
    assert "1 vencen en 180 días" in antes.output

    usar("reglas", editado("reglas", ("dias_por_vencer = 180", "dias_por_vencer = 90")))
    despues = runner.invoke(cli.app, ["estado"])

    assert "0 vencen en 90 días" in despues.output


def test_un_texto_nuevo_de_punto_vacio_y_un_sufijo_nuevo_se_agregan_en_el_archivo(
    editado: Editado, usar: Callable[[str, Path], None]
) -> None:
    lista = "SIN PUNTO;BA S/E LOS MAQUIS 220KV BP1-1 (HIB)"
    assert [p["texto"] for p in puntos.separar_lista(lista)] == [
        "SIN PUNTO",
        "BA S/E LOS MAQUIS 220KV BP1-1 (HIB)",
    ]
    assert not any(p["reconocido"] for p in puntos.separar_lista(lista))

    usar(
        "reglas",
        editado(
            "reglas",
            ('vacios = ["NULO"]', 'vacios = ["NULO", "SIN PUNTO"]'),
            (SUFIJOS, 'sufijos_que_se_quitan = ["(AIS)", "(GIS)", "(HIB)"]'),
            (EJEMPLO_AIS, EJEMPLO_AIS + '    "BA S/E LOS MAQUIS 220KV BP1-1 (HIB)",\n'),
        ),
    )

    (punto,) = puntos.separar_lista(lista)
    assert punto["subestacion"] == "LOS MAQUIS"
    assert punto["tension_kv"] == 220.0
    assert punto["reconocido"]
