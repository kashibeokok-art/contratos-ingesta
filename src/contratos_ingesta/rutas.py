"""Dónde viven Bronze y Silver. Una carpeta elegida en el .env TIENE que existir (A17).

Si la red no está conectada o la ruta está mal escrita, crearla en silencio haría que los
datos fueran a parar a una carpeta nueva y equivocada. Por eso el programa no la crea.
"""

from pathlib import Path

from contratos_ingesta.config import Settings


def exigir_carpeta(ruta: Path, variable: str) -> Path:
    """La ruta si existe; si no, ValueError con un mensaje que dice qué hacer."""
    if not ruta.is_dir():
        raise ValueError(
            f"no se encuentra la carpeta de {variable}: {ruta}. Si está en la red, revisa que el "
            "equipo esté conectado; si está mal escrita, corrígela en el .env. El programa no "
            "la crea: si es nueva, créala una vez a mano."
        )
    return ruta


def _capa(cfg: Settings, propia: Path | None, variable: str, nombre: str) -> Path:
    if propia is not None:
        return exigir_carpeta(propia, variable)
    base = exigir_carpeta(cfg.data_dir, "CONT_DATA_DIR")
    ruta = base / nombre  # bajo data_dir (que sí se exige) se puede crear
    ruta.mkdir(exist_ok=True)
    return ruta


def bronze(cfg: Settings) -> Path:
    """Carpeta de Bronze: CONT_BRONZE_DIR si se eligió; si no, data_dir/bronze."""
    return _capa(cfg, cfg.bronze_dir, "CONT_BRONZE_DIR", "bronze")


def silver(cfg: Settings) -> Path:
    """Carpeta de Silver: CONT_SILVER_DIR si se eligió; si no, data_dir/silver."""
    return _capa(cfg, cfg.silver_dir, "CONT_SILVER_DIR", "silver")
