"""config/excel.toml: lo mismo que estaba en el código (columnas, años y fechas), errores de
tipeo con su ubicación, y dos cambios del Excel que se resuelven sin tocar código."""

import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from contratos_ingesta import cli, deriva, excel, silver
from contratos_ingesta.dominio import fechas
from tests import referencia_config as viejo
from tests.conftest import Editado
from tests.test_silver import _excel, _fila

# ------------------------------------------------------------- equivalencia


def test_los_valores_son_los_que_estaban_en_el_codigo() -> None:
    e = excel.cargar()

    assert e["hoja"] == viejo.HOJA
    assert e["fila_encabezado"] - 1 == viejo.HEADER
    assert e["conocidas"] == list(viejo.COLUMNAS_CONOCIDAS)
    for nuevo, antes in ((e["texto"], viejo.TEXTOS), (e["fecha"], viejo.FECHAS),
                         (e["puntos"], viejo.PUNTOS)):  # fmt: skip
        assert list(nuevo.items()) == list(antes.items())  # mismo contenido y mismo orden
    assert (e["anio_min"], e["anio_max"]) == (viejo.ANIO_MIN, viejo.ANIO_MAX)
    assert tuple(e["fecha"]) == viejo.COLUMNAS_FECHA


def test_los_nombres_de_antes_siguen_existiendo() -> None:
    assert deriva.COLUMNAS_CONOCIDAS == viejo.COLUMNAS_CONOCIDAS
    assert (deriva.ANIO_MIN, deriva.ANIO_MAX) == (viejo.ANIO_MIN, viejo.ANIO_MAX)
    assert deriva.COLUMNAS_FECHA == viejo.COLUMNAS_FECHA
    assert silver.HOJA == viejo.HOJA
    assert (silver.TEXTOS, silver.FECHAS, silver.PUNTOS) == (viejo.TEXTOS, viejo.FECHAS,
                                                              viejo.PUNTOS)  # fmt: skip
    # las 2 formas que de verdad vienen en el Excel (decisión del usuario, 2026-10-26)
    assert fechas.FORMATOS == ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y")
    assert set(fechas.FORMATOS) <= set(viejo.FORMATOS)


def test_importar_no_lee_los_archivos() -> None:
    """Los nombres de antes se leen al USARLOS: importar el programa no abre config/."""
    codigo = (
        "import contratos_ingesta.cli, contratos_ingesta.excel as e, contratos_ingesta.fuente "
        "as f, contratos_ingesta.reglas as r; print(len(e._VIGENTE) + len(f._VIGENTE) + "
        "len(r._VIGENTE))"
    )
    salida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert salida.stdout.strip() == "0", salida.stderr


#: Los nombres reales + años de todo el rango + bordes.
COLUMNAS_A_PROBAR = [
    *viejo.COLUMNAS_CONOCIDAS,
    *(f"{m} {a}" for m in ("Energía", "Potencia") for a in range(1980, 2070)),
    "Energia 2026", "ENERGÍA 2026", "energía 2026", "  Energía   2026 ", "Potencia\t2026",
    "Energía 2026 (MWh)", "Energía", "Energía año", "Energía 2O26", "Energía_2026",
    "Energía ２０２６", "Potencia Conectada 2026", "Precio 2026", "2026",
]  # fmt: skip
#: Únicas diferencias, a propósito: {año} es un año de 4 dígitos. Antes, Silver tomaba
#: "Energía 26" como el año 26 mientras deriva la avisaba como columna nueva; ahora los dos
#: la tratan igual (columna nueva, con aviso).
DISTINTAS_A_PROPOSITO = ["Energía 26", "Energía 20261", "Potencia 0"]


def _anio_deriva_viejo(columna: str) -> tuple[str, int] | None:
    m = viejo.POR_ANIO.match(columna)
    return None if m is None else (m.group(1), int(m.group(2)))


@pytest.mark.parametrize("columna", COLUMNAS_A_PROBAR)
def test_las_columnas_de_cada_anio_se_reconocen_igual(columna: str) -> None:
    e = excel.cargar()
    # deriva: nombre exacto
    exacto = [(m, int(x.group(1))) for m, p in e["por_anio"].items() if (x := p.match(columna))]
    antes = _anio_deriva_viejo(columna)
    assert exacto == ([] if antes is None else [(viejo.sin_tildes(antes[0]), antes[1])])
    # silver: sin tildes ni mayúsculas
    for magnitud, patron in e["por_anio_tolerante"].items():
        m = patron.match(excel.sin_tildes(columna))
        assert (int(m.group(1)) if m else None) == viejo.anio_silver(columna, magnitud)


@pytest.mark.parametrize("columna", DISTINTAS_A_PROPOSITO)
def test_un_anio_que_no_es_de_4_digitos_ya_no_se_lee(columna: str) -> None:
    e = excel.cargar()
    assert viejo.anio_silver(columna, viejo.sin_tildes(columna.split()[0])) is not None
    assert not any(p.match(excel.sin_tildes(columna)) for p in e["por_anio_tolerante"].values())
    assert _anio_deriva_viejo(columna) is None  # deriva ya la avisaba: eso no cambia


#: Las formas reales y bordes. `leer_fecha` de antes y de ahora dan lo mismo.
FECHAS_A_PROBAR: list[object] = [
    "2026-09-24 00:00:00", "2027-03-31 00:00:00", "30-09-2026", "01-09-2026", "05-03-2027",
    "  30-09-2026  ", "2026-9-24 0:0:0", "1-9-2026", "31-02-2027", "29-02-2028", "",
    "   ", "pronto", "30-09-26", "2026-09-24T00:00:00", "30.09.2026", None,
    datetime(2026, 1, 2, 10, 0), date(2026, 1, 2),
]  # fmt: skip


@pytest.mark.parametrize("valor", FECHAS_A_PROBAR)
def test_las_fechas_se_leen_igual(valor: object) -> None:
    assert fechas.leer_fecha(valor) == viejo.leer_fecha(valor)


@pytest.mark.parametrize("valor", ["2027-12-31", "31/12/2027"])
def test_las_formas_nunca_vistas_ya_no_se_adivinan(valor: str) -> None:
    """Decisión del usuario (2026-10-26): si llegan, quedan vacías y deriva avisa."""
    assert viejo.leer_fecha(valor) == date(2027, 12, 31)
    assert fechas.leer_fecha(valor) is None


# ---------------------------------------------------------- errores de tipeo

FORMA_TEXTO = '"DD-MM-AAAA",'
EJEMPLOS_DD_MM = '"30-09-2026" = "2026-09-30"\n"01-09-2026" = "2026-09-01"\n'


@pytest.mark.parametrize(
    ("antes", "despues", "mensaje"),
    [
        ('nombre = "contratos"', 'nombre = ""', "falta 'nombre' en [hoja]"),
        ("fila_encabezado = 2", "fila_encabezado = 0", "entre 1 y 100"),
        ("fila_encabezado = 2", 'fila_encabezado = "2"', "sin comillas"),
        ('cliente = "Empresa Cliente"', 'clinte = "Empresa Cliente"',
         "['clinte'] no son columnas de Silver en [columnas.texto]"),
        ('cliente = "Empresa Cliente"', "", "faltan ['cliente'] en [columnas.texto]"),
        ('cliente = "Empresa Cliente"', 'cliente = "Empresa Clientes"',
         "no está en 'conocidas'"),
        ('cliente = "Empresa Cliente"', 'cliente = "Empresa Suministradora"',
         "más de una columna de Silver"),
        ('cliente = "Empresa Cliente"', 'cliente = " Empresa Cliente"', "espacios"),
        ("\n[columnas.fecha]\n", "\n[columnas.fechas]\n", "falta la sección [columnas.fecha]"),
        ('energia = "Energía {año}"', 'energia = "Energía {anio}"', "{año} una vez"),
        ('energia = "Energía {año}"', 'energia = "Energía{año}"',
         "el ejemplo 'Energía 2026' no calza"),
        ('ejemplos = ["Energía 2026", "Potencia 2026"]', 'ejemplos = ["Energía 2026"]',
         "'Potencia {año}' no tiene ningún ejemplo"),
        ("anio_min = 1986", "anio_min = 2070", "mayor que anio_max"),
        ('    "Listado Región",\n]', '    "Listado Región",\n    "Listado Region",\n]',
         "solo difieren en tildes"),
        ('    "Listado Región",\n]', '    "Listado Región",\n    "Energía 2026",\n]',
         "son columnas de un año"),
        ('    "Listado Región",\n]', '    "Listado Región",\n    "Listado Región",\n]',
         "repetidos"),
        (FORMA_TEXTO, '"MM-DD-AAAA",', "no calza con ninguna forma"),
        (FORMA_TEXTO, '"DD-MM-AA",', "AAAA (el año) una vez"),
        ('"AAAA-MM-DD hh:mm:ss",', '"AAAA-MM-DD HH:MM:SS",', "MM (el mes) una vez"),
        ('"AAAA-MM-DD hh:mm:ss",', '"AAAA-MM-DD HH:mm:ss",', "la letra 'H'"),
        ('"01-09-2026" = "2026-09-01"', '"01-09-2026" = "2026-01-09"',
         "se lee como 2026-09-01"),
        ('"30-09-2026" = "2026-09-30"', '"30-09-2026" = "30-09-2026"', "AAAA-MM-DD"),
        (EJEMPLOS_DD_MM, "", "la forma 'DD-MM-AAAA' no lee ningún ejemplo"),
        ('"30-09-2026" = "2026-09-30"', '"30-09-2026 = "2026-09-30"', "no se puede leer"),
    ],
)  # fmt: skip
def test_un_error_de_tipeo_se_detiene_y_dice_cual(
    editado: Editado, antes: str, despues: str, mensaje: str
) -> None:
    with pytest.raises(excel.ErrorExcel, match=re.escape(mensaje)) as e:
        excel.cargar(editado("excel", (antes, despues)))
    assert "excel.toml" in str(e.value)


def test_dia_y_mes_cambiados_de_lugar_se_detectan() -> None:
    """La trampa de A21, en el archivo: una forma con DD y MM al revés no pasa la carga."""
    with pytest.raises(excel.ErrorExcel, match="Revisa el orden de DD y MM"):
        excel.cargar(_con_texto('formas = ["MM-DD-AAAA"]', '"01-09-2026" = "2026-09-01"'))


def _con_texto(formas: str, ejemplos: str) -> Path:
    """Un excel.toml con [fechas] reemplazado (lo demás, el del proyecto)."""
    original = excel.RUTA_POR_DEFECTO.read_text(encoding="utf-8")
    texto = original[: original.index("\n[fechas]\n") + 1] + (
        f"[fechas]\n{formas}\n[fechas.ejemplos]\n{ejemplos}\n"
    )
    ruta = Path("excel_fechas.toml").resolve()
    ruta.write_text(texto, encoding="utf-8")
    return ruta


# ------------------------------------------------------ de punta a punta

runner = CliRunner()


@pytest.fixture
def datos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    carpeta = tmp_path / "datos"
    carpeta.mkdir()
    monkeypatch.setenv("CONT_DATA_DIR", str(carpeta))
    return carpeta


def _renombrar_columna(ruta: Path, antes: str, despues: str) -> None:
    libro = load_workbook(ruta)
    hoja = libro["contratos"]
    (celda,) = [c for c in hoja[2] if c.value == antes]
    celda.value = despues
    libro.save(ruta)


def test_una_columna_renombrada_se_corrige_en_el_archivo(
    tmp_path: Path, datos: Path, editado: Editado, usar: Callable[[str, Path], None]
) -> None:
    """El Coordinador renombra 'Empresa Cliente' a 'Cliente Final': se edita excel.toml."""
    ruta = _excel(
        tmp_path / "Contratos_publica_20261015_120000.xlsx",
        [_fila(**{"Id Contrato": "100", "Término": "2027-12-31 00:00:00"})],
    )
    _renombrar_columna(ruta, "Empresa Cliente", "Cliente Final")

    antes = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    assert antes.exit_code == 1
    assert "'Empresa Cliente'" in antes.output

    usar(
        "excel",
        editado(
            "excel",
            ('    "Empresa Cliente",\n', '    "Cliente Final",\n'),
            ('cliente = "Empresa Cliente"', 'cliente = "Cliente Final"'),
        ),
    )
    despues = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])

    assert despues.exit_code == 0, despues.output  # 0: tampoco queda el aviso de deriva
    contratos = pd.read_parquet(datos / "silver" / "contratos.parquet")
    assert list(contratos["cliente"]) == ["CLIENTE SA"]
    assert "Cliente Final" in deriva.COLUMNAS_CONOCIDAS  # el nombre viejo ve el cambio


def test_una_fecha_con_otra_forma_se_agrega_en_el_archivo(
    tmp_path: Path, datos: Path, editado: Editado, usar: Callable[[str, Path], None]
) -> None:
    """El Término llega como 2027/12/31: aviso y fecha vacía; se agrega la forma y se lee."""
    termino = date.today() + timedelta(days=400)
    ruta = _excel(
        tmp_path / "Contratos_publica_20261015_120000.xlsx",
        [_fila(**{"Id Contrato": "100", "Término": f"{termino:%Y/%m/%d}"})],
    )

    antes = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    assert antes.exit_code == 3  # algo que revisar
    assert "formato desconocido" in antes.output
    vigente = pd.read_parquet(datos / "silver" / "contratos.parquet")["vigente"]
    assert list(vigente) == [False]  # sin término: no vigente

    usar(
        "excel",
        editado(
            "excel",
            ('    "DD-MM-AAAA",\n', '    "DD-MM-AAAA",\n    "AAAA/MM/DD",\n'),
            ('"01-09-2026" = "2026-09-01"\n', '"01-09-2026" = "2026-09-01"\n'
                                               '"2027/12/31" = "2027-12-31"\n'),
        ),
    )  # fmt: skip
    despues = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])

    assert despues.exit_code == 0, despues.output
    contratos = pd.read_parquet(datos / "silver" / "contratos.parquet")
    assert list(contratos["vigente"]) == [True]
    assert contratos["fecha_termino"].iloc[0] == termino
