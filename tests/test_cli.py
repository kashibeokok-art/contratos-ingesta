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
    assert "Bronze está vacío" in resultado.output
    assert "qué hacer: Correr uv run contratos actualizar" in resultado.output
    assert "(alerta bronze_vacio en la guía)" in resultado.output


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


def _correr_main(monkeypatch: pytest.MonkeyPatch, *argumentos: str) -> int:
    """Corre el punto de entrada real (`contratos ...`), como lo haría una tarea programada."""
    monkeypatch.setattr("sys.argv", ["contratos", *argumentos])
    with pytest.raises(SystemExit) as fin:
        cli.main()
    return int(fin.value.code or 0)


def test_una_corrida_fallida_deja_log_y_alerta(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mejora 8.5: Bronze vacío -> código 1, log del día y archivo de alerta con qué hacer."""
    assert _correr_main(monkeypatch, "procesar") == 1

    log = next((datos / "logs").glob("contratos_*.log")).read_text(encoding="utf-8")
    assert "Bronze está vacío" in log
    alerta = next((datos / "alertas").glob("ALERTA_*.txt")).read_text(encoding="utf-8")
    assert "Comando:  contratos procesar" in alerta
    assert "Código:   1 (no se pudo cumplir)" in alerta and "Qué hacer:" in alerta
    assert "Bronze está vacío" in alerta


def test_una_corrida_bien_no_deja_alerta(datos: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _correr_main(monkeypatch, "estado") == 3  # Silver vacío: algo que revisar
    assert len(list((datos / "alertas").glob("ALERTA_*.txt"))) == 1
    (next((datos / "alertas").glob("ALERTA_*.txt"))).unlink()

    _correr_main(monkeypatch, "--help")

    assert not list((datos / "alertas").glob("ALERTA_*.txt"))


def test_comando_mal_escrito_sale_con_2_sin_alerta(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _correr_main(monkeypatch, "procesar", "--archivoo", "x") == 2
    assert not (datos / "alertas").exists()


def test_esquema_antiguo_dice_que_hay_que_correr_el_sql(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caso real (2026-10-16): publicar-sql contra un esquema sin contrato_nuevo."""
    import psycopg

    (datos / "silver").mkdir()
    (datos / "silver" / "contratos.parquet").write_bytes(b"x")
    monkeypatch.setenv("CONT_PG_CONEXION", "host=x dbname=cmg_cen user=contratos_carga")
    monkeypatch.setenv("CONT_PG_CLAVE", "x")

    class ConexionFalsa:
        def __enter__(self) -> "ConexionFalsa":
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def publicar_falso(*_a: object, **_k: object) -> None:
        raise psycopg.errors.UndefinedTable('relation "contratos.contrato_nuevo" does not exist')

    monkeypatch.setattr("contratos_ingesta.cli.psycopg.connect", lambda *a, **k: ConexionFalsa())
    monkeypatch.setattr("contratos_ingesta.cli.publicar.publicar", publicar_falso)

    resultado = runner.invoke(cli.app, ["publicar-sql"])

    assert resultado.exit_code == 1
    assert "debe correr sql/esquema_contratos.sql" in resultado.output
    assert "No se cambió nada en la base" in resultado.output
