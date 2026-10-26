"""Aislamiento común (errores_verificados D1 y A10).

- Se borran TODAS las variables CONT_* (barrer el prefijo, no una lista a mano).
- El `.env` está anclado al proyecto: cambiar de carpeta ya no aísla del `.env` real, así que
  se apaga para todos; el test que prueba la lectura del .env lo enciende con uno temporal.
- Cada test parte con los archivos de `config/` del proyecto. Para probar un cambio,
  `editado` escribe una copia con el cambio y `usar` hace que el programa la lea.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from contratos_ingesta import excel, fuente, reglas
from contratos_ingesta.config import Settings

EDITABLES: dict[str, ModuleType] = {"fuente": fuente, "excel": excel, "reglas": reglas}


@pytest.fixture(autouse=True)
def aislar_configuracion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for clave in list(os.environ):
        if clave.upper().startswith("CONT_"):
            monkeypatch.delenv(clave, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(autouse=True)
def sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ninguna prueba sale a internet (A31): la que olvida simular la API falla, no descarga.

    Solo se bloquea el transporte real de httpx; `httpx.MockTransport` sigue funcionando.
    """

    def bloqueado(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"una prueba intentó salir a internet: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", bloqueado)


@pytest.fixture(autouse=True)
def config_del_proyecto() -> Iterator[None]:
    """Lo que un test dejó leído (o cambió con `usar`) no pasa al siguiente."""
    yield
    for modulo in EDITABLES.values():
        modulo._VIGENTE.clear()


Editado = Callable[..., Path]


@pytest.fixture
def editado(tmp_path: Path) -> Editado:
    """editado("excel", (antes, despues), ...): copia de config/excel.toml con esos cambios."""

    def _editar(archivo: str, *cambios: tuple[str, str]) -> Path:
        texto = EDITABLES[archivo].RUTA_POR_DEFECTO.read_text(encoding="utf-8")
        for antes, despues in cambios:
            assert texto.count(antes) >= 1, f"no está en config/{archivo}.toml: {antes!r}"
            texto = texto.replace(antes, despues, 1)
        ruta = tmp_path / "config_editada" / f"{archivo}.toml"
        ruta.parent.mkdir(exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        return ruta

    return _editar


@pytest.fixture
def usar(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, Path], None]:
    """usar("excel", ruta): desde ahora el programa lee ese archivo en vez del del proyecto."""

    def _usar(archivo: str, ruta: Path) -> None:
        modulo = EDITABLES[archivo]
        monkeypatch.setattr(modulo, "RUTA_POR_DEFECTO", ruta)
        modulo._VIGENTE.clear()

    return _usar
