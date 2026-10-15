"""Configuración y rutas (A10, A17, D1)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from contratos_ingesta import rutas
from contratos_ingesta.config import RAIZ_PROYECTO, Settings


def test_valores_por_defecto() -> None:
    cfg = Settings()

    assert cfg.data_dir == RAIZ_PROYECTO / "data"  # A10: anclada al proyecto
    assert cfg.bronze_dir is None and cfg.silver_dir is None


def test_lee_el_archivo_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(f"CONT_SILVER_DIR={tmp_path / 's'}\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env)

    assert Settings().silver_dir == tmp_path / "s"


def test_ruta_de_red_queda_tal_cual(monkeypatch: pytest.MonkeyPatch) -> None:
    red = r"\\SAFIRA_CL1\FrontOffice\Comercial\contratos\bronze"
    monkeypatch.setenv("CONT_BRONZE_DIR", red)

    assert Settings().bronze_dir == Path(red)


def test_variable_mal_escrita_detiene_el_arranque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_SILVR_DIR", "x")

    with pytest.raises(ValidationError, match="CONT_SILVR_DIR"):
        Settings()


def test_variable_mal_escrita_en_el_env_tambien(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("# comentario\nCONT_BRONZ_DIR=x\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env)

    with pytest.raises(ValidationError, match="CONT_BRONZ_DIR"):
        Settings()


def test_variable_ajena_se_ignora(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQL_SERVIDOR", "192.168.0.85")

    Settings()


def test_carpeta_elegida_que_no_existe_se_detiene_y_no_se_crea(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A17: una ruta mal escrita no termina en una carpeta nueva y equivocada."""
    monkeypatch.setenv("CONT_SILVER_DIR", str(tmp_path / "no_existe"))

    with pytest.raises(ValueError, match="CONT_SILVER_DIR"):
        rutas.silver(Settings())
    assert not (tmp_path / "no_existe").exists()


def test_carpeta_elegida_que_existe_se_usa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_BRONZE_DIR", str(tmp_path))

    assert rutas.bronze(Settings()) == tmp_path


def test_sin_eleccion_se_usa_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_DATA_DIR", str(tmp_path))

    assert rutas.bronze(Settings()) == tmp_path / "bronze"
    assert (tmp_path / "bronze").is_dir()


def test_data_dir_que_no_existe_se_detiene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_DATA_DIR", str(tmp_path / "nada"))

    with pytest.raises(ValueError, match="CONT_DATA_DIR"):
        rutas.silver(Settings())


#: Ruta de red real, escrita con raw string: dos barras al inicio, una entre carpetas.
RED = r"\\SAFIRA_CL1\00. Información\18. Contratos CEN\bronze"


def test_ruta_deformada_por_comillas_dobles_se_detiene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caso real del 2026-10-15: entre comillas dobles se pierde una barra del inicio y la
    secuencia barra + b se vuelve un carácter de retroceso."""
    env = tmp_path / ".env"
    env.write_text('CONT_BRONZE_DIR="' + RED + '"' + "\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env)

    with pytest.raises(ValidationError, match="SIN comillas"):
        Settings()


def test_ruta_de_red_sin_comillas_en_el_env_llega_intacta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("CONT_BRONZE_DIR=" + RED + "\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env)

    assert str(Settings().bronze_dir) == RED
