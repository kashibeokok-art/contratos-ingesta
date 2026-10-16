"""Silver con un Excel chico de forma real (2 filas de encabezado, columnas reales)."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from contratos_ingesta import silver

COLUMNAS = [
    "Id Contrato", "Empresa Suministradora", "Rut Suministradora", "Tipo Suministrador",
    "Tipo Contrato", "Red Distribuidora", "Tipo Cliente", "Empresa Cliente", "Rut Empresa Cliente",
    "Suscripción", "Inicio", "Término", "Fecha Renovación", "Fecha Inicio Renovación",
    "Fecha Término Renovación", "Estado Contrato", "Afecto Ley", "Régimen Compra Potencia",
    "Correo Cliente", "Región", "Dirección Comercial", "Sector Económico", "Subsector Económico",
    "Listado de puntos de Suministro", "Listado de puntos de Retiro",
    "Energía 2026", "Energía 2027", "Energía 2040", "Potencia 2026", "Potencia 2027",
]  # fmt: skip

HOY = date(2026, 10, 15)


def _fila(**valores: object) -> list[object]:
    base: dict[str, object] = {c: None for c in COLUMNAS}
    base.update(
        {
            "Empresa Suministradora": "Colbún S.A.",
            "Empresa Cliente": "CLIENTE SA",
            "Correo Cliente": "privado@cliente.cl",
            "Dirección Comercial": "Calle 123",
        }
    )
    base.update(valores)
    return [base[c] for c in COLUMNAS]


def _excel(ruta: Path, filas: list[list[object]]) -> Path:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "contratos"
    hoja.append(["Información del Contrato"] + [None] * (len(COLUMNAS) - 1))  # fila de grupos
    hoja.append(COLUMNAS)
    for fila in filas:
        hoja.append(fila)
    libro.save(ruta)
    return ruta


@pytest.fixture
def excel(tmp_path: Path) -> Path:
    return _excel(
        tmp_path / "Contratos_publica_20261015_120000.xlsx",
        [
            # 100: vigente; 2 retiros + NULO; un año aislado (2040)
            _fila(**{"Id Contrato": "100", "Término": "2027-12-31 00:00:00",
                     "Estado Contrato": "Vigente", "Listado de puntos de Retiro":
                     "CHACAHUIN 13;BA S/E SAN JOAQUIN (CGE) 13.2KV C2;NULO",
                     "Listado de puntos de Suministro": "BA S/E LOS MAQUIS 220KV BP1-1 (AIS)",
                     "Energía 2026": "1400", "Energía 2027": "2000", "Energía 2040": "9999",
                     "Potencia 2026": "2", "Potencia 2027": "3.5"}),
            # 200: Término vencido, pero renovado hasta 05-03-2027 (texto DD-MM-AAAA): vigente
            _fila(**{"Id Contrato": "200", "Término": "2020-01-01 00:00:00",
                     "Fecha Término Renovación": "05-03-2027", "Estado Contrato": "Vigente"}),
            # 300: vencido
            _fila(**{"Id Contrato": "300", "Término": "2024-01-01 00:00:00",
                     "Estado Contrato": "No vigente", "Energía 2026": "5"}),
        ],
    )  # fmt: skip


def test_transformar_aplica_las_reglas(excel: Path) -> None:
    contratos, puntos, conteo = silver.transformar(silver.leer_excel(excel), HOY, HOY)
    c = contratos.set_index("id_contrato")

    assert list(c.index) == ["100", "200", "300"]  # ADR-C03: Silver guarda TODOS
    assert list(c["vigente"]) == [True, True, False]
    assert list(c["estado_distinto"]) == [False, False, False]
    assert c.loc["200", "fecha_termino_efectiva"] == date(2027, 3, 5)  # 5 de marzo (A21)
    assert c.loc["200", "dias_para_vencer"] == 141
    assert str(contratos["dias_para_vencer"].dtype) == "Int64"
    assert c.loc["100", "energia_max_anual_gwh"] == 2.0  # RN-05/08, sin 2040 (RN-07)
    assert c.loc["100", "anios_aislados"] == "2040"
    assert c.loc["200", "energia_max_anual_gwh"] == 0.0  # RN-09
    assert c.loc["100", "potencia_max_anual_mw"] == 3.5
    assert c.loc["100", "suministrador"] == "Colbún S.A."  # las tildes se conservan
    assert "correo_cliente" not in contratos.columns and "Correo Cliente" not in contratos.columns
    assert conteo == {
        "contratos": 3, "vigentes": 2, "no_vigentes": 1, "estado_distinto": 0,
        "sin_energia": 1, "anios_aislados": 1, "puntos": 3, "puntos_no_reconocidos": 0,
        "ids_repetidos": 0, "sin_id": 0,
    }  # fmt: skip
    retiros = puntos[(puntos["id_contrato"] == "100") & (puntos["tipo_punto"] == "retiro")]
    assert list(retiros["subestacion"]) == ["CHACAHUIN", "SAN JOAQUIN"]  # NULO no es un punto
    suministro = puntos[puntos["tipo_punto"] == "suministro"].iloc[0]
    assert (suministro["subestacion"], suministro["seccion"]) == ("LOS MAQUIS", "BP1-1")


def test_estado_distinto_marca_sin_cambiar_la_vigencia(tmp_path: Path) -> None:
    """Caso real (contratos 13361 y 8885): la fuente dice No vigente y el término es futuro."""
    ruta = _excel(
        tmp_path / "x.xlsx",
        [_fila(**{"Id Contrato": "13361", "Término": "2029-12-31 00:00:00",
                  "Fecha Término Renovación": "31-12-2025", "Estado Contrato": "No vigente"})],
    )  # fmt: skip
    contratos, _p, conteo = silver.transformar(silver.leer_excel(ruta), HOY, HOY)

    assert bool(contratos.loc[0, "vigente"]) is True  # manda la fecha
    assert bool(contratos.loc[0, "estado_distinto"]) is True  # pero queda marcado
    assert conteo["estado_distinto"] == 1


def test_la_vigencia_se_calcula_contra_hoy_no_contra_el_excel(tmp_path: Path) -> None:
    """Mejora 8.1. Escenario: el Excel es del 1-oct y no cambió; hoy es 20-oct. Un contrato
    que vence el 10-oct ya NO está vigente, aunque al 1-oct lo estaba."""
    ruta = _excel(
        tmp_path / "x.xlsx",
        [
            _fila(
                **{
                    "Id Contrato": "1",
                    "Término": "2026-10-10 00:00:00",
                    "Estado Contrato": "Vigente",
                }
            )
        ],
    )
    contratos, _p, _c = silver.transformar(
        silver.leer_excel(ruta), date(2026, 10, 1), date(2026, 10, 20)
    )
    fila = contratos.iloc[0]

    assert bool(fila["vigente"]) is False
    assert fila["dias_para_vencer"] == -10
    assert (fila["fecha_datos"], fila["fecha_calculo"]) == (date(2026, 10, 1), date(2026, 10, 20))


def test_falta_una_columna_se_detiene(tmp_path: Path) -> None:
    tabla = pd.DataFrame({"Id Contrato": ["1"]})

    with pytest.raises(silver.FormatoDesconocido, match="Empresa Suministradora"):
        silver.transformar(tabla, HOY, HOY)


def test_fecha_ingreso_se_conserva_entre_corridas(excel: Path) -> None:
    contratos, _p, _c = silver.transformar(silver.leer_excel(excel), HOY, HOY)
    conocidas = {"100": "2026-01-01"}

    marcados, nuevas = silver.marcar_fecha_ingreso(contratos, conocidas, HOY)

    fechas = dict(zip(marcados["id_contrato"], marcados["fecha_ingreso"], strict=True))
    assert fechas == {"100": date(2026, 1, 1), "200": HOY, "300": HOY}
    assert nuevas["200"] == "2026-10-15"


def test_un_excel_mas_viejo_deja_la_fecha_mas_antigua(excel: Path) -> None:
    contratos, _p, _c = silver.transformar(silver.leer_excel(excel), date(2026, 9, 1), HOY)

    _m, nuevas = silver.marcar_fecha_ingreso(contratos, {"100": "2026-10-15"}, date(2026, 9, 1))

    assert nuevas["100"] == "2026-09-01"


def test_escribir_deja_las_tablas_y_el_control(excel: Path, tmp_path: Path) -> None:
    destino = tmp_path / "silver"
    destino.mkdir()
    contratos, puntos, conteo = silver.transformar(silver.leer_excel(excel), HOY, HOY)
    contratos, fechas = silver.marcar_fecha_ingreso(contratos, {}, HOY)

    silver.escribir(destino, contratos, puntos, fechas, excel.name, conteo)

    leidos = pd.read_parquet(destino / "contratos.parquet")
    assert len(leidos) == 3 and leidos["fecha_ingreso"].notna().all()
    assert len(pd.read_parquet(destino / "contrato_barra.parquet")) == 3
    assert silver.leer_control(destino) == fechas
    assert not list(destino.glob("*.tmp"))
