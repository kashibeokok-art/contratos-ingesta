"""Configuración leída de variables de entorno y del archivo .env (Twelve-Factor).

Reglas (docs/errores_verificados.md):
- A10: una ruta relativa se cuelga de la CARPETA DEL PROYECTO, no de la carpeta desde
  donde se ejecuta el comando. El `.env` también se busca ahí.
- A17: una variable `CONT_*` que el programa no conoce DETIENE el arranque (casi siempre
  es un nombre mal escrito). Las variables ajenas (sin `CONT_`) se ignoran.
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: La carpeta que tiene `pyproject.toml` (este archivo está dos niveles más abajo).
RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

PREFIJO = "CONT_"


def claves_del_env(ruta: Path) -> list[str]:
    """Los nombres de variable de un `.env` (sin valores). Ignora comentarios y líneas vacías."""
    if not ruta.is_file():
        return []
    claves: list[str] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        claves.append(linea.split("=", 1)[0].strip().removeprefix("export ").strip())
    return claves


def desconocidas(
    conocidas: set[str], env_file: Path | None, entorno: Mapping[str, str]
) -> list[str]:
    """Las variables `CONT_*` (del `.env` o del sistema) que no son un campo de Settings."""
    vistas = [k for k in entorno if k.upper().startswith(PREFIJO)]
    if env_file is not None:
        vistas += [k for k in claves_del_env(env_file) if k.upper().startswith(PREFIJO)]
    return sorted({k.upper() for k in vistas} - conocidas)


class Settings(BaseSettings):
    """Cada atributo se lee de la variable CONT_<NOMBRE>. Prioridad: entorno > .env > defecto."""

    model_config = SettingsConfigDict(
        env_prefix=PREFIJO,
        env_file=RAIZ_PROYECTO / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,  # CONT_X= (vacío) cuenta como "no configurado"
        extra="ignore",  # lo ajeno se ignora; las CONT_ desconocidas las detiene el validador
    )

    data_dir: Path = Path("data")
    """Carpeta local de trabajo (temporales y reportes). Relativa = dentro del proyecto."""

    bronze_dir: Path | None = None
    """Carpeta de Bronze (los Excel descargados). Sin valor: data_dir/bronze."""

    silver_dir: Path | None = None
    """Carpeta de Silver (las tablas procesadas). Sin valor: data_dir/silver."""

    pg_conexion: str | None = None
    """Conexión a PostgreSQL SIN la clave: host=... port=... dbname=cmg_cen user=contratos_carga."""

    pg_clave: SecretStr | None = None
    """Clave de `pg_conexion`. SecretStr: no aparece si se imprime la configuración (D2)."""

    @field_validator("data_dir", "bronze_dir", "silver_dir", mode="before")
    @classmethod
    def _sin_deformar(cls, valor: object) -> object:
        """Detecta una ruta deformada por comillas dobles en el .env (caso real, 2026-10-15).

        Entre comillas dobles, el lector del .env interpreta las barras: `\\\\SERVIDOR` queda
        `\\SERVIDOR` (ya no es ruta de red) y `\\b` se vuelve un carácter de control.
        """
        texto = str(valor) if valor is not None else ""
        deformada = any(ord(c) < 32 for c in texto) or (
            texto.startswith("\\") and not texto.startswith("\\\\")
        )
        if deformada:
            raise ValueError(
                f"la ruta {texto!r} llegó deformada. En el .env escribe las rutas SIN comillas "
                r"(por ejemplo CONT_BRONZE_DIR=\\SERVIDOR\carpeta\bronze): entre comillas "
                "dobles las barras se interpretan y la ruta cambia."
            )
        return valor

    @field_validator("data_dir")
    @classmethod
    def _anclar(cls, ruta: Path) -> Path:
        """Relativa -> dentro del proyecto (A10). Absoluta o de red -> tal cual."""
        return ruta if ruta.is_absolute() else RAIZ_PROYECTO / ruta

    @field_validator("bronze_dir", "silver_dir")
    @classmethod
    def _anclar_si_hay(cls, ruta: Path | None) -> Path | None:
        return None if ruta is None else cls._anclar(ruta)

    @model_validator(mode="after")
    def _sin_desconocidas(self) -> "Settings":
        env_file = self.model_config.get("env_file")
        ruta = Path(env_file) if isinstance(env_file, str | Path) else None
        conocidas = {f"{PREFIJO}{campo}".upper() for campo in type(self).model_fields}
        malas = desconocidas(conocidas, ruta, os.environ)
        if malas:
            raise ValueError(
                f"variable(s) que el programa no conoce: {', '.join(malas)}. "
                f"Las válidas son: {', '.join(sorted(conocidas))}. Revisa si está mal escrita "
                f"(en {ruta or 'las variables del sistema'})."
            )
        return self
