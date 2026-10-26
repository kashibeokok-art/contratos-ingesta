"""config/fuente.toml: lo mismo que estaba en el código, errores de tipeo con su ubicación y
un cambio de dirección que se resuelve sin tocar código."""

import re
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from contratos_ingesta import bronze, cli, fuente
from tests import referencia_config as viejo
from tests.conftest import Editado

# ------------------------------------------------------------- equivalencia


def test_los_valores_son_los_que_estaban_en_el_codigo() -> None:
    f = fuente.cargar()

    assert f["direccion"] == viejo.URL_API
    assert f["parametros"] == viejo.PARAMS
    assert list(f["parametros"]) == list(viejo.PARAMS)  # mismo orden en la dirección
    assert f["encabezados"] == viejo.HEADERS
    assert f["reintentos"] == viejo.REINTENTOS


def test_los_nombres_de_antes_siguen_existiendo() -> None:
    assert bronze.URL_API == viejo.URL_API
    assert bronze.PARAMS == viejo.PARAMS
    assert bronze.HEADERS == viejo.HEADERS
    assert bronze.REINTENTOS == viejo.REINTENTOS
    with pytest.raises(AttributeError):
        _ = bronze.NO_EXISTE


def test_la_peticion_es_la_misma_de_antes(tmp_path: Path) -> None:
    pedidas: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(request)
        if request.url.host.endswith("amazonaws.com"):
            return httpx.Response(200, json={"message": "ok", "data": {"url": "https://s3/c"}})
        return httpx.Response(200, content=b"PK\x03\x04 excel")

    bronze.descargar(tmp_path, httpx.Client(transport=httpx.MockTransport(responder)))

    antes = httpx.Request("GET", viejo.URL_API, params=viejo.PARAMS, headers=viejo.HEADERS)
    assert str(pedidas[0].url) == str(antes.url)
    for nombre, valor in viejo.HEADERS.items():
        assert pedidas[0].headers[nombre] == valor


def test_los_reintentos_son_los_de_antes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("contratos_ingesta.bronze.time.sleep", lambda _s: None)
    intentos: list[int] = []

    def responder(request: httpx.Request) -> httpx.Response:
        intentos.append(1)
        return httpx.Response(503)

    with pytest.raises(bronze.ErrorDescarga):
        bronze.descargar(tmp_path, httpx.Client(transport=httpx.MockTransport(responder)))
    assert len(intentos) == viejo.REINTENTOS


# ---------------------------------------------------------- errores de tipeo

DIRECCION = 'direccion = "https://icdp0af7ze'


@pytest.mark.parametrize(
    ("antes", "despues", "mensaje"),
    [
        (DIRECCION, 'direccion = "http://icdp0af7ze', "https://"),
        (DIRECCION, 'direcion = "https://icdp0af7ze', "falta 'direccion' en [api]"),
        ('/prod/public"', '/prod/public?type=descarga_publica"', 'no lleva "?"'),
        ("reintentos = 3", 'reintentos = "3"', "número entero entre 1 y 10, sin comillas"),
        ("reintentos = 3", "reintentos = 0", "entre 1 y 10"),
        ('empresa = ""', "empresa = 0", "va entre comillas"),
        ('empresa = ""', "empresa = ", "no se puede leer"),
        ('empresa = ""', 'empresa = ""\nempresa = ""', "no se puede leer"),
        ("[api.encabezados]", "[api.encabezado]", "falta la sección [api.encabezados]"),
        ('origin = "https://plataformamercado.coordinador.cl"', 'origin = ""', "origin está vacío"),
        ('accept = "application/json"', 'accept = "application/json "', "espacios"),
    ],
)
def test_un_error_de_tipeo_se_detiene_y_dice_cual(
    editado: Editado, antes: str, despues: str, mensaje: str
) -> None:
    with pytest.raises(fuente.ErrorFuente, match=re.escape(mensaje)) as e:
        fuente.cargar(editado("fuente", (antes, despues)))
    assert "fuente.toml" in str(e.value)  # siempre dice en qué archivo


def test_un_archivo_que_falta_lo_dice() -> None:
    with pytest.raises(fuente.ErrorFuente, match="no existe .*no_esta.toml"):
        fuente.cargar(Path("no_esta.toml"))


# ------------------------------------------------------ de punta a punta


def test_una_direccion_nueva_se_corrige_en_el_archivo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    editado: Editado,
    usar: Callable[[str, Path], None],
) -> None:
    """El Coordinador cambia la dirección: se edita fuente.toml y `descargar` vuelve a andar."""
    pedidas: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidas.append(str(request.url))
        if request.url.host == "api-nueva.coordinador.cl":
            return httpx.Response(200, json={"message": "ok", "data": {"url": "https://s3/c"}})
        if request.url.host == "s3":
            return httpx.Response(200, content=b"PK\x03\x04 excel")
        return httpx.Response(403)  # la dirección vieja ya no responde

    original = httpx.Client
    monkeypatch.setattr(
        "contratos_ingesta.bronze.httpx.Client",
        lambda *_a, **_k: original(transport=httpx.MockTransport(responder)),
    )
    monkeypatch.setenv("CONT_DATA_DIR", str(tmp_path))
    runner = CliRunner()

    antes = runner.invoke(cli.app, ["descargar"])
    assert antes.exit_code == 1
    assert "HTTP 403" in antes.output

    usar(
        "fuente",
        editado("fuente", (viejo.URL_API, "https://api-nueva.coordinador.cl/prod/public")),
    )
    despues = runner.invoke(cli.app, ["descargar"])

    assert despues.exit_code == 0, despues.output
    assert pedidas[-2].startswith("https://api-nueva.coordinador.cl/prod/public?type=")
    assert len(list((tmp_path / "bronze").glob("*.xlsx"))) == 1
