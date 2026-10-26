"""Las alertas las lee alguien que NO va a abrir el código (decisión del usuario, 2026-10-26).

Estas pruebas leen el código fuente por AST y exigen que:

1. ningún mensaje de error o de aviso quede suelto: todos pasan por `alertas` (que les agrega
   qué hacer y el tipo, para buscar su ficha en la guía);
2. ningún texto que lee la persona nombre un .py, una constante, una función interna ni a
   "Claude", ni la mande a tocar el código;
3. lo que nombran (archivos y secciones de config/, campos, comandos) exista de verdad;
4. cada tipo de alerta tenga su ficha en GUIA_MANTENIMIENTO.md.

Y que la revisión 1 habría atrapado los mensajes de antes del paso 5 (copia congelada en
tests/mensajes_viejos/).
"""

import ast
import re
import tomllib
from pathlib import Path

import pytest

from contratos_ingesta import alertas, bitacora, cli
from contratos_ingesta.config import RAIZ_PROYECTO

SRC = RAIZ_PROYECTO / "src" / "contratos_ingesta"
CONFIG = RAIZ_PROYECTO / "config"
GUIA = RAIZ_PROYECTO / "GUIA_MANTENIMIENTO.md"
VIEJOS = Path(__file__).parent / "mensajes_viejos"

#: Las excepciones que terminan en pantalla: su mensaje tiene que ser una alerta.
ERRORES = {"ErrorDescarga", "FormatoDesconocido", "DatosInvalidos", "ValueError"}
#: Los módulos que validan config/ y el .env: sus errores dicen archivo, sección y qué corregir
#: con su propio texto (los envuelven `config_invalida` y `env_invalido` al mostrarlos).
VALIDAN_CONFIG = {"toml_editable.py", "fuente.py", "excel.py", "reglas.py", "config.py"}
#: Cierres de un comando que ya mostró arriba cada problema con su qué hacer.
RESUMENES = (
    "Corrige lo marcado MAL",  # revisar-config: cada MAL ya dice qué corregir
    "Hay algo que corregir (MAL)",  # diagnostico: cada MAL ya trae su "qué hacer"
    "Funciona, pero hay avisos",
    "NO entraría a Silver",  # probar-excel: lleva la alerta que lo impide
    "Entraría a Silver, con algo que revisar",
)
FUNCIONES_ALERTA = {"mensaje", "error", "hallazgo", "lineas"}


def _texto(nodo: ast.AST) -> str:
    """Todo el texto literal de una expresión (constantes, f-strings, concatenaciones)."""
    return " ".join(
        n.value for n in ast.walk(nodo) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )


def _llama_a_alertas(nodo: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "alertas"
        and n.func.attr in FUNCIONES_ALERTA
        for n in ast.walk(nodo)
    )


def _es_problema(codigo: ast.AST) -> bool:
    """`_salir(ERROR, ...)` o `_salir(REVISAR, ...)`: el comando terminó con 1 o 3."""
    return any(isinstance(n, ast.Name) and n.id in ("ERROR", "REVISAR") for n in ast.walk(codigo))


#: Una línea que empieza con "revisar:", "aviso:" o "error:": un aviso escrito a mano.
RE_AVISO_A_MANO = re.compile(r"\s*(revisar|aviso|error)\s*:", re.IGNORECASE)


def _imprime(func: ast.AST) -> bool:
    """`bitacora.decir(...)`, `d(...)` (su alias) o `lineas.append(...)`."""
    if isinstance(func, ast.Attribute):
        return func.attr in ("decir", "append")
    return isinstance(func, ast.Name) and func.id in ("d", "decir")


def sueltos(fuente: str, archivo: str) -> list[str]:
    """Los mensajes de error o de aviso que NO pasan por `alertas` (revisión 1)."""
    salida: list[str] = []
    for n in ast.walk(ast.parse(fuente)):
        if (
            isinstance(n, ast.Raise)
            and isinstance(n.exc, ast.Call)
            and isinstance(n.exc.func, ast.Name)
            and n.exc.func.id in ERRORES
            and archivo not in VALIDAN_CONFIG
            and n.exc.args
            and not _llama_a_alertas(n.exc.args[0])
        ):
            salida.append(f"{archivo}:{n.lineno}: {n.exc.func.id} sin qué hacer")
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_salir"
            and len(n.args) >= 2
            and _es_problema(n.args[0])
            and not _llama_a_alertas(n.args[1])
            and not any(r in _texto(n.args[1]) for r in RESUMENES)
        ):
            salida.append(f"{archivo}:{n.lineno}: mensaje de error sin qué hacer")
        if (
            isinstance(n, ast.Call)
            and _imprime(n.func)
            and n.args
            and RE_AVISO_A_MANO.match(_texto(n.args[0]))
            and not _llama_a_alertas(n.args[0])
        ):
            salida.append(f"{archivo}:{n.lineno}: aviso impreso a mano (sin qué hacer)")
        if (
            isinstance(n, ast.Dict)
            and archivo != "alertas.py"
            and any(isinstance(k, ast.Constant) and k.value == "severidad" for k in n.keys)
        ):
            salida.append(f"{archivo}:{n.lineno}: hallazgo armado a mano (sin qué hacer)")
    return salida


def _fuentes() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(SRC.rglob("*.py"))}


# ------------------------------------------------------ 1. nada suelto


def test_ningun_mensaje_queda_suelto() -> None:
    malos = [m for archivo, fuente in _fuentes().items() for m in sueltos(fuente, archivo)]
    assert not malos, "\n".join(malos)


def test_la_revision_habria_atrapado_los_mensajes_viejos() -> None:
    """Los mensajes de antes del paso 5 (copia congelada) no la pasan: la revisión sirve."""
    por_archivo = {
        p.name.removesuffix(".txt"): sueltos(p.read_text(encoding="utf-8"), p.name)
        for p in sorted(VIEJOS.glob("*.py.txt"))
    }
    cuantos = {archivo: len(m) for archivo, m in por_archivo.items()}
    # uno por cada mensaje que el paso 5 reescribió
    assert cuantos == {
        "bronze.py": 6, "cli.py": 21, "deriva.py": 6, "mantencion.py": 1, "publicar.py": 5,
        "rutas.py": 1, "silver.py": 3,
    }, cuantos  # fmt: skip


#: (archivo, línea, tipo, detalle) de cada `alertas.mensaje(...)` y `alertas.hallazgo(...)`.
Sitio = tuple[str, int, str, str]


def sitios() -> list[Sitio]:
    salida: list[Sitio] = []
    for archivo, fuente in _fuentes().items():
        for n in ast.walk(ast.parse(fuente)):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "alertas"
                and n.func.attr in ("mensaje", "hallazgo")
            ):
                tipo = n.args[0].value if isinstance(n.args[0], ast.Constant) else "?"
                salida.append((archivo, n.lineno, str(tipo), _texto(n.args[-1])))
            # dentro de alertas.py: `mensaje("archivo_inaccesible", ...)` de `error()`
            if (
                archivo == "alertas.py"
                and isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "mensaje"
                and isinstance(n.args[0], ast.Constant)
            ):
                salida.append((archivo, n.lineno, str(n.args[0].value), _texto(n.args[-1])))
    return salida


SITIOS = sitios()


def test_se_encontraron_las_alertas() -> None:
    """Si esto falla, la búsqueda dejó de verlas y las otras pruebas no prueban nada."""
    assert len(SITIOS) >= 40
    assert len(alertas.CATALOGO) >= 30


def test_cada_alerta_usa_un_tipo_del_catalogo_y_ninguno_sobra() -> None:
    usados = {tipo for _, _, tipo, _ in SITIOS}
    desconocidos = sorted(f"{a}:{n} {t}" for a, n, t, _ in SITIOS if t not in alertas.CATALOGO)
    assert not desconocidos, f"tipos que no están en alertas.CATALOGO: {desconocidos}"
    assert not set(alertas.CATALOGO) - usados, "tipos del catálogo que nadie usa"


# ------------------------------------------------------ 2. nada de código

#: Lo que delata que un texto manda a tocar código, o a alguien que no estará.
PROHIBIDO = [
    (re.compile(r"\.py\b"), "nombra un archivo .py"),
    (re.compile(r"\bsrc[/\\]"), "nombra la carpeta del código"),
    (re.compile(r"\bClaude\b|\bla IA\b"), "supone que hay una IA disponible"),
    (re.compile(r"\b[a-z]+(?:_[a-z]+)+\("), "nombra una función del código"),
    (
        re.compile(
            # (?<!\[): [fechas.ejemplos] es una sección de config/, no un módulo
            r"(?<!\[)\b(alertas|bitacora|bronze|cli|deriva|editables|energia|excel|fechas|fuente|"
            r"mantencion|publicar|puntos|reglas|rutas|silver|toml_editable)\.(?!toml\b)[a-z_]+"
        ),
        "nombra un módulo del código",
    ),
    (re.compile(r"\bcódigo\b(?!\s+(?:de salida|\d))"), "manda al código"),
]


def _constantes() -> set[str]:
    """Las constantes de módulo del código (MAYÚSCULAS con _) y los nombres de antes."""
    nombres = {
        "COLUMNAS_CONOCIDAS", "COLUMNAS_FECHA", "ANIO_MIN", "ANIO_MAX", "URL_API", "PARAMS",
        "HEADERS", "REINTENTOS", "FORMATOS", "TEXTOS", "FECHAS", "HOJA",
    }  # fmt: skip
    for fuente in _fuentes().values():
        for n in ast.parse(fuente).body:
            if isinstance(n, ast.Assign | ast.AnnAssign):
                objetivos = n.targets if isinstance(n, ast.Assign) else [n.target]
                nombres |= {
                    t.id
                    for t in objetivos
                    if isinstance(t, ast.Name) and re.fullmatch(r"[A-Z]+_[A-Z_]+", t.id)
                }
    return nombres


CONSTANTES = re.compile(r"\b(" + "|".join(sorted(_constantes())) + r")\b")


def textos_que_lee_la_persona() -> list[tuple[str, str]]:
    """(dónde, texto): el catálogo, los detalles, los chequeos del diagnóstico, los errores de
    config/ y lo que dice la alerta general de cada código de salida."""
    salida = [(f"alertas.CATALOGO[{t}]", texto) for t, texto in alertas.CATALOGO.items()]
    salida += [(f"{a}:{n}", detalle) for a, n, _, detalle in SITIOS]
    salida += [(f"bitacora.QUE_HACER[{c}]", t) for c, t in bitacora.QUE_HACER.items()]
    for archivo, fuente in _fuentes().items():
        for n in ast.walk(ast.parse(fuente)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_c":
                salida.append((f"{archivo}:{n.lineno}", _texto(n)))
            if (
                isinstance(n, ast.Raise)
                and archivo in VALIDAN_CONFIG
                and isinstance(n.exc, ast.Call)
                and n.exc.args
            ):
                salida.append((f"{archivo}:{n.lineno}", _texto(n.exc.args[0])))
    return salida


TEXTOS = textos_que_lee_la_persona()


def test_se_encontraron_los_textos() -> None:
    assert len(TEXTOS) >= 120


@pytest.mark.parametrize(("donde", "texto"), TEXTOS, ids=[t[0] for t in TEXTOS])
def test_ningun_texto_manda_a_tocar_codigo(donde: str, texto: str) -> None:
    for patron, motivo in [*PROHIBIDO, (CONSTANTES, "nombra una constante del código")]:
        assert not patron.search(texto), f"{donde}: {motivo}: {texto!r}"


@pytest.mark.parametrize(
    "texto",
    [
        "editar COLUMNAS_CONOCIDAS en deriva.py",
        "ver silver.leer_excel",
        "llamar a probar_excel(ruta)",
        "pedirle a Claude que lo arregle",
        "es un cambio en el código",
        "corregir LECTURA_ORIGINAL",
    ],
)
def test_la_revision_atrapa_cada_tipo_de_texto_prohibido(texto: str) -> None:
    patrones = [p for p, _ in PROHIBIDO] + [CONSTANTES]
    assert any(p.search(texto) for p in patrones), texto


def test_se_permiten_los_textos_legitimos() -> None:
    """Archivos de config/, variables del .env, comandos, códigos de salida, columnas."""
    for texto in (
        "corregir 'nombre' en [hoja] de config/excel.toml",
        "CONT_PG_CLAVE del .env",
        "uv run contratos procesar --forzar",
        "sale con código 3",
        "la columna estado_distinto de Silver",
    ):
        patrones = [p for p, _ in PROHIBIDO] + [CONSTANTES]
        assert not any(p.search(texto) for p in patrones), texto


# ------------------------------------------------------ 3. lo nombrado existe


def _tomls() -> dict[str, dict[str, object]]:
    return {
        f"config/{p.name}": tomllib.loads(p.read_text(encoding="utf-8"))
        for p in CONFIG.glob("*.toml")
    }


def _seccion(datos: dict[str, object], ruta: str) -> object:
    actual: object = datos
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            return None
        actual = actual[parte]
    return actual


def comandos_de_la_cli() -> set[str]:
    """Los nombres tal como se escriben: `probar_excel` -> `probar-excel`."""
    nombres: set[str] = set()
    for c in cli.app.registered_commands:
        if c.name:
            nombres.add(c.name)
        elif c.callback is not None:
            nombres.add(c.callback.__name__.replace("_", "-"))
    return nombres


RE_ARCHIVO = re.compile(r"config/(\w+\.toml)")
RE_SECCION = re.compile(r"\[\[?([a-z_][a-z_.]*)\]\]?")
RE_CAMPO = re.compile(r"'(\w+)' (?:de|en) \[([a-z_.]+)\]")
RE_COMANDO = re.compile(r"(?:uv run contratos|`contratos) ([a-z][a-z-]+)")


@pytest.mark.parametrize(("donde", "texto"), TEXTOS, ids=[t[0] for t in TEXTOS])
def test_lo_que_nombra_un_texto_existe(donde: str, texto: str) -> None:
    tomls = _tomls()
    nombrados = [f"config/{n}" for n in RE_ARCHIVO.findall(texto)]
    for archivo in nombrados:
        assert archivo in tomls, f"{donde}: no existe {archivo}"
    donde_buscar = [tomls[a] for a in nombrados] or list(tomls.values())
    for seccion in RE_SECCION.findall(texto):
        assert any(isinstance(_seccion(t, seccion), dict) for t in donde_buscar), (
            f"{donde}: la sección [{seccion}] no existe en {nombrados or 'config/'}"
        )
    for campo, seccion in RE_CAMPO.findall(texto):
        assert any(
            isinstance(s := _seccion(t, seccion), dict) and campo in s for t in donde_buscar
        ), f"{donde}: '{campo}' no está en [{seccion}]"
    comandos = comandos_de_la_cli()
    for comando in RE_COMANDO.findall(texto):
        assert comando in comandos, f"{donde}: no existe el comando contratos {comando}"


def test_la_revision_de_nombres_ve_secciones_campos_y_comandos() -> None:
    texto = alertas.CATALOGO["excel_ilegible"] + alertas.CATALOGO["fecha_formato_desconocido"]
    assert "hoja" in RE_SECCION.findall(texto)
    assert ("nombre", "hoja") in RE_CAMPO.findall(texto)
    assert "probar-excel" in RE_COMANDO.findall(texto)


# ------------------------------------------------------ cómo se ve una alerta


def test_una_alerta_dice_que_hacer_y_su_tipo() -> None:
    texto = alertas.mensaje("silver_vacio", "Silver está vacío.")
    assert texto.splitlines() == [
        "Silver está vacío.",
        "  qué hacer: Correr uv run contratos procesar (o actualizar).",
        "  (alerta silver_vacio en la guía)",
    ]


def test_un_error_que_ya_es_alerta_no_se_envuelve_dos_veces() -> None:
    ya = ValueError(alertas.mensaje("bronze_vacio", "x"))
    assert alertas.error(ya) == str(ya)


def test_un_error_de_windows_dice_que_revisar() -> None:
    texto = alertas.error(PermissionError(13, "Permiso denegado", "contratos.parquet"))
    assert "(alerta archivo_inaccesible en la guía)" in texto


def test_un_error_inesperado_dice_que_es_trabajo_de_programador() -> None:
    texto = alertas.error(KeyError("x"))
    assert "KeyError" in texto and "trabajo de programador" in texto


# ------------------------------------------------------ 4. la guía


def test_cada_alerta_tiene_su_ficha_en_la_guia() -> None:
    """Quien recibe una alerta busca su tipo en la guía: tiene que estar."""
    guia = GUIA.read_text(encoding="utf-8")
    faltan = sorted(t for t in alertas.CATALOGO if f"`{t}`" not in guia)
    assert not faltan, f"alertas sin ficha en GUIA_MANTENIMIENTO.md: {faltan}"
