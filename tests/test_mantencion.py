"""Comandos de mantenimiento: revisar-config, probar-excel, diagnostico, volver-a-bajar,
`actualizar` que sigue aunque un paso falle, y config/ validada al arrancar cualquier comando."""

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from contratos_ingesta import bronze, cli, mantencion
from tests.conftest import Editado
from tests.test_silver import _excel, _fila

runner = CliRunner()
HOY = date(2026, 10, 26)
ROTO = ('nombre = "contratos"', 'nombre = "contratos')  # una comilla sin cerrar


@pytest.fixture
def datos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    carpeta = tmp_path / "datos"
    carpeta.mkdir()
    monkeypatch.setenv("CONT_DATA_DIR", str(carpeta))
    monkeypatch.setattr(cli, "_hoy", lambda: HOY)
    return carpeta


def _un_excel(
    carpeta: Path, nombre: str = "Contratos_publica_20261015_120000.xlsx", **valores: object
) -> Path:
    fila = {
        "Id Contrato": "1",
        "Término": "2030-01-01 00:00:00",
        "Estado Contrato": "Vigente",
        "Listado de puntos de Retiro": "CHACAHUIN 13",
        "Energía 2026": "1400",
        **valores,
    }
    return _excel(carpeta / nombre, [_fila(**fila)])


def _bronze_con(datos: Path, *nombres: str) -> Path:
    """Bronze con esos Excel y su manifiesto, como lo deja `descargar`."""
    base = datos / "bronze"
    base.mkdir(exist_ok=True)
    entradas = []
    for i, nombre in enumerate(nombres):
        ruta = _un_excel(base, nombre, **{"Id Contrato": str(i + 1)})
        entradas.append(
            {
                "archivo": nombre,
                "bytes": ruta.stat().st_size,
                "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                "descargado_en": "2026-10-15T12:00:00+00:00",
                "edad_minutos": None,
            }
        )
    (base / "manifiesto.json").write_text(json.dumps({"archivos": entradas}), encoding="utf-8")
    return base


# ------------------------------------------------- config/ validada al arrancar


@pytest.mark.parametrize(
    "comando",
    [
        ["estado"],
        ["procesar"],
        ["descargar"],
        ["actualizar"],
        ["probar-excel"],
        ["volver-a-bajar", "x.xlsx"],
    ],
)
def test_una_config_rota_detiene_cualquier_comando_antes_de_escribir(
    datos: Path,
    editado: Editado,
    usar: Callable[[str, Path], None],
    monkeypatch: pytest.MonkeyPatch,
    comando: list[str],
) -> None:
    ruta = editado("excel", ROTO)
    monkeypatch.setattr("contratos_ingesta.excel.RUTA_POR_DEFECTO", ruta)

    resultado = runner.invoke(cli.app, comando)

    assert resultado.exit_code == 1
    assert "Error en un archivo de configuración" in resultado.output
    assert "excel.toml" in resultado.output and "revisar-config" in resultado.output
    assert resultado.exception is None or isinstance(resultado.exception, SystemExit)
    assert sorted(p.name for p in datos.iterdir()) == []  # no escribió nada


# ------------------------------------------------------------ revisar-config


def test_revisar_config_con_todo_bien() -> None:
    resultado = runner.invoke(cli.app, ["revisar-config"])

    assert resultado.exit_code == 0
    for archivo in ("config/fuente.toml", "config/excel.toml", "config/reglas.toml"):
        assert f"[OK ] {archivo}" in resultado.output
    assert "Todo bien" in resultado.output


def test_revisar_config_muestra_todos_los_errores_y_no_se_detiene(
    editado: Editado, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("contratos_ingesta.excel.RUTA_POR_DEFECTO", editado("excel", ROTO))
    monkeypatch.setattr(
        "contratos_ingesta.reglas.RUTA_POR_DEFECTO",
        editado("reglas", ("dias_por_vencer = 180", "dias_por_vencer = 0")),
    )

    resultado = runner.invoke(cli.app, ["revisar-config"])

    assert resultado.exit_code == 1
    assert "[OK ] config/fuente.toml" in resultado.output
    assert "[MAL] config/excel.toml" in resultado.output and "no se puede leer" in resultado.output
    assert "[MAL] config/reglas.toml" in resultado.output and "entre 1 y 3650" in resultado.output


# ------------------------------------------------------------ probar-excel


def test_probar_excel_dice_que_saco_y_no_escribe(datos: Path, tmp_path: Path) -> None:
    ruta = _un_excel(tmp_path, **{"Fecha Término Renovación": "05-03-2031"})

    resultado = runner.invoke(cli.app, ["probar-excel", str(ruta)])

    assert resultado.exit_code == 0, resultado.output
    assert "contratos     : 1 (1 vigentes al 2026-10-26)" in resultado.output
    assert "puntos        : 1 (0 con forma desconocida)" in resultado.output
    assert "Fecha Término Renovación: 1 leídas de 1 escritas" in resultado.output
    assert "energía [GWh] : mín 1.4000, máx 1.4000, promedio 1.4000" in resultado.output
    assert "Entraría a Silver." in resultado.output
    assert not (datos / "silver").exists()


def test_probar_excel_que_no_entraria(datos: Path, tmp_path: Path) -> None:
    from openpyxl import load_workbook

    ruta = _un_excel(tmp_path)
    libro = load_workbook(ruta)
    (celda,) = [c for c in libro["contratos"][2] if c.value == "Empresa Cliente"]
    celda.value = "Cliente Final"
    libro.save(ruta)

    resultado = runner.invoke(cli.app, ["probar-excel", str(ruta)])

    assert resultado.exit_code == 1
    assert "'Empresa Cliente'" in resultado.output and "NO entraría" in resultado.output
    assert "columnas nuevas: ['Cliente Final']" in resultado.output


def test_probar_excel_con_algo_que_revisar(datos: Path, tmp_path: Path) -> None:
    ruta = tmp_path / "x.xlsx"
    _excel(ruta, [_fila(**{"Id Contrato": "1"}), _fila(**{"Id Contrato": "1"})])

    resultado = runner.invoke(cli.app, ["probar-excel", str(ruta)])

    assert resultado.exit_code == 3
    assert "1 IDs de contrato repetidos" in resultado.output
    assert "(alerta ids_repetidos en la guía)" in resultado.output


def test_probar_excel_con_un_archivo_que_no_es_excel(datos: Path, tmp_path: Path) -> None:
    ruta = tmp_path / "no_es.xlsx"
    ruta.write_text("hola", encoding="utf-8")

    resultado = runner.invoke(cli.app, ["probar-excel", str(ruta)])

    assert resultado.exit_code == 1
    assert "no se pudo leer como Excel de contratos" in resultado.output
    assert "Traceback" not in resultado.output


def test_probar_excel_sin_ruta_usa_el_ultimo_de_bronze(datos: Path) -> None:
    sin_nada = runner.invoke(cli.app, ["probar-excel"])
    assert sin_nada.exit_code == 1 and "Bronze está vacío" in sin_nada.output

    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    resultado = runner.invoke(cli.app, ["probar-excel"])
    assert resultado.exit_code == 0 and "Contratos_publica_20261015_120000.xlsx" in resultado.output


def test_probar_excel_que_no_existe_es_error_de_uso(datos: Path) -> None:
    assert runner.invoke(cli.app, ["probar-excel", "no_existe.xlsx"]).exit_code == 2


# ------------------------------------------------------------ diagnostico


def _estados(chequeos: list[mantencion.Chequeo]) -> dict[str, str]:
    return {c["tema"]: c["estado"] for c in chequeos}


def test_diagnostico_de_un_equipo_nuevo(datos: Path) -> None:
    resultado = runner.invoke(cli.app, ["diagnostico", "--sin-red"])

    assert resultado.exit_code == 3, resultado.output
    assert "[OK   ] config/excel.toml" in resultado.output
    assert "[AVISO] .env: no hay .env" in resultado.output
    assert (
        "[AVISO] Bronze" in resultado.output and "uv run contratos actualizar" in resultado.output
    )
    assert "[AVISO] Silver" in resultado.output
    assert "[OK   ] Carpeta de datos" in resultado.output
    assert sorted(p.name for p in datos.iterdir()) == ["bronze", "silver"]  # sin restos


def test_diagnostico_funciona_con_config_y_env_rotos(
    datos: Path, editado: Editado, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("contratos_ingesta.excel.RUTA_POR_DEFECTO", editado("excel", ROTO))
    monkeypatch.setenv("CONT_SILVR_DIR", "x")

    resultado = runner.invoke(cli.app, ["diagnostico"])

    assert resultado.exit_code == 1
    assert "[MAL  ] config/excel.toml" in resultado.output
    assert "[MAL  ] .env" in resultado.output and "CONT_SILVR_DIR" in resultado.output
    assert "qué hacer: Corregir el .env" in resultado.output


def test_diagnostico_al_dia(datos: Path) -> None:
    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    assert runner.invoke(cli.app, ["procesar"]).exit_code == 0

    estados = _estados(mantencion.diagnostico(HOY, con_red=False))

    assert estados["Bronze"] == "ok" and estados["Silver"] == "ok"


def test_diagnostico_avisa_si_la_tarea_diaria_no_corre(datos: Path) -> None:
    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    runner.invoke(cli.app, ["procesar"])

    chequeos = mantencion.diagnostico(HOY + timedelta(days=5), con_red=False)

    (silver,) = [c for c in chequeos if c["tema"] == "Silver"]
    assert silver["estado"] == "aviso" and "Programador de tareas" in silver["que_hacer"]


def test_diagnostico_avisa_si_silver_no_esta_al_dia(
    datos: Path, editado: Editado, usar: Callable[[str, Path], None]
) -> None:
    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    runner.invoke(cli.app, ["procesar"])
    usar("reglas", editado("reglas", ('vacios = ["NULO"]', 'vacios = ["NULO", "SIN PUNTO"]')))

    (silver,) = [c for c in mantencion.diagnostico(HOY, con_red=False) if c["tema"] == "Silver"]

    assert silver["estado"] == "aviso" and "otra config/" in silver["detalle"]


def test_diagnostico_avisa_si_falta_un_excel_del_registro(datos: Path) -> None:
    base = _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    (base / "Contratos_publica_20261015_120000.xlsx").unlink()

    (b,) = [c for c in mantencion.diagnostico(HOY, con_red=False) if c["tema"] == "Bronze"]

    assert b["estado"] == "aviso" and "volver-a-bajar" in b["que_hacer"]


def _cliente(responder: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(responder))


def test_diagnostico_con_red_pide_el_enlace_pero_no_baja_el_excel(datos: Path) -> None:
    pedidas: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(request.url.host)
        return httpx.Response(
            200, json={"message": "ok", "data": {"url": "https://s3/c", "age_minutes": 120.0}}
        )

    chequeos = mantencion.diagnostico(HOY, cliente=_cliente(responder))

    estados = _estados(chequeos)
    assert estados["Descarga del Coordinador"] == "ok"
    assert pedidas == ["icdp0af7ze.execute-api.us-east-1.amazonaws.com"]  # no pidió el Excel
    assert estados["PostgreSQL"] == "aviso"  # sin CONT_PG_CONEXION


def test_diagnostico_con_la_api_caida(datos: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contratos_ingesta.bronze.time.sleep", lambda _s: None)
    chequeos = mantencion.diagnostico(HOY, cliente=_cliente(lambda _r: httpx.Response(403)))

    (api,) = [c for c in chequeos if c["tema"] == "Descarga del Coordinador"]
    assert api["estado"] == "mal" and "config/fuente.toml" in api["que_hacer"]


def test_diagnostico_sin_clave_de_postgres(datos: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_PG_CONEXION", "host=x user=y")
    monkeypatch.setattr("contratos_ingesta.bronze.time.sleep", lambda _s: None)

    chequeos = mantencion.diagnostico(HOY, cliente=_cliente(lambda _r: httpx.Response(500)))

    assert _estados(chequeos)["PostgreSQL"] == "mal"


# ------------------------------------------------------------ volver-a-bajar


def test_volver_a_bajar_aparta_sin_borrar_y_la_descarga_lo_trae_de_nuevo(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nombres = ("Contratos_publica_20261001_120000.xlsx", "Contratos_publica_20261015_120000.xlsx")
    base = _bronze_con(datos, *nombres)
    contenido = (base / nombres[1]).read_bytes()

    resultado = runner.invoke(cli.app, ["volver-a-bajar", nombres[1]])

    assert resultado.exit_code == 0, resultado.output
    assert (base / "_apartados" / nombres[1]).read_bytes() == contenido  # apartado, no borrado
    assert not (base / nombres[1]).exists()
    assert [e["archivo"] for e in bronze.leer_manifiesto(base)] == [nombres[0]]

    def responder(request: httpx.Request) -> httpx.Response:
        if "execute-api" in str(request.url):
            return httpx.Response(200, json={"message": "ok", "data": {"url": "https://s3/c"}})
        return httpx.Response(200, content=contenido)

    original = httpx.Client
    monkeypatch.setattr(
        "contratos_ingesta.bronze.httpx.Client",
        lambda *_a, **_k: original(transport=httpx.MockTransport(responder)),
    )
    bajado = runner.invoke(cli.app, ["descargar"])
    assert "(nuevo)" in bajado.output
    assert len(bronze.leer_manifiesto(base)) == 2


def test_volver_a_bajar_dos_veces_el_mismo_nombre_no_pisa_el_apartado(datos: Path) -> None:
    nombre = "Contratos_publica_20261015_120000.xlsx"
    base = _bronze_con(datos, nombre)
    runner.invoke(cli.app, ["volver-a-bajar", nombre])
    _bronze_con(datos, nombre)

    runner.invoke(cli.app, ["volver-a-bajar", nombre])

    assert sorted(p.name for p in (base / "_apartados").iterdir()) == [
        "Contratos_publica_20261015_120000.xlsx",
        "Contratos_publica_20261015_120000_2.xlsx",
    ]


def test_volver_a_bajar_un_nombre_que_no_esta(datos: Path) -> None:
    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")

    resultado = runner.invoke(cli.app, ["volver-a-bajar", "otro.xlsx"])

    assert resultado.exit_code == 2
    assert "Contratos_publica_20261015_120000.xlsx" in resultado.output  # sugiere los nombres


def test_volver_a_bajar_uno_que_ya_no_estaba_en_la_carpeta(datos: Path) -> None:
    nombre = "Contratos_publica_20261015_120000.xlsx"
    base = _bronze_con(datos, nombre)
    (base / nombre).unlink()

    resultado = runner.invoke(cli.app, ["volver-a-bajar", nombre])

    assert resultado.exit_code == 0 and "ya no estaba" in resultado.output
    assert bronze.leer_manifiesto(base) == []


# ------------------------------------------------------------ actualizar


def test_actualizar_sigue_aunque_la_descarga_falle(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin red: igual recalcula la vigencia con el último Excel, y sale con 1."""
    _bronze_con(datos, "Contratos_publica_20261015_120000.xlsx")
    original = httpx.Client
    monkeypatch.setattr(
        "contratos_ingesta.bronze.httpx.Client",
        lambda *_a, **_k: original(transport=httpx.MockTransport(lambda _r: httpx.Response(403))),
    )

    resultado = runner.invoke(cli.app, ["actualizar"])

    assert resultado.exit_code == 1
    assert "Descarga    no se pudo cumplir" in resultado.output
    assert "Silver      bien" in resultado.output
    assert (datos / "silver" / "contratos.parquet").is_file()


def test_actualizar_publica_aunque_silver_tenga_algo_que_revisar(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = datos / "bronze"
    base.mkdir()
    ruta = base / "Contratos_publica_20261015_120000.xlsx"
    _excel(ruta, [_fila(**{"Id Contrato": "1"}), _fila(**{"Id Contrato": "1"})])
    (base / "manifiesto.json").write_text(
        json.dumps(
            {
                "archivos": [
                    {
                        "archivo": ruta.name,
                        "bytes": 1,
                        "sha256": "a",
                        "descargado_en": "x",
                        "edad_minutos": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "contratos_ingesta.bronze.descargar",
        lambda *_a, **_k: {"ruta": ruta, "nuevo": False},
    )
    monkeypatch.setenv("CONT_PG_CONEXION", "host=x user=y")
    publicadas: list[bool] = []

    def publicar_falso(forzar: bool = False) -> None:
        publicadas.append(forzar)

    monkeypatch.setattr(cli, "publicar_sql", publicar_falso)

    resultado = runner.invoke(cli.app, ["actualizar"])

    assert resultado.exit_code == 3, resultado.output
    assert publicadas == [False]
    assert "Silver      hay algo que revisar" in resultado.output


# ------------------------------------------------------------ alertas


def _correr_main(monkeypatch: pytest.MonkeyPatch, *argumentos: str) -> int:
    monkeypatch.setattr(sys, "argv", ["contratos", *argumentos])
    with pytest.raises(SystemExit) as fin:
        cli.main()
    return int(fin.value.code or 0)


def test_las_herramientas_manuales_no_dejan_alerta(
    datos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _correr_main(monkeypatch, "diagnostico", "--sin-red") == 3
    assert _correr_main(monkeypatch, "probar-excel") == 1
    assert not (datos / "alertas").exists()

    assert _correr_main(monkeypatch, "procesar") == 1  # una corrida de rutina sí la deja
    assert len(list((datos / "alertas").glob("ALERTA_*.txt"))) == 1


def test_ninguna_prueba_sale_a_internet(datos: Path) -> None:
    """A31: sin simular la API, `descargar` falla dentro de la prueba en vez de bajar el Excel."""
    with pytest.raises(AssertionError, match="intentó salir a internet"):
        bronze.descargar(datos)
