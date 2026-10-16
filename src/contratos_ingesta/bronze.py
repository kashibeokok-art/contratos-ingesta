"""Bronze: descargar el Excel público de contratos y guardarlo tal cual, solo si cambió.

La fuente (verificada el 2026-10-15): un API Gateway público, sin clave, que devuelve un
enlace temporal de S3 al Excel `Contratos_publica.xlsx`:

    {"message": "ok",
     "data": {"url": "...", "status": "ready", "cached": true, "age_minutes": 2850.9}}

El legado esperaba `data` como el enlace (texto) y hoy fallaría. Aquí se acepta solo la
forma conocida; cualquier otra detiene la descarga con un mensaje claro (fail fast).

En Bronze queda:

    <bronze>/Contratos_publica_AAAAMMDD_HHMMSS.xlsx   (una copia por cada versión distinta)
    <bronze>/manifiesto.json                           (sha256, tamaño, fecha de cada copia)

Si el Excel es idéntico (mismo sha256) al último guardado, no se guarda otra copia.
"""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import httpx

URL_API = "https://icdp0af7ze.execute-api.us-east-1.amazonaws.com/prod/public"
PARAMS = {
    "type": "descarga_publica",
    "empresa": "",
    "cliente": "",
    "tipoContrato": "",
    "suscripcion": "",
    "inicio": "",
    "termino": "",
    "idContrato": "",
    "iniciofechaTermino": "",
    "finfechaTermino": "",
}
HEADERS = {"origin": "https://plataformamercado.coordinador.cl", "accept": "application/json"}
REINTENTOS = 3
MANIFIESTO = "manifiesto.json"


class ErrorDescarga(RuntimeError):
    """La API o el enlace no respondieron como se esperaba."""


class Entrada(TypedDict):
    archivo: str
    bytes: int
    sha256: str
    descargado_en: str  # UTC, ISO 8601
    edad_minutos: float | None  # antigüedad que informa la API (su Excel se regenera)


class Resultado(TypedDict):
    ruta: Path
    nuevo: bool  # False = idéntico al último: no se guardó otra copia


def enlace(respuesta: object) -> tuple[str, float | None]:
    """(url, antigüedad en minutos) de la respuesta de la API. Función pura."""
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get("data"), dict):
        raise ErrorDescarga(f"respuesta de la API con forma desconocida: {str(respuesta)[:200]}")
    data = respuesta["data"]
    url = data.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ErrorDescarga(f"la API no entregó un enlace de descarga: {str(data)[:200]}")
    edad = data.get("age_minutes")
    return url, float(edad) if isinstance(edad, int | float) else None


def pedir(cliente: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
    """GET con reintentos SOLO ante errores transitorios (red, 429, 5xx). Nunca ante un 403."""
    for intento in range(1, REINTENTOS + 1):
        try:
            r = cliente.get(url, **kwargs)  # type: ignore[arg-type]
        except httpx.TransportError as e:
            if intento == REINTENTOS:
                raise ErrorDescarga(f"sin conexión con {url.split('?')[0]}: {e}") from e
            time.sleep(2**intento)
            continue
        if r.status_code in (429, 500, 502, 503, 504) and intento < REINTENTOS:
            time.sleep(2**intento)
            continue
        if r.status_code != 200:
            raise ErrorDescarga(f"{url.split('?')[0]} respondió HTTP {r.status_code}")
        return r
    raise ErrorDescarga("sin respuesta tras varios intentos")


def leer_manifiesto(base: Path) -> list[Entrada]:
    ruta = base / MANIFIESTO
    if not ruta.is_file():
        return []
    entradas: list[Entrada] = json.loads(ruta.read_text(encoding="utf-8"))["archivos"]
    return entradas


def _guardar_manifiesto(base: Path, entradas: list[Entrada]) -> None:
    """Atómico: .tmp + reemplazo, para que un corte nunca deje el manifiesto a medias."""
    tmp = base / (MANIFIESTO + ".tmp")
    tmp.write_text(json.dumps({"archivos": entradas}, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(base / MANIFIESTO)


def descargar(base: Path, cliente: httpx.Client | None = None) -> Resultado:
    """API -> Excel en Bronze. Si es idéntico al último guardado, no se guarda otra copia."""
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))
    try:
        url, edad = enlace(pedir(cliente, URL_API, params=PARAMS, headers=HEADERS).json())
        contenido = pedir(cliente, url).content
    finally:
        if propio:
            cliente.close()
    if contenido[:4] != b"PK\x03\x04":
        raise ErrorDescarga("lo descargado no es un Excel (.xlsx)")

    huella = hashlib.sha256(contenido).hexdigest()
    entradas = leer_manifiesto(base)
    if entradas and entradas[-1]["sha256"] == huella and (base / entradas[-1]["archivo"]).is_file():
        return {"ruta": base / entradas[-1]["archivo"], "nuevo": False}

    destino = base / f"Contratos_publica_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    parcial = destino.with_name(destino.name + ".part")
    try:
        parcial.write_bytes(contenido)
        parcial.replace(destino)  # el archivo aparece completo o no aparece
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    entradas.append(
        {
            "archivo": destino.name,
            "bytes": len(contenido),
            "sha256": huella,
            "descargado_en": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "edad_minutos": edad,
        }
    )
    _guardar_manifiesto(base, entradas)
    return {"ruta": destino, "nuevo": True}


def todos(base: Path) -> list[Path]:
    """Todos los Excel de Bronze que existen, del más antiguo al más nuevo."""
    return [base / e["archivo"] for e in leer_manifiesto(base) if (base / e["archivo"]).is_file()]


def ultimo(base: Path) -> Path | None:
    """El último Excel guardado en Bronze (o None si no hay)."""
    existentes = [e for e in leer_manifiesto(base) if (base / e["archivo"]).is_file()]
    return base / existentes[-1]["archivo"] if existentes else None
