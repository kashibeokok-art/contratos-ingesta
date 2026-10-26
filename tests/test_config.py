"""Configuración y rutas (A10, A17, A28, D1)."""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from contratos_ingesta import cli, config, rutas
from contratos_ingesta.config import RAIZ_PROYECTO, Settings, claves_del_env, explicar

CLAVE = "clave-de-prueba-9f3"


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


# ------------------------------------------------------------ la clave nunca se muestra (A28)


def test_error_de_configuracion_no_muestra_la_clave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El error que lanza el validador del modelo traía `input_value` con todo lo leído."""
    monkeypatch.setenv("CONT_PG_CLAVE", CLAVE)
    monkeypatch.setenv("CONT_SILVR_DIR", "x")

    with pytest.raises(ValidationError) as e:
        Settings()
    assert CLAVE in str(e.value)  # pydantic sí la trae: por eso no se muestra `{e}`
    assert CLAVE not in explicar(e.value)
    assert "CONT_SILVR_DIR" in explicar(e.value)


def test_comando_con_env_roto_no_deja_la_clave_en_pantalla_log_ni_alerta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    datos = tmp_path / "data"
    datos.mkdir()
    monkeypatch.setattr(config, "RAIZ_PROYECTO", tmp_path)  # main() anota en <raíz>/data
    monkeypatch.setenv("CONT_PG_CLAVE", CLAVE)
    monkeypatch.setenv("CONT_SILVR_DIR", "x")
    monkeypatch.setattr(sys, "argv", ["contratos", "estado"])

    with pytest.raises(SystemExit) as fin:
        cli.main()

    assert fin.value.code == 1
    escritos = list(datos.rglob("*.*"))
    assert {p.parent.name for p in escritos} == {"logs", "alertas"}
    for archivo in escritos:
        texto = archivo.read_text(encoding="utf-8")
        assert CLAVE not in texto and "CONT_SILVR_DIR" in texto, archivo.name


def test_la_salida_del_comando_tampoco_la_muestra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_PG_CLAVE", CLAVE)
    monkeypatch.setenv("CONT_PG_CONEXION", "host=x user=y")
    monkeypatch.setenv("CONT_DATA_DIR", "\b")

    resultado = CliRunner().invoke(cli.app, ["estado"])

    assert resultado.exit_code == 1
    assert CLAVE not in resultado.output
    assert "CONT_DATA_DIR" in resultado.output and "SIN comillas" in resultado.output


@pytest.mark.parametrize(
    "conexion",
    [
        f"host=x port=5433 dbname=b user=u password={CLAVE}",
        f"host=x PASSWORD = {CLAVE}",
        f"postgresql://u:{CLAVE}@x:5433/b",
    ],
)
def test_conexion_con_la_clave_adentro_se_detiene(
    conexion: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONT_PG_CONEXION", conexion)

    with pytest.raises(ValidationError) as e:
        Settings()
    assert "CONT_PG_CLAVE" in explicar(e.value)
    assert CLAVE not in explicar(e.value)


def test_conexion_sin_clave_se_acepta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONT_PG_CONEXION", "host=x port=5433 dbname=b user=u")
    monkeypatch.setenv("CONT_PG_CLAVE", CLAVE)

    cfg = Settings()

    assert cfg.pg_conexion == "host=x port=5433 dbname=b user=u"
    assert cfg.pg_clave is not None and cfg.pg_clave.get_secret_value() == CLAVE


# ------------------------------------------------------------ .env.example


def _ejemplo() -> dict[str, str]:
    lineas = (RAIZ_PROYECTO / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(linea.split("=", 1) for linea in lineas if linea and not linea.startswith("#"))


def test_env_example_documenta_cada_variable_y_nada_mas() -> None:
    conocidas = {f"CONT_{c}".upper() for c in Settings.model_fields}

    assert set(claves_del_env(RAIZ_PROYECTO / ".env.example")) == conocidas


def test_env_example_no_trae_valores_reales() -> None:
    """Solo CONT_DATA_DIR tiene valor (el por defecto); las rutas y la conexión van vacías."""
    assert {k: v for k, v in _ejemplo().items() if v} == {"CONT_DATA_DIR": "data"}


def test_env_example_explica_cada_variable() -> None:
    """Cada variable lleva al menos una línea de comentario justo arriba."""
    lineas = (RAIZ_PROYECTO / ".env.example").read_text(encoding="utf-8").splitlines()
    for i, linea in enumerate(lineas):
        if linea.startswith("CONT_"):
            assert lineas[i - 1].startswith("#"), f"{linea.split('=')[0]} no tiene explicación"
