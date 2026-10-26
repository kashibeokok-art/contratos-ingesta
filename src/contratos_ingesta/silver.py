"""Silver: el Excel de Bronze -> dos tablas conformadas, con las reglas de CLAUDE.md §1.4.

| tabla                    | una fila =                      | para qué                       |
|--------------------------|---------------------------------|--------------------------------|
| `contratos.parquet`      | un contrato (TODOS, ADR-C03)    | quién, con quién, hasta cuándo |
| `contrato_barra.parquet` | un punto de retiro o suministro | dónde                          |

Van separadas para no repetir la energía de un contrato en cada una de sus barras.

`fecha_ingreso` = el primer día en que el contrato apareció en la base (pedido del usuario).
Se guarda en `_control.json` y se conserva entre corridas: aunque el contrato cambie, su
fecha de ingreso no cambia. En la PRIMERA carga todos reciben la fecha de esa carga.

Datos personales: `Correo Cliente` y `Dirección Comercial` NO se leen.

Reproceso: `_control.json` anota también la HUELLA del Silver (el sha256 del Excel y, si no
es la entregada, la de cómo se lee: config/excel.toml y [puntos] de config/reglas.toml) y el
día de la vigencia. Con la misma huella y el mismo día, `procesar` no rehace nada; si cambia
el Excel, la lectura o el día, se rehace. Lo que solo cambia avisos no entra en la huella.
"""

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

from contratos_ingesta import alertas, excel, reglas
from contratos_ingesta.dominio import energia, fechas, puntos

CONTROL = "_control.json"

# La hoja, la fila del encabezado y de qué columna del Excel sale cada columna de Silver
# están en config/excel.toml. `silver.HOJA`, `TEXTOS`, `FECHAS` y `PUNTOS` se siguen pudiendo
# usar: los resuelve `__getattr__`, al final del módulo.


class FormatoDesconocido(ValueError):
    """El Excel no tiene la forma conocida (falta una columna esperada)."""


class Conteo(TypedDict):
    contratos: int
    vigentes: int
    no_vigentes: int
    estado_distinto: int  # la vigencia calculada no coincide con 'Estado Contrato'
    sin_energia: int  # quedan en 0 (RN-09)
    anios_aislados: int  # años excluidos (RN-07)
    puntos: int
    puntos_no_reconocidos: int
    ids_repetidos: int
    sin_id: int


def leer_excel(ruta: Path) -> pd.DataFrame:
    """La hoja de contratos, con el encabezado real (`fila_encabezado` de config/excel.toml)."""
    forma = excel.vigente()
    try:
        tabla = pd.read_excel(
            ruta, sheet_name=forma["hoja"], header=forma["fila_encabezado"] - 1, dtype=str
        )
    except OSError:
        raise  # la red o un archivo abierto: lo explica quien lo atrapa
    except Exception as e:  # noqa: BLE001 - openpyxl y pandas lanzan de muchos tipos
        raise FormatoDesconocido(
            alertas.mensaje(
                "excel_ilegible",
                f"{ruta.name} no se pudo leer como Excel de contratos con la hoja "
                f"'{forma['hoja']}' ({type(e).__name__}: {e})",
            )
        ) from e
    tabla.columns = [str(c).strip() for c in tabla.columns]
    return tabla


def _columna(tabla: pd.DataFrame, nombre: str) -> str:
    """El nombre real de una columna, comparando sin tildes ni mayúsculas."""
    buscado = excel.sin_tildes(nombre)
    for c in tabla.columns:
        if excel.sin_tildes(str(c)) == buscado:
            return str(c)
    raise FormatoDesconocido(
        alertas.mensaje("excel_falta_columna", f"falta la columna {nombre!r} en el Excel")
    )


def _por_anio(tabla: pd.DataFrame, magnitud: str) -> dict[int, str]:
    """{2026: 'Energía 2026', ...} para 'energia' o 'potencia' (sin tildes ni mayúsculas)."""
    forma = excel.vigente()
    patron = forma["por_anio_tolerante"][magnitud]
    salida: dict[int, str] = {}
    for c in tabla.columns:
        if m := patron.match(excel.sin_tildes(str(c))):
            salida[int(m.group(1))] = str(c)
    if not salida:
        plantilla = forma["plantillas_por_anio"][magnitud]
        raise FormatoDesconocido(
            alertas.mensaje("excel_sin_columnas_anio", f"el Excel no trae columnas {plantilla!r}")
        )
    return salida


def _texto(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return None
    t = str(valor).strip()
    return t or None


def transformar(
    tabla: pd.DataFrame, fecha_datos: date, hoy: date
) -> tuple[pd.DataFrame, pd.DataFrame, Conteo]:
    """Excel -> (contratos, contrato_barra, conteo). Sin archivos: se prueba con datos a mano.

    - `fecha_datos`: la del Excel de Bronze (procedencia: de qué versión salió cada fila).
    - `hoy`: el día contra el que se calcula la vigencia (mejora 8.1). Antes era `fecha_datos`,
      y si el CEN no cambiaba el Excel por días, un contrato vencido seguía "vigente".
    """
    forma = excel.vigente()
    c_texto = {_columna(tabla, k): v for k, v in forma["texto"].items()}
    c_fecha = {_columna(tabla, k): v for k, v in forma["fecha"].items()}
    c_punto = {_columna(tabla, k): v for k, v in forma["puntos"].items()}
    c_energia = _por_anio(tabla, "energia")
    c_potencia = _por_anio(tabla, "potencia")

    conteo: Conteo = {
        "contratos": 0, "vigentes": 0, "no_vigentes": 0, "estado_distinto": 0,
        "sin_energia": 0, "anios_aislados": 0, "puntos": 0, "puntos_no_reconocidos": 0,
        "ids_repetidos": 0, "sin_id": 0,
    }  # fmt: skip
    contratos: list[dict[str, object]] = []
    filas_puntos: list[dict[str, object]] = []
    for fila in tabla.to_dict(orient="records"):
        r: dict[str, object] = {
            destino: _texto(fila[origen]) for origen, destino in c_texto.items()
        }
        if r["id_contrato"] is None:
            conteo["sin_id"] += 1
            continue
        r["id_contrato"] = str(r["id_contrato"]).removesuffix(".0")
        for origen, destino in c_fecha.items():
            r[destino] = fechas.leer_fecha(fila[origen])
        termino = fechas.termino_efectivo(
            r["fecha_termino"],  # type: ignore[arg-type]
            r["fecha_termino_renovacion"],  # type: ignore[arg-type]
        )
        r["fecha_termino_efectiva"] = termino
        r["vigente"] = fechas.vigente(termino, hoy)
        r["dias_para_vencer"] = fechas.dias_para_vencer(termino, hoy)
        conteo["vigentes" if r["vigente"] else "no_vigentes"] += 1
        # Manda la fecha (decisión del usuario, 2026-10-15); `estado_distinto` marca los
        # contratos donde 'Estado Contrato' de la fuente dice otra cosa, para revisarlos.
        estado_vigente = excel.sin_tildes(str(r["estado_fuente"] or "")) == "vigente"
        distinto = estado_vigente != r["vigente"]
        r["estado_distinto"] = distinto
        conteo["estado_distinto"] += int(distinto)

        resumen = energia.resumir({a: energia.numero(fila[c]) for a, c in c_energia.items()})
        r["energia_max_anual_gwh"] = resumen["maximo_gwh"]
        r["energia_promedio_anual_gwh"] = resumen["promedio_gwh"]
        r["energia_min_anual_gwh"] = resumen["minimo_gwh"]
        r["anios_energia"] = ",".join(map(str, resumen["anios_usados"]))
        r["anios_aislados"] = ",".join(map(str, resumen["anios_aislados"]))
        conteo["sin_energia"] += int(not resumen["anios_usados"])
        conteo["anios_aislados"] += len(resumen["anios_aislados"])
        potencias = [p for p in (energia.numero(fila[c]) for c in c_potencia.values()) if p]
        r["potencia_max_anual_mw"] = max(potencias) if potencias else 0.0
        r["fecha_datos"] = fecha_datos
        r["fecha_calculo"] = hoy
        contratos.append(r)

        for origen, tipo_punto in c_punto.items():
            for orden, p in enumerate(puntos.separar_lista(fila[origen]), start=1):
                filas_puntos.append({"id_contrato": r["id_contrato"], "tipo_punto": tipo_punto,
                                     "orden": orden, **p})  # fmt: skip
                conteo["puntos_no_reconocidos"] += int(not p["reconocido"])

    tabla_contratos = pd.DataFrame(contratos)
    tabla_puntos = pd.DataFrame(
        filas_puntos,
        columns=["id_contrato", "tipo_punto", "orden", "texto", "subestacion", "propietario",
                 "tension_kv", "seccion", "reconocido"],
    )  # fmt: skip
    if len(tabla_contratos):  # entero con vacíos (contratos sin término), no float
        tabla_contratos["dias_para_vencer"] = tabla_contratos["dias_para_vencer"].astype("Int64")
    conteo["contratos"] = len(tabla_contratos)
    conteo["puntos"] = len(tabla_puntos)
    if len(tabla_contratos):
        conteo["ids_repetidos"] = int(tabla_contratos["id_contrato"].duplicated().sum())
    return tabla_contratos, tabla_puntos, conteo


def revision(conteo: Conteo) -> list[alertas.Hallazgo]:
    """Lo que hay que mirar de un Silver recién armado. IDs repetidos o filas sin ID = aviso
    (código 3); lo demás es informativo."""
    salida: list[alertas.Hallazgo] = []
    if conteo["estado_distinto"]:
        salida.append(
            alertas.hallazgo(
                "estado_distinto",
                "info",
                f"{conteo['estado_distinto']:,} contratos con 'Estado Contrato' distinto de la "
                "vigencia por fecha",
            )
        )
    if conteo["puntos_no_reconocidos"]:
        salida.append(
            alertas.hallazgo(
                "puntos_no_reconocidos",
                "info",
                f"{conteo['puntos_no_reconocidos']:,} puntos con una forma desconocida",
            )
        )
    if conteo["ids_repetidos"]:
        salida.append(
            alertas.hallazgo(
                "ids_repetidos", "aviso", f"{conteo['ids_repetidos']:,} IDs de contrato repetidos"
            )
        )
    if conteo["sin_id"]:
        salida.append(
            alertas.hallazgo(
                "sin_id", "aviso", f"{conteo['sin_id']:,} filas sin ID de contrato (no entraron)"
            )
        )
    return salida


def marcar_fecha_ingreso(
    contratos: pd.DataFrame, conocidas: dict[str, str], dia: date
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Agrega `fecha_ingreso`: la más antigua conocida, o `dia` si el contrato es nuevo.

    Si se procesa un Excel más viejo que lo ya cargado, se queda la fecha MÁS ANTIGUA.
    """
    nuevas = dict(conocidas)
    for id_contrato in contratos["id_contrato"] if len(contratos) else []:
        previa = nuevas.get(str(id_contrato))
        if previa is None or dia.isoformat() < previa:
            nuevas[str(id_contrato)] = dia.isoformat()
    if len(contratos):
        contratos = contratos.assign(
            fecha_ingreso=contratos["id_contrato"].map(lambda i: date.fromisoformat(nuevas[i]))
        )
    return contratos, nuevas


def leer_control(silver: Path) -> dict[str, str] | None:
    """{id_contrato: fecha_ingreso ISO} de las corridas anteriores.

    None = el control no existe o no se puede leer (borrado, dañado): hay que reconstruirlo
    desde Bronze (`reconstruir_fecha_ingreso`), no partir de cero en silencio (mejora 8.2).
    """
    ruta = silver / CONTROL
    if not ruta.is_file():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))["fecha_ingreso"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(datos, dict):
        return None
    return {str(k): str(v) for k, v in datos.items()}


def ids_del_excel(ruta: Path) -> set[str]:
    """Solo la columna `Id Contrato` de un Excel de Bronze (rápido: no lee las 180 columnas)."""
    forma = excel.vigente()
    columna = next(k for k, v in forma["texto"].items() if v == "id_contrato")
    tabla = pd.read_excel(
        ruta,
        sheet_name=forma["hoja"],
        header=forma["fila_encabezado"] - 1,
        dtype=str,
        usecols=lambda c: excel.sin_tildes(str(c)) == excel.sin_tildes(columna),
    )
    if tabla.shape[1] != 1:
        raise FormatoDesconocido(
            alertas.mensaje("excel_falta_columna", f"{ruta.name}: no tiene la columna {columna!r}")
        )
    return {str(v).strip().removesuffix(".0") for v in tabla.iloc[:, 0].dropna() if str(v).strip()}


def reconstruir_fecha_ingreso(excels: list[tuple[date, Path]]) -> dict[str, str]:
    """Mejora 8.2: la fecha de ingreso de cada contrato = el Excel MÁS ANTIGUO de Bronze en que
    aparece. Se usa cuando el control se perdió; con un solo Excel, todos quedan con su fecha."""
    fechas: dict[str, str] = {}
    for dia, ruta in sorted(excels):
        for id_contrato in ids_del_excel(ruta):
            fechas.setdefault(id_contrato, dia.isoformat())
    return fechas


# ------------------------------------------------------------- huella (reproceso)

#: La huella de lectura tal como se entregó (config/excel.toml y [puntos] de config/reglas.toml
#: del 2026-10-26, que leen igual que el código de antes). Mientras se lea así, no se agrega a
#: la huella del Silver: con los archivos tal como se entregan, nada se rehace por ellos.
LECTURA_ORIGINAL = "4329375aa6e1bbda-8e9d0bd6c20a3899"


def huella_lectura() -> str:
    """Lo que cambia el contenido de Silver y vive en los archivos editables."""
    return excel.vigente()["huella_silver"] + "-" + reglas.vigente()["huella_silver"]


def huella(sha256_excel: str) -> list[str]:
    """Lo que identifica el contenido de Silver, sin contar el día: el Excel y cómo se lee."""
    lectura = huella_lectura()
    extra = [] if lectura == LECTURA_ORIGINAL else [f"lectura:{lectura}"]
    return [f"excel:{sha256_excel}", *extra]


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class Proceso(TypedDict):
    huella: list[str]
    calculado: str  # el día contra el que se calculó la vigencia (ISO)
    lineas: list[str]  # lo que informó: el resumen y lo que hay que revisar
    revisar: bool  # True = terminó con algo que revisar (código 3)


def ultimo_proceso(silver: Path) -> Proceso | None:
    """Lo que anotó el último `procesar`. None si no hay control o es de antes de la huella."""
    ruta = silver / CONTROL
    if not ruta.is_file():
        return None
    try:
        p = json.loads(ruta.read_text(encoding="utf-8"))["proceso"]
        return {
            "huella": [str(h) for h in p["huella"]],
            "calculado": str(p["calculado"]),
            "lineas": [str(linea) for linea in p["lineas"]],
            "revisar": bool(p["revisar"]),
        }
    except (ValueError, KeyError, TypeError):
        return None


def al_dia(previo: Proceso | None, firma: list[str], hoy: date) -> bool:
    """Silver ya se hizo con este Excel, esta lectura y la vigencia de hoy: no hay que rehacerlo."""
    return (
        previo is not None and previo["huella"] == firma and previo["calculado"] == hoy.isoformat()
    )


def escribir(
    silver: Path,
    contratos: pd.DataFrame,
    puntos_: pd.DataFrame,
    fecha_ingreso: dict[str, str],
    origen: str,
    conteo: Conteo,
    proceso: Proceso | None = None,
) -> None:
    """Escribe las dos tablas y el control como UN conjunto: o queda la versión nueva completa,
    o la anterior completa. Nunca una mezcla (mejora 8.10, mismo patrón que B9).

    1. todo a `.tmp`                    (si falla: se borran los .tmp, lo anterior intacto)
    2. lo anterior a `.old`
    3. cada `.tmp` a su nombre final     (si falla: se quitan los nuevos y vuelven los `.old`)
    4. recién ahora se borran los `.old`

    Antes una tabla podía quedar nueva y la otra vieja si el antivirus bloqueaba un renombre.
    """
    recuperar(silver)
    control: dict[str, object] = {
        "origen": origen,
        "conteo": conteo,
        "fecha_ingreso": fecha_ingreso,
    }
    if proceso is not None:
        control["proceso"] = proceso
    tmps = {nombre: silver / (nombre + ".tmp") for nombre in ARCHIVOS}
    try:
        contratos.to_parquet(tmps["contratos.parquet"], index=False, compression="zstd")
        puntos_.to_parquet(tmps["contrato_barra.parquet"], index=False, compression="zstd")
        tmps[CONTROL].write_text(json.dumps(control, ensure_ascii=False, indent=1), "utf-8")
    except BaseException:
        for tmp in tmps.values():
            tmp.unlink(missing_ok=True)
        raise

    apartados: list[str] = []
    puestos: list[str] = []
    try:
        for nombre in ARCHIVOS:
            if (silver / nombre).exists():
                (silver / nombre).replace(silver / (nombre + ".old"))
                apartados.append(nombre)
        for nombre in ARCHIVOS:
            tmps[nombre].replace(silver / nombre)
            puestos.append(nombre)
    except BaseException:
        for nombre in puestos:
            (silver / nombre).unlink(missing_ok=True)
        for nombre in apartados:
            (silver / (nombre + ".old")).replace(silver / nombre)
        for tmp in tmps.values():
            tmp.unlink(missing_ok=True)
        raise
    for nombre in apartados:
        (silver / (nombre + ".old")).unlink(missing_ok=True)


#: Los tres archivos de Silver, que se escriben siempre juntos.
ARCHIVOS = ("contratos.parquet", "contrato_barra.parquet", CONTROL)


def recuperar(silver: Path) -> None:
    """Arregla lo que dejó una corrida que murió a mitad de `escribir` (sin poder deshacer).

    - un `.old` cuyo archivo falta -> el proceso murió entre apartar y poner: vuelve a su lugar;
    - si quedó un conjunto mezclado (algún final faltante), se restauran TODOS los `.old`;
    - los `.tmp` sueltos se borran.
    """
    viejos = [n for n in ARCHIVOS if (silver / (n + ".old")).exists()]
    if viejos and any(not (silver / n).exists() for n in ARCHIVOS):
        for nombre in viejos:
            (silver / (nombre + ".old")).replace(silver / nombre)
    for nombre in ARCHIVOS:
        (silver / (nombre + ".old")).unlink(missing_ok=True)
        (silver / (nombre + ".tmp")).unlink(missing_ok=True)


def __getattr__(nombre: str) -> Any:
    """`silver.HOJA`, `TEXTOS`, `FECHAS`, `PUNTOS`: leídos de config/excel.toml al usarlos."""
    if nombre == "HOJA":
        return excel.vigente()["hoja"]
    if nombre in ("TEXTOS", "FECHAS", "PUNTOS"):
        clave = {"TEXTOS": "texto", "FECHAS": "fecha", "PUNTOS": "puntos"}[nombre]
        return dict(excel.vigente()[clave])  # type: ignore[literal-required]
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
