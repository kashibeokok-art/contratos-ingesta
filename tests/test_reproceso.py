"""Reproceso automático por huella: qué rehace Silver y qué no, de punta a punta y sin servidor.

Silver se rehace si cambia el Excel, la lectura (config/excel.toml y [puntos] de
config/reglas.toml) o el día de la vigencia. Lo que solo cambia avisos no lo rehace, y con
los archivos tal como se entregan la lectura no entra en la huella.
"""

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from contratos_ingesta import cli, publicar, silver
from tests.conftest import Editado
from tests.test_silver import _excel, _fila

runner = CliRunner()
HOY = date(2026, 10, 26)

# ------------------------------------------------------------ la huella


def test_con_los_archivos_entregados_la_lectura_no_entra_en_la_huella() -> None:
    assert silver.huella_lectura() == silver.LECTURA_ORIGINAL
    assert silver.huella("abc") == ["excel:abc"]


#: Cambios que solo tocan avisos: la huella no cambia, Silver no se rehace.
SOLO_AVISOS = [
    ("excel", ('    "Listado Región",\n]', '    "Listado Región",\n    "Columna Nueva",\n]')),
    ("excel", ("anio_max = 2060", "anio_max = 2070")),
    ("excel", ('ejemplos = ["Energía 2026", "Potencia 2026"]',
               'ejemplos = ["Energía 2026", "Potencia 2026", "Energía 2030"]')),
    ("excel", ('"01-09-2026" = "2026-09-01"\n', '"01-09-2026" = "2026-09-01"\n'
                                                 '"15-10-2026" = "2026-10-15"\n')),
    ("excel", ("# Columnas de texto:", "# Un comentario cambiado. Columnas de texto:")),
    ("reglas", ("dias_por_vencer = 180", "dias_por_vencer = 90")),
    ("reglas", ('    "BA S/E LOS MAQUIS 220KV B1-2 (GIS)",\n',
                '    "BA S/E LOS MAQUIS 220KV B1-2 (GIS)",\n    "BA S/E X 66KV C1 (AIS)",\n')),
]  # fmt: skip

#: Cambios que tocan el contenido de Silver: la huella cambia, Silver se rehace.
CONTENIDO = [
    ("excel", ('nombre = "contratos"', 'nombre = "contratos_2027"')),
    ("excel", ("fila_encabezado = 2", "fila_encabezado = 3")),
    ("excel", ('cliente = "Empresa Cliente"', 'cliente = "Numero Cliente"')),
    ("excel", ('energia = "Energía {año}"', 'energia = "Energía (MWh) {año}"'),
              ('ejemplos = ["Energía 2026",', 'ejemplos = ["Energía (MWh) 2026",')),
    ("excel", ('    "DD-MM-AAAA",\n', '    "DD-MM-AAAA",\n    "AAAA/MM/DD",\n'),
              ('"01-09-2026" = "2026-09-01"\n', '"01-09-2026" = "2026-09-01"\n'
                                                '"2026/09/24" = "2026-09-24"\n')),
    ("reglas", ('vacios = ["NULO"]', 'vacios = ["NULO", "SIN PUNTO"]')),
    ("reglas", ('sufijos_que_se_quitan = ["(AIS)", "(GIS)"]',
                'sufijos_que_se_quitan = ["(GIS)", "(AIS)"]')),
]  # fmt: skip


@pytest.mark.parametrize(("archivo", "cambios"), [(a, c) for a, *c in SOLO_AVISOS])
def test_lo_que_solo_avisa_no_cambia_la_huella(
    archivo: str,
    cambios: list[tuple[str, str]],
    editado: Editado,
    usar: Callable[[str, Path], None],
) -> None:
    usar(archivo, editado(archivo, *cambios))
    assert silver.huella("abc") == ["excel:abc"]


@pytest.mark.parametrize(("archivo", "cambios"), [(a, c) for a, *c in CONTENIDO])
def test_lo_que_cambia_silver_cambia_la_huella(
    archivo: str,
    cambios: list[tuple[str, str]],
    editado: Editado,
    usar: Callable[[str, Path], None],
) -> None:
    usar(archivo, editado(archivo, *cambios))
    firma = silver.huella("abc")
    assert firma[0] == "excel:abc"
    assert firma[1].startswith("lectura:") and len(firma) == 2


def test_al_dia_pide_la_misma_huella_y_el_mismo_dia() -> None:
    previo: silver.Proceso = {
        "huella": ["excel:a"], "calculado": "2026-10-26", "lineas": [], "revisar": False
    }  # fmt: skip
    assert silver.al_dia(previo, ["excel:a"], HOY)
    assert not silver.al_dia(previo, ["excel:b"], HOY)  # otro Excel
    assert not silver.al_dia(previo, ["excel:a", "lectura:x"], HOY)  # otra lectura
    assert not silver.al_dia(previo, ["excel:a"], HOY + timedelta(days=1))  # otro día
    assert not silver.al_dia(None, ["excel:a"], HOY)  # sin control, o de antes de la huella


# ------------------------------------------------------- la cadena completa


@pytest.fixture
def datos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    carpeta = tmp_path / "datos"
    carpeta.mkdir()
    monkeypatch.setenv("CONT_DATA_DIR", str(carpeta))
    monkeypatch.setattr(cli, "_hoy", lambda: HOY)
    return carpeta


def _excel_de(tmp_path: Path, nombre: str, *ids: str) -> bytes:
    filas = [
        _fila(**{"Id Contrato": i, "Término": "2030-01-01 00:00:00", "Estado Contrato": "Vigente",
                 "Listado de puntos de Retiro": "CHACAHUIN 13"})
        for i in ids
    ]  # fmt: skip
    return _excel(tmp_path / nombre, filas).read_bytes()


def _marca(datos: Path) -> tuple[int, str]:
    """Cuándo se escribió Silver por última vez, y su huella para publicar."""
    ruta = datos / "silver" / "contratos.parquet"
    return ruta.stat().st_mtime_ns, publicar.huella(datos / "silver")


def _control(datos: Path) -> silver.Proceso:
    proceso = silver.ultimo_proceso(datos / "silver")
    assert proceso is not None
    return proceso


def _api_simulada(monkeypatch: pytest.MonkeyPatch, servido: dict[str, bytes]) -> None:
    """La API del Coordinador, sin red: entrega lo que haya en `servido` en ese momento."""

    def responder(request: httpx.Request) -> httpx.Response:
        if "execute-api" in str(request.url):
            return httpx.Response(200, json={"message": "ok", "data": {"url": "https://s3/c.xlsx"}})
        return httpx.Response(200, content=servido["excel"])

    original = httpx.Client
    monkeypatch.setattr(
        "contratos_ingesta.bronze.httpx.Client",
        lambda *_a, **_k: original(transport=httpx.MockTransport(responder)),
    )


class _Despues(datetime):
    """Para que la segunda descarga no caiga en el mismo segundo (el nombre lleva la hora)."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> "_Despues":
        return cls(2030, 1, 1, tzinfo=tz)


def test_la_cadena_completa_rehace_solo_lo_que_cambio(
    datos: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    editado: Editado,
    usar: Callable[[str, Path], None],
) -> None:
    servido = {"excel": _excel_de(tmp_path, "uno.xlsx", "1")}
    _api_simulada(monkeypatch, servido)

    # 1. primera corrida: baja y procesa
    primera = runner.invoke(cli.app, ["actualizar"])
    assert primera.exit_code == 0, primera.output
    assert "Procesando" in primera.output
    marca = _marca(datos)
    assert _control(datos)["calculado"] == "2026-10-26"
    assert runner.invoke(cli.app, ["estado"]).exit_code == 0

    # 2. otra corrida el mismo día, sin cambios: no rehace nada
    segunda = runner.invoke(cli.app, ["actualizar"])
    assert segunda.exit_code == 0, segunda.output
    assert "ya está al día" in segunda.output and "Procesando" not in segunda.output
    assert "1 contratos (1 vigentes)" in segunda.output  # repite lo que informó
    assert _marca(datos) == marca

    # 3. un cambio que solo avisa: tampoco
    usar("reglas", editado("reglas", ("dias_por_vencer = 180", "dias_por_vencer = 90")))
    assert "ya está al día" in runner.invoke(cli.app, ["actualizar"]).output
    assert _marca(datos) == marca

    # 4. un cambio de la lectura: estado lo avisa y el próximo procesar rehace Silver
    usar("reglas", editado("reglas", ('vacios = ["NULO"]', 'vacios = ["NULO", "SIN PUNTO"]')))
    estado = runner.invoke(cli.app, ["estado"])
    assert estado.exit_code == 3 and "no está al día" in estado.output
    rehecho = runner.invoke(cli.app, ["actualizar"])
    assert "Procesando" in rehecho.output, rehecho.output
    assert _marca(datos)[0] != marca[0]
    assert any(h.startswith("lectura:") for h in _control(datos)["huella"])
    assert runner.invoke(cli.app, ["estado"]).exit_code == 0
    marca = _marca(datos)

    # 5. el día siguiente: se rehace (la vigencia se calcula contra el día)
    monkeypatch.setattr(cli, "_hoy", lambda: HOY + timedelta(days=1))
    assert "Procesando" in runner.invoke(cli.app, ["actualizar"]).output
    assert _control(datos)["calculado"] == "2026-10-27"
    marca = _marca(datos)

    # 6. el Coordinador publica otro Excel: se rehace con ese
    servido["excel"] = _excel_de(tmp_path, "dos.xlsx", "1", "2")
    monkeypatch.setattr("contratos_ingesta.bronze.datetime", _Despues)
    nuevo = runner.invoke(cli.app, ["actualizar"])
    assert "(nuevo)" in nuevo.output and "2 contratos" in nuevo.output, nuevo.output
    assert _marca(datos)[1] != marca[1]  # Silver distinto: publicar-sql lo subiría


def test_al_dia_repite_los_avisos_y_el_codigo(datos: Path, tmp_path: Path) -> None:
    """Una tarea programada que corre dos veces no pierde el código 3 de la primera."""
    ruta = tmp_path / "Contratos_publica_20261015_120000.xlsx"
    _excel(ruta, [_fila(**{"Id Contrato": "1"}), _fila(**{"Id Contrato": "1"})])

    primera = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    segunda = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])

    assert primera.exit_code == segunda.exit_code == 3
    assert "IDs de contrato repetidos" in segunda.output
    assert "ya está al día" in segunda.output


def test_forzar_rehace_aunque_este_al_dia(datos: Path, tmp_path: Path) -> None:
    ruta = tmp_path / "Contratos_publica_20261015_120000.xlsx"
    _excel(ruta, [_fila(**{"Id Contrato": "1"})])
    runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    marca = _marca(datos)

    forzado = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta), "--forzar"])

    assert "Procesando" in forzado.output
    assert _marca(datos)[0] != marca[0]


def test_un_silver_de_antes_de_la_huella_se_rehace_una_vez(datos: Path, tmp_path: Path) -> None:
    """El Silver que hay hoy en Safira no tiene huella: estado lo dice, y procesar la anota."""
    ruta = tmp_path / "Contratos_publica_20261015_120000.xlsx"
    _excel(ruta, [_fila(**{"Id Contrato": "1"})])
    runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    control = datos / "silver" / "_control.json"
    viejo = json.loads(control.read_text(encoding="utf-8"))
    del viejo["proceso"]
    control.write_text(json.dumps(viejo), encoding="utf-8")

    estado = runner.invoke(cli.app, ["estado"])
    assert estado.exit_code == 0 and "sin huella" in estado.output

    procesado = runner.invoke(cli.app, ["procesar", "--archivo", str(ruta)])
    assert "Procesando" in procesado.output
    assert silver.ultimo_proceso(datos / "silver") is not None
