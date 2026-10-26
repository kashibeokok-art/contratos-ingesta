"""GUIA_MANTENIMIENTO.md: lo que nombra existe de verdad, y no le falta nada de lo que hay.

La guía la lee alguien que no va a abrir el código: un comando, una opción, una sección de
config/ o una variable del .env que no existe lo dejaría sin salida. Estas pruebas fallan si
el código cambia y la guía no (o al revés).
"""

import re

from contratos_ingesta import alertas
from contratos_ingesta.config import PREFIJO, Settings
from tests.test_alertas import (
    GUIA,
    RE_ARCHIVO,
    RE_CAMPO,
    RE_SECCION,
    _seccion,
    _tomls,
    comandos_de_la_cli,
)

TEXTO = GUIA.read_text(encoding="utf-8")
#: Sin los enlaces de Markdown: `[6.1](#61-...)` no es una sección de config/.
SIN_ENLACES = re.sub(r"\[[^\]]*\]\([^)]*\)", "", TEXTO)

SECCIONES = [
    "Qué hace el programa", "Lo que necesita", "Instalar en un equipo nuevo", "La rutina",
    "Ante cualquier problema", "Recetas: si pasa X, haz Y", "Fichas de alertas",
    "Los archivos editables", "Todos los comandos", "Lo que no hay que tocar",
    "Cuándo hace falta un programador", "Problemas conocidos", "Glosario",
]  # fmt: skip


def test_tiene_las_13_secciones_en_orden() -> None:
    titulos = re.findall(r"^## (\d+)\. (.+)$", TEXTO, re.MULTILINE)
    assert titulos == [(str(i), t) for i, t in enumerate(SECCIONES, 1)]


def test_los_enlaces_internos_llevan_a_un_titulo() -> None:
    """Un enlace `(#61-...)` que no calza con ningún título no lleva a ninguna parte."""

    def ancla(titulo: str) -> str:  # como las arma GitHub y VS Code
        return re.sub(r"[^\w\- ]", "", titulo.strip().lower()).replace(" ", "-")

    anclas = {ancla(t) for t in re.findall(r"^#{2,4} (.+)$", TEXTO, re.MULTILINE)}
    rotos = sorted({e for e in re.findall(r"\]\(#([^)]+)\)", TEXTO) if e not in anclas})
    assert not rotos, f"enlaces que no llevan a ningún título: {rotos}"


# ------------------------------------------------------------ comandos


RE_COMANDO_GUIA = re.compile(r"(?:uv run contratos|`contratos) ([a-z][a-z-]+)")
#: En la sección 9, la primera columna de cada tabla es el comando.
RE_FILA_COMANDO = re.compile(r"^\| `([a-z-]+)", re.MULTILINE)


def _seccion_9() -> str:
    return TEXTO[TEXTO.index("## 9. Todos los comandos") : TEXTO.index("## 10.")]


def _comandos_nombrados() -> set[str]:
    sueltos = set(RE_COMANDO_GUIA.findall(TEXTO)) - {"COMANDO"}
    return sueltos | set(RE_FILA_COMANDO.findall(_seccion_9()))


def test_los_comandos_que_nombra_existen() -> None:
    inventados = sorted(_comandos_nombrados() - comandos_de_la_cli())
    assert not inventados, f"la guía nombra comandos que no existen: {inventados}"


def test_todos_los_comandos_estan_en_la_guia() -> None:
    faltan = sorted(c for c in comandos_de_la_cli() if f"`{c}" not in _seccion_9())
    assert not faltan, f"comandos sin explicar en la sección 9: {faltan}"


def test_las_opciones_que_nombra_existen() -> None:
    """Las opciones salen de la ayuda real de cada comando (`--help`)."""
    from typer.testing import CliRunner

    from contratos_ingesta import cli

    opciones: set[str] = set()
    for comando in comandos_de_la_cli():
        ayuda = CliRunner().invoke(cli.app, [comando, "--help"], env={"COLUMNS": "200"}).output
        opciones |= set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", ayuda))
    assert {"--forzar", "--archivo", "--sin-red", "--help"} <= opciones  # la búsqueda las ve
    nombradas = set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", TEXTO))
    assert not nombradas - opciones, f"opciones que no existen: {sorted(nombradas - opciones)}"


# ------------------------------------------------------------ config/ y .env


def test_las_secciones_y_campos_de_config_que_nombra_existen() -> None:
    tomls = _tomls()
    for archivo in RE_ARCHIVO.findall(TEXTO):
        assert f"config/{archivo}" in tomls, f"no existe config/{archivo}"
    nombradas = set(RE_SECCION.findall(SIN_ENLACES))
    malas = sorted(
        s for s in nombradas if not any(isinstance(_seccion(t, s), dict) for t in tomls.values())
    )
    assert len(nombradas) >= 10, nombradas  # si no, la búsqueda dejó de verlas
    assert not malas, f"la guía nombra secciones de config/ que no existen: {malas}"
    for campo, seccion in RE_CAMPO.findall(SIN_ENLACES):
        assert any(
            isinstance(s := _seccion(t, seccion), dict) and campo in s for t in tomls.values()
        ), f"'{campo}' no está en [{seccion}]"


def test_los_campos_de_las_tablas_de_la_seccion_8_existen() -> None:
    """`campo` de `[sección]` en las tablas de referencia."""
    tomls = _tomls()
    pares = re.findall(r"`(\w+)`(?:, `(\w+)`)? de `\[([a-z_.]+)\]`", TEXTO)
    assert len(pares) >= 10
    for campo, otro, seccion in pares:
        for c in filter(None, (campo, otro)):
            assert any(
                isinstance(s := _seccion(t, seccion), dict) and c in s for t in tomls.values()
            ), f"'{c}' no está en [{seccion}]"


def test_cada_campo_de_config_esta_explicado() -> None:
    """Nada de config/ queda sin explicar en la sección 8."""
    seccion_8 = TEXTO[TEXTO.index("## 8. Los archivos editables") : TEXTO.index("## 9.")]
    faltan = []
    for archivo, datos in _tomls().items():
        assert f"`{archivo}`" in seccion_8, archivo
        pila: list[tuple[str, dict[str, object]]] = [("", datos)]
        while pila:
            prefijo, tabla = pila.pop()
            for clave, valor in tabla.items():
                nombre = f"{prefijo}.{clave}" if prefijo else clave
                if isinstance(valor, dict):
                    if f"[{nombre}]" not in seccion_8:  # una tabla se explica entera
                        pila.append((nombre, valor))
                elif f"`{clave}`" not in seccion_8:
                    faltan.append(f"{archivo} {nombre}")
    assert not faltan, f"campos de config/ sin explicar en la sección 8: {faltan}"


def test_las_variables_del_env_son_las_que_existen() -> None:
    validas = {f"{PREFIJO}{c}".upper() for c in Settings.model_fields}
    nombradas = set(re.findall(rf"\b{PREFIJO}[A-Z_]+\b", TEXTO))
    assert nombradas == validas, (sorted(nombradas - validas), sorted(validas - nombradas))


# ------------------------------------------------------------ alertas y rutina


def test_cada_alerta_tiene_su_ficha() -> None:
    fichas = set(re.findall(r"^#### `(\w+)`$", TEXTO, re.MULTILINE))
    assert fichas == set(alertas.CATALOGO), (
        sorted(set(alertas.CATALOGO) - fichas),
        sorted(fichas - set(alertas.CATALOGO)),
    )


def test_la_tarea_programada_devuelve_el_codigo_real() -> None:
    assert "uv run contratos actualizar" in TEXTO and "exit $LASTEXITCODE" in TEXTO


def test_no_muestra_la_clave() -> None:
    """La guía se comparte: la clave de PostgreSQL no puede estar escrita."""
    assert re.search(r"CONT_PG_CLAVE=la-clave-de-contratos_carga", TEXTO)
    assert not re.search(r"password\s*=", TEXTO, re.IGNORECASE)
