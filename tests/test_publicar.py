"""Publicar en PostgreSQL. Pruebas de integración contra un servidor de PRUEBA, nunca el real.

Se saltan si no está la variable PRUEBA_PG_CONTRATOS (conexión de administrador), p. ej.:

    $env:PRUEBA_PG_CONTRATOS = "host=localhost port=55433 user=postgres"

Cada test crea una base nueva, le corre sql/esquema_contratos.sql y publica como
contratos_carga, igual que en el servidor.
"""

import os
import uuid
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import pytest

from contratos_ingesta import publicar, silver
from contratos_ingesta.config import RAIZ_PROYECTO
from tests.test_silver import _excel, _fila

ADMIN = os.environ.get("PRUEBA_PG_CONTRATOS")
pytestmark = pytest.mark.skipif(not ADMIN, reason="sin PRUEBA_PG_CONTRATOS (PostgreSQL de prueba)")
HOY = date(2026, 10, 15)


@pytest.fixture
def base() -> Iterator[str]:
    """Una base de prueba con el esquema real. Devuelve la conexión como contratos_carga."""
    assert ADMIN
    nombre = f"contratos_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN, autocommit=True) as con:
        con.execute(f"CREATE DATABASE {nombre}")
        con.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cmg_lectura') "
            "THEN CREATE ROLE cmg_lectura LOGIN; END IF; END $$"
        )
    esquema = (RAIZ_PROYECTO / "sql" / "esquema_contratos.sql").read_text(encoding="utf-8")
    with psycopg.connect(f"{ADMIN} dbname={nombre}", autocommit=True) as con:
        con.execute(esquema.encode())  # varias sentencias: sin parámetros se permite
    yield f"{ADMIN.replace('user=postgres', '')} dbname={nombre} user=contratos_carga"
    with psycopg.connect(ADMIN, autocommit=True) as con:
        con.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")


def _silver(carpeta: Path, ids: list[str]) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    excel = _excel(
        carpeta / "Contratos_publica_20261015_120000.xlsx",
        [
            _fila(**{"Id Contrato": i, "Término": "2030-01-01 00:00:00", "Estado Contrato":
                     "Vigente", "Listado de puntos de Retiro": "CHACAHUIN 13;BA S/E A 220KV BP1",
                     "Energía 2026": "1000"})
            for i in ids
        ],
    )  # fmt: skip
    contratos, puntos, conteo = silver.transformar(silver.leer_excel(excel), HOY, HOY)
    contratos, fechas = silver.marcar_fecha_ingreso(contratos, {}, HOY)
    silver.escribir(carpeta, contratos, puntos, fechas, excel.name, conteo)
    return carpeta


def _contar(conexion: str) -> tuple[int, int, int]:
    with psycopg.connect(conexion) as con:
        fila = con.execute(
            "SELECT (SELECT count(*) FROM contratos.contrato), "
            "(SELECT count(*) FROM contratos.contrato_barra), "
            "(SELECT count(*) FROM contratos.carga)"
        ).fetchone()
    assert fila is not None
    return int(fila[0]), int(fila[1]), int(fila[2])


def test_publica_todo_y_registra_la_carga(base: str, tmp_path: Path) -> None:
    datos = _silver(tmp_path / "s", ["1", "2"])

    with psycopg.connect(base) as con:
        res = publicar.publicar(con, datos)

    assert res["subido"] and (res["contratos"], res["puntos"]) == (2, 4)
    assert _contar(base) == (2, 4, 1)
    with psycopg.connect(base) as con:
        fila = con.execute(
            "SELECT vigente, fecha_ingreso, energia_max_anual_gwh, dias_para_vencer "
            "FROM contratos.contrato WHERE id_contrato = '1'"
        ).fetchone()
        origen = con.execute("SELECT archivo_origen FROM contratos.carga").fetchone()
    assert fila == (True, HOY, 1.0, 1174)
    assert origen == ("Contratos_publica_20261015_120000.xlsx",)


def test_sin_cambios_no_sube_y_forzar_si(base: str, tmp_path: Path) -> None:
    datos = _silver(tmp_path / "s", ["1"])
    with psycopg.connect(base) as con:
        publicar.publicar(con, datos)
        segunda = publicar.publicar(con, datos)
        forzada = publicar.publicar(con, datos, forzar=True)

    assert not segunda["subido"] and forzada["subido"]
    assert _contar(base) == (1, 2, 2)


def test_reemplaza_lo_anterior(base: str, tmp_path: Path) -> None:
    with psycopg.connect(base) as con:
        publicar.publicar(con, _silver(tmp_path / "a", ["1", "2", "3"]))
        publicar.publicar(con, _silver(tmp_path / "b", ["9"]))

    assert _contar(base)[:2] == (1, 2)


def test_un_fallo_a_la_mitad_deja_la_base_como_estaba(base: str, tmp_path: Path) -> None:
    """Atomicidad (ADR-C06): un punto inválido hace fallar el COPY después de borrar."""
    with psycopg.connect(base) as con:
        publicar.publicar(con, _silver(tmp_path / "a", ["1", "2"]))
    malo = _silver(tmp_path / "b", ["7"])
    puntos = pd.read_parquet(malo / publicar.PUNTOS)
    puntos.loc[0, "tipo_punto"] = "otro"  # viola el CHECK de la tabla
    puntos.to_parquet(malo / publicar.PUNTOS, index=False)

    with psycopg.connect(base) as con, pytest.raises(psycopg.errors.CheckViolation):
        publicar.publicar(con, malo)

    assert _contar(base) == (2, 4, 1)  # los 2 contratos de antes siguen ahí
    with psycopg.connect(base) as con:  # y el historial no anotó nada de la carga fallida
        assert con.execute("SELECT count(*) FROM contratos.contrato_historial").fetchone() == (2,)


def test_ids_repetidos_no_tocan_la_base(base: str, tmp_path: Path) -> None:
    datos = _silver(tmp_path / "s", ["1", "1"])

    with psycopg.connect(base) as con, pytest.raises(publicar.DatosInvalidos, match="repetidos"):
        publicar.publicar(con, datos)

    assert _contar(base) == (0, 0, 0)


def test_cmg_lectura_lee_pero_no_escribe(base: str, tmp_path: Path) -> None:
    with psycopg.connect(base) as con:
        publicar.publicar(con, _silver(tmp_path / "s", ["1"]))
    lectura = base.replace("user=contratos_carga", "user=cmg_lectura")

    with psycopg.connect(lectura) as con:
        assert con.execute("SELECT count(*) FROM contratos.contrato").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("DELETE FROM contratos.contrato")


def test_la_vista_recalcula_la_vigencia_con_el_dia_de_chile(base: str, tmp_path: Path) -> None:
    """Mejora 8.1: Silver calculado en 2020 dice vigente; la vista, hoy, dice que no."""
    carpeta = tmp_path / "s"
    carpeta.mkdir()
    excel = _excel(
        carpeta / "Contratos_publica_20200101_120000.xlsx",
        [
            _fila(
                **{
                    "Id Contrato": "1",
                    "Término": "2025-01-01 00:00:00",
                    "Estado Contrato": "Vigente",
                }
            )
        ],
    )
    antiguo = date(2020, 1, 1)
    contratos, puntos, conteo = silver.transformar(silver.leer_excel(excel), antiguo, antiguo)
    contratos, fechas = silver.marcar_fecha_ingreso(contratos, {}, antiguo)
    silver.escribir(carpeta, contratos, puntos, fechas, excel.name, conteo)
    with psycopg.connect(base) as con:
        publicar.publicar(con, carpeta)

    lectura = base.replace("user=contratos_carga", "user=cmg_lectura")
    with psycopg.connect(lectura) as con:
        tabla = con.execute("SELECT vigente FROM contratos.contrato").fetchone()
        vista = con.execute(
            "SELECT vigente, estado_distinto, dias_para_vencer, fecha_calculo "
            "FROM contratos.contrato_hoy"
        ).fetchone()
    hoy_chile = datetime.now(ZoneInfo("America/Santiago")).date()
    assert tabla == (True,)  # lo guardado, calculado en 2020
    assert vista == (False, True, (date(2025, 1, 1) - hoy_chile).days, hoy_chile)


def _silver_energia(carpeta: Path, energias: dict[str, str], hoy: date = HOY) -> Path:
    """Silver con un contrato por ID y su energía 2026 en MWh."""
    carpeta.mkdir(parents=True, exist_ok=True)
    excel = _excel(
        carpeta / "Contratos_publica_20261015_120000.xlsx",
        [
            _fila(**{"Id Contrato": i, "Término": "2030-01-01 00:00:00", "Estado Contrato":
                     "Vigente", "Energía 2026": e})
            for i, e in energias.items()
        ],
    )  # fmt: skip
    contratos, puntos, conteo = silver.transformar(silver.leer_excel(excel), HOY, hoy)
    contratos, fechas = silver.marcar_fecha_ingreso(contratos, {}, HOY)
    silver.escribir(carpeta, contratos, puntos, fechas, excel.name, conteo)
    return carpeta


def _historial(conexion: str) -> list[tuple[str, str, list[str]]]:
    with psycopg.connect(conexion) as con:
        filas = con.execute(
            "SELECT id_contrato, cambio, columnas FROM contratos.contrato_historial "
            "WHERE carga_id = (SELECT max(carga_id) FROM contratos.carga) ORDER BY id_contrato"
        ).fetchall()
    return [(str(a), str(b), list(c)) for a, b, c in filas]


def test_historial_anota_altas_cambios_y_bajas(base: str, tmp_path: Path) -> None:
    """Mejora 8.3: el 1 cambia su energía, el 2 sigue igual, el 3 desaparece, el 4 aparece."""
    with psycopg.connect(base) as con:
        primera = publicar.publicar(
            con, _silver_energia(tmp_path / "a", {"1": "1000", "2": "1000", "3": "1000"})
        )
        assert primera["historial"] == 3  # la primera carga: todo es alta
        segunda = publicar.publicar(
            con, _silver_energia(tmp_path / "b", {"1": "2000", "2": "1000", "4": "500"})
        )

    assert segunda["historial"] == 3
    assert _historial(base) == [
        (
            "1",
            "cambio",
            ["energia_max_anual_gwh", "energia_promedio_anual_gwh", "energia_min_anual_gwh"],
        ),
        ("3", "baja", []),
        ("4", "alta", []),
    ]
    with psycopg.connect(base) as con:
        antes_despues = con.execute(
            "SELECT (antes->>'energia_max_anual_gwh')::float, "
            "(despues->>'energia_max_anual_gwh')::float "
            "FROM contratos.contrato_historial WHERE cambio = 'cambio'"
        ).fetchone()
    assert antes_despues == (1.0, 2.0)


def test_un_cambio_solo_del_dia_no_va_al_historial(base: str, tmp_path: Path) -> None:
    """Silver de otro día (otra fecha_calculo, otros dias_para_vencer): se sube, pero no es un
    cambio del contrato."""
    with psycopg.connect(base) as con:
        publicar.publicar(con, _silver_energia(tmp_path / "a", {"1": "1000"}))
        otro_dia = publicar.publicar(
            con, _silver_energia(tmp_path / "b", {"1": "1000"}, date(2026, 11, 1))
        )

    assert otro_dia["subido"] and otro_dia["historial"] == 0
