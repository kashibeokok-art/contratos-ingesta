"""Bronze con un servidor simulado (httpx.MockTransport): no toca la red."""

from pathlib import Path

import httpx
import pytest

from contratos_ingesta import bronze

EXCEL = b"PK\x03\x04 contenido de prueba"


def servidor(excel: bytes = EXCEL, estado_api: int = 200, fallas: int = 0) -> httpx.Client:
    """API + S3 simulados. `fallas`: cuántas veces responde 503 antes de responder bien."""
    pendientes = {"n": fallas}

    def responder(request: httpx.Request) -> httpx.Response:
        if "execute-api" in str(request.url):
            if pendientes["n"]:
                pendientes["n"] -= 1
                return httpx.Response(503)
            datos = {"message": "ok", "data": {"url": "https://s3/c.xlsx", "age_minutes": 5}}
            return httpx.Response(estado_api, json=datos)
        return httpx.Response(200, content=excel)

    return httpx.Client(transport=httpx.MockTransport(responder))


def test_primera_descarga_guarda_y_registra(tmp_path: Path) -> None:
    res = bronze.descargar(tmp_path, servidor())

    assert res["nuevo"] and res["ruta"].read_bytes() == EXCEL
    entrada = bronze.leer_manifiesto(tmp_path)[0]
    assert (entrada["archivo"], entrada["bytes"], entrada["edad_minutos"]) == (
        res["ruta"].name,
        len(EXCEL),
        5.0,
    )


def test_excel_identico_no_se_guarda_dos_veces(tmp_path: Path) -> None:
    primero = bronze.descargar(tmp_path, servidor())
    segundo = bronze.descargar(tmp_path, servidor())

    assert not segundo["nuevo"] and segundo["ruta"] == primero["ruta"]
    assert len(bronze.leer_manifiesto(tmp_path)) == 1


def test_excel_distinto_se_guarda_aparte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bronze.descargar(tmp_path, servidor())
    otra = bronze.descargar(tmp_path, servidor(EXCEL + b" cambio"))

    assert otra["nuevo"]
    assert len(bronze.leer_manifiesto(tmp_path)) == 2
    assert bronze.ultimo(tmp_path) == otra["ruta"]


def test_errores_transitorios_se_reintentan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("contratos_ingesta.bronze.time.sleep", lambda _s: None)

    assert bronze.descargar(tmp_path, servidor(fallas=2))["nuevo"]


def test_403_no_se_reintenta(tmp_path: Path) -> None:
    """Una clave o un bloqueo no se arreglan esperando (receta §5.1)."""
    with pytest.raises(bronze.ErrorDescarga, match="HTTP 403"):
        bronze.descargar(tmp_path, servidor(estado_api=403))


def test_lo_que_no_es_excel_no_entra(tmp_path: Path) -> None:
    with pytest.raises(bronze.ErrorDescarga, match="no es un Excel"):
        bronze.descargar(tmp_path, servidor(b"<html>error</html>"))
    assert list(tmp_path.iterdir()) == []


def test_enlace_acepta_la_forma_actual_y_rechaza_la_del_legado() -> None:
    assert bronze.enlace({"data": {"url": "https://s3/x.xlsx", "age_minutes": 1}}) == (
        "https://s3/x.xlsx",
        1.0,
    )
    with pytest.raises(bronze.ErrorDescarga):
        bronze.enlace({"data": "https://s3/x.xlsx"})  # lo que esperaba OLD/funciones.py:82
