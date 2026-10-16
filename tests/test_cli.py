"""Línea de comandos: códigos de salida (A15) y el flujo completo con la API simulada."""

import json
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest
from typer.testing import CliRunner

from contratos_ingesta import cli
from tests.test_silver import _excel, _fila

runner = CliRunner()


@pytest.fixture
def datos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    carpeta = tmp_path / "datos"
    carpeta.mkdir()
    monkeypatch.setenv("CONT_DATA_DIR", str(carpeta))
    return carpeta


def _api_simulada(monkeypatch: pytest.MonkeyPatch, excel: bytes) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        if "execute-api" in str(request.url):
            return httpx.Response(200, json={"message": "ok", "data": {"url": "https://s3/c.xlsx"}})
        return httpx.Response(200, content=excel)

    original = httpx.Client

    def cliente(*_a: object, **_k: object) -> httpx.Client:
        return original(transport=httpx.MockTransport(responder))

    monkeypatch.setattr("contratos_ingesta.bronze.httpx.Client", cliente)


def test_comando_mal_escrito_sale_con_2() -> None:
    assert runner.invoke(cli.app, ["procesar", "--archivoo", "x"]).exit_code == 2
    assert runner.invoke(cli.app, ["desconocido"]).exit_code == 2


def test_archivo_inexistente_sale_con_2(datos: Path) -> None:
    resultado = runner.invoke(cli.app, ["procesar", "--archivo", str(datos / "no.xlsx")])

    assert resultado.exit_code == 2


def test_procesar_sin_bronze_sale_con_1(datos: Path) -> None:
    resultado = runner.invoke(cli.app, ["procesar"])

    assert resultado.exit_code == 1
    assert "corre primero `contratos descargar`" in resultado.output


def test_estado_sin_silver_sale_con_3(datos: Path) -> None:
    assert runner.invoke(cli.app, ["estado"]).exit_code == 3


def test_actualizar_de_punta_a_punta(
    datos: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    excel = _excel(
        tmp_path / "fuente.xlsx",
        [
            _fila(**{"Id Contrato": "1", "Término": "2030-01-01 00:00:00", "Estado Contrato":
                     "Vigente", "Listado de puntos de Retiro": "CHACAHUIN 13"}),
        ],
    ).read_bytes()  # fmt: skip
    _api_simulada(monkeypatch, excel)

    primera = runner.invoke(cli.app, ["actualizar"])
    segunda = runner.invoke(cli.app, ["actualizar"])
    estado = runner.invoke(cli.app, ["estado"])

    assert primera.exit_code == 0, primera.output
    assert "(nuevo)" in primera.output and "1 contratos (1 vigentes)" in primera.output
    assert "sin cambios" in segunda.output
    assert estado.exit_code == 0 and "Bronze: 1 Excel" in estado.output
    tabla = pd.read_parquet(datos / "silver" / "contratos.parquet")
    assert tabla.loc[0, "fecha_ingreso"] == date.today()


def test_fecha_del_archivo() -> None:
    ruta = Path("Contratos_publica_20261015_165541.xlsx")

    assert cli.fecha_del_archivo(ruta) == date(2026, 10, 15)
    with pytest.raises(ValueError):
        cli.fecha_del_archivo(Path("otro.xlsx"))


def test_sin_control_la_fecha_de_ingreso_se_reconstruye_desde_bronze(
    datos: Path, tmp_path: Path
) -> None:
    """Mejora 8.2, de punta a punta: dos Excel en Bronze y el control de Silver borrado."""
    bronze_dir = datos / "bronze"
    bronze_dir.mkdir()
    for nombre, ids in (
        ("Contratos_publica_20261001_090000.xlsx", ["1"]),
        ("Contratos_publica_20261010_090000.xlsx", ["1", "2"]),
    ):
        _excel(bronze_dir / nombre, [_fila(**{"Id Contrato": i}) for i in ids])
    manifiesto = [
        {"archivo": n, "bytes": 1, "sha256": n, "descargado_en": "x", "edad_minutos": None}
        for n in sorted(p.name for p in bronze_dir.glob("*.xlsx"))
    ]
    (bronze_dir / "manifiesto.json").write_text(
        json.dumps({"archivos": manifiesto}), encoding="utf-8"
    )

    resultado = runner.invoke(cli.app, ["procesar"])

    assert resultado.exit_code == 0, resultado.output
    assert "se reconstruye desde 2 Excel" in resultado.output
    tabla = pd.read_parquet(datos / "silver" / "contratos.parquet").set_index("id_contrato")
    assert tabla.loc["1", "fecha_ingreso"] == date(2026, 10, 1)
    assert tabla.loc["2", "fecha_ingreso"] == date(2026, 10, 10)
