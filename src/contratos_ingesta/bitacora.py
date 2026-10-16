"""Bitácora de cada corrida: log diario y archivo de alerta si algo falla (mejora 8.5).

Todo lo que el comando muestra pasa por `decir()`, que además lo anota en
`data/logs/contratos_AAAAMMDD.log`. Al terminar, si el código es 1 (no se pudo) o 3 (hay
algo que revisar), `alertar()` deja `data/alertas/ALERTA_AAAAMMDD_HHMMSS.txt` con el comando,
el código, qué hacer y la salida completa de esa corrida: quien revise la carpeta lo ve sin
abrir una terminal.

Si la carpeta de datos no existe todavía, se muestra igual pero no se anota (no se crean
carpetas que el usuario no creó, A17).
"""

from datetime import datetime
from pathlib import Path

import typer

#: Qué hacer según el código de salida.
QUE_HACER = {
    1: "No se pudo cumplir. Lee el mensaje de error de abajo: si es la red, la API o el servidor, "
    "vuelve a correr más tarde; si es la configuración (.env), corrígela. Nada quedó a medias.",
    2: "El comando estaba mal escrito. Revisa la tarea o el comando que lo llamó.",
    3: "Terminó, pero hay algo que revisar (abajo, las líneas 'revisar' o 'aviso'). Los datos "
    "se procesaron.",
}
NOMBRES = {0: "bien", 1: "no se pudo cumplir", 2: "comando mal escrito", 3: "hay algo que revisar"}

_lineas: list[str] = []
_carpeta: list[Path] = []  # la carpeta de datos, si ya se conoce (una lista para no usar global)


def iniciar(data_dir: Path | None) -> None:
    """Empieza la bitácora de esta corrida. `data_dir` None o inexistente = solo pantalla."""
    _lineas.clear()
    _carpeta.clear()
    if data_dir is not None and data_dir.is_dir():
        _carpeta.append(data_dir)


def decir(mensaje: str, error: bool = False) -> None:
    """Muestra el mensaje y lo anota en el log del día (si hay carpeta de datos)."""
    typer.echo(mensaje, err=error)
    _lineas.append(mensaje)
    if _carpeta:
        logs = _carpeta[0] / "logs"
        logs.mkdir(exist_ok=True)  # bajo data_dir, que existe: se puede crear
        marca = datetime.now()
        with (logs / f"contratos_{marca:%Y%m%d}.log").open("a", encoding="utf-8") as f:
            for linea in mensaje.splitlines() or [""]:
                f.write(f"{marca:%Y-%m-%d %H:%M:%S}  {linea}\n")


def alertar(comando: str, codigo: int) -> Path | None:
    """Si el código es 1 o 3, deja el archivo de alerta. Devuelve su ruta (o None)."""
    if codigo not in (1, 3) or not _carpeta:
        return None
    alertas = _carpeta[0] / "alertas"
    alertas.mkdir(exist_ok=True)
    marca = datetime.now()
    ruta = alertas / f"ALERTA_{marca:%Y%m%d_%H%M%S}.txt"
    texto = [
        "ALERTA contratos-ingesta",
        f"Comando:  {comando}",
        f"Fecha:    {marca:%Y-%m-%d %H:%M:%S}",
        f"Código:   {codigo} ({NOMBRES.get(codigo, '?')})",
        f"Qué hacer: {QUE_HACER.get(codigo, '')}",
        "",
        "--- Salida de la corrida ---",
        *_lineas,
    ]
    ruta.write_text("\n".join(texto) + "\n", encoding="utf-8")
    return ruta
