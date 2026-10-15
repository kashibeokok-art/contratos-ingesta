"""Aislamiento común (errores_verificados D1 y A10).

- Se borran TODAS las variables CONT_* (barrer el prefijo, no una lista a mano).
- El `.env` está anclado al proyecto: cambiar de carpeta ya no aísla del `.env` real, así que
  se apaga para todos; el test que prueba la lectura del .env lo enciende con uno temporal.
"""

import os
from pathlib import Path

import pytest

from contratos_ingesta.config import Settings


@pytest.fixture(autouse=True)
def aislar_configuracion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for clave in list(os.environ):
        if clave.upper().startswith("CONT_"):
            monkeypatch.delenv(clave, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
