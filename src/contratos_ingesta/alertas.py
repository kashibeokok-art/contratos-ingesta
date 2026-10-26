"""Catálogo de las alertas del programa: qué hacer con cada una, sin abrir el código.

Quien recibe una alerta NO va a leer el código (decisión del usuario, 2026-10-26). Por eso
cada mensaje de error o de aviso pasa por aquí y lleva tres cosas:

- el detalle (qué pasó, con los datos de ese caso), que escribe quien lo detecta;
- qué hacer: qué archivo y sección editar, qué comando correr, o "es trabajo de
  programador" cuando de verdad lo es. Está en este catálogo, uno por tipo;
- el tipo, para buscar su ficha en GUIA_MANTENIMIENTO.md.

`tests/test_alertas.py` revisa el código por AST: ningún mensaje queda suelto (sin pasar por
aquí), ningún "qué hacer" manda a tocar Python, y lo que nombran (secciones de config/,
comandos) existe.
"""

from typing import Literal, TypedDict

Severidad = Literal["aviso", "info"]

#: tipo -> qué hacer. El orden es el de las fichas de la guía.
CATALOGO: dict[str, str] = {
    # --- configuración --------------------------------------------------------
    "env_invalido": (
        "Corregir el .env de este equipo (las variables válidas y su explicación están en "
        ".env.example) y volver a correr. Para revisar todo: uv run contratos diagnostico."
    ),
    "config_invalida": (
        "Corregir lo que dice el mensaje en ese archivo de config/ (o volver a la copia de "
        "config\\ hecha antes de editar) y revisar con: uv run contratos revisar-config."
    ),
    "carpeta_no_encontrada": (
        "Si la carpeta está en la red, revisar que el equipo esté conectado a ella. Si la ruta "
        "está mal escrita, corregirla en el .env. El programa no crea carpetas: si es nueva, "
        "crearla una vez a mano."
    ),
    "archivo_inaccesible": (
        "Revisar que la carpeta de red esté conectada y que nadie tenga el archivo abierto (por "
        "ejemplo, en Excel), y volver a correr. Nada quedó a medias."
    ),
    "archivo_no_existe": (
        "Revisar la ruta del archivo (se puede copiar desde el Explorador de Windows; si tiene "
        "espacios, va entre comillas)."
    ),
    # --- descarga ------------------------------------------------------------
    "api_sin_conexion": (
        "Revisar la conexión a internet del equipo y volver a correr más tarde. Si pasa varios "
        "días seguidos, correr uv run contratos diagnostico."
    ),
    "api_rechazo": (
        "Si la respuesta HTTP es 429 o empieza con 5, el servidor del Coordinador tiene problemas: "
        "volver a correr más tarde. Si es 403 o 404, cambió la dirección o los filtros: ver la "
        "receta de la guía y corregir [api] en config/fuente.toml."
    ),
    "api_respuesta_desconocida": (
        "El Coordinador cambió la forma de su respuesta: es trabajo de programador (no se "
        "arregla en config/). Mientras tanto, Silver sigue con el último Excel."
    ),
    "descarga_no_es_excel": (
        "Volver a correr más tarde (el enlace temporal puede haber vencido). Si se repite, es "
        "trabajo de programador."
    ),
    "bronze_vacio": (
        "Correr uv run contratos actualizar (o descargar). En un equipo nuevo es normal."
    ),
    "apartar_fallo": (
        "Revisar que nadie tenga ese Excel abierto y que haya permiso para escribir en Bronze, "
        "y volver a correr uv run contratos volver-a-bajar."
    ),
    # --- el Excel ------------------------------------------------------------
    "excel_ilegible": (
        "Revisar que sea el .xlsx del Coordinador (probar con uv run contratos probar-excel). "
        "Si la hoja de los contratos cambió de nombre, corregir 'nombre' en [hoja] de "
        "config/excel.toml."
    ),
    "excel_falta_columna": (
        "Si el Coordinador renombró la columna, poner el nombre nuevo en config/excel.toml: en "
        "'conocidas' de [columnas] y en la sección donde se lee ([columnas.texto], "
        "[columnas.fecha] o [columnas.puntos]). Probar con uv run contratos probar-excel."
    ),
    "excel_sin_columnas_anio": (
        "Mirar en el Excel cómo se llaman ahora las columnas de energía y potencia de cada año "
        "y corregir la plantilla en [columnas.por_anio] de config/excel.toml, con un ejemplo "
        "real. Probar con uv run contratos probar-excel."
    ),
    "excel_sin_contratos": (
        "Ninguna fila trae el ID del contrato: revisar el Excel. Si la columna del ID cambió de "
        "nombre, corregir 'id_contrato' en [columnas.texto] de config/excel.toml."
    ),
    "excel_nombre_sin_fecha": (
        "Usar el Excel tal como lo dejó la descarga en Bronze, o renombrar la copia como "
        "Contratos_publica_AAAAMMDD_HHMMSS.xlsx con la fecha de los datos."
    ),
    "columnas_nuevas": (
        "Si la columna no hace falta, agregarla a 'conocidas' de [columnas] en "
        "config/excel.toml para que deje de avisar. Si es el nombre nuevo de una columna que "
        "se lee, cambiarla también en [columnas.texto], [columnas.fecha] o [columnas.puntos]."
    ),
    "columnas_que_faltan": (
        "Si el Coordinador la quitó y no se lee, sacarla de 'conocidas' de [columnas] en "
        "config/excel.toml. Si se lee, el proceso se detiene con la alerta excel_falta_columna."
    ),
    "anios_nuevos": (
        "Nada urgente: el Excel trae años fuera del rango esperado y se leen igual. Para que "
        "deje de informarlo, ampliar anio_min o anio_max en [columnas.por_anio] de "
        "config/excel.toml."
    ),
    "fecha_formato_desconocido": (
        "Esas fechas quedaron vacías. Agregar la forma nueva a 'formas' de [fechas] en "
        "config/excel.toml, con un ejemplo real en [fechas.ejemplos] y la fecha que tiene que "
        "dar. Probar con uv run contratos probar-excel y después correr uv run contratos "
        "procesar."
    ),
    "energia_con_coma": (
        "Mirar esos valores en el Excel. Si la coma es decimal (1400,5), está bien. Si separa "
        "miles (1,400), el dato queda mal: es trabajo de programador."
    ),
    "energia_no_numerica": (
        "Esos valores quedaron vacíos. Mirarlos en el Excel; si se repite, es trabajo de "
        "programador."
    ),
    # --- Silver --------------------------------------------------------------
    "ids_repetidos": (
        "Revisar esos IDs en el Excel del Coordinador. Mientras haya IDs repetidos, "
        "publicar-sql no sube Silver a la base (la base queda como estaba)."
    ),
    "sin_id": (
        "Esas filas no entraron a Silver. Revisarlas en el Excel; si el Coordinador las sigue "
        "mandando, avisarle."
    ),
    "estado_distinto": (
        "Informativo. La vigencia se decide por la fecha de término (decisión del 2026-10-15); "
        "la columna estado_distinto de Silver marca esos contratos para revisarlos."
    ),
    "puntos_no_reconocidos": (
        "Informativo: se guardaron con el texto completo. Si es un texto nuevo que significa "
        "'sin punto' o un sufijo, agregarlo a [puntos] de config/reglas.toml; una forma nueva "
        "de escribir un punto es trabajo de programador."
    ),
    "control_reconstruido": (
        "Informativo: el control de fechas de ingreso de Silver no estaba y se rehízo desde "
        "los Excel de Bronze. No hay que hacer nada."
    ),
    "silver_vacio": "Correr uv run contratos procesar (o actualizar).",
    "silver_no_al_dia": "Correr uv run contratos procesar.",
    # --- PostgreSQL ----------------------------------------------------------
    "pg_sin_configurar": (
        "Escribir CONT_PG_CONEXION y CONT_PG_CLAVE en el .env (ver .env.example). Si este "
        "equipo no publica en la base, no hace falta: actualizar se salta ese paso solo."
    ),
    "pg_esquema_antiguo": (
        "Un administrador de la base debe correr sql/esquema_contratos.sql en la base cmg_cen "
        "(se puede repetir sin perder datos). No se cambió nada en la base."
    ),
    "pg_error": (
        "Revisar que el servidor esté encendido y la conexión y la clave del .env "
        "(CONT_PG_CONEXION, CONT_PG_CLAVE); uv run contratos diagnostico lo prueba. No se "
        "cambió nada en la base."
    ),
    "silver_invalido": (
        "No se cambió nada en la base. Rehacer Silver con uv run contratos procesar --forzar y "
        "volver a publicar; si se repite, revisar el Excel con uv run contratos probar-excel. "
        "Si sigue, es trabajo de programador."
    ),
    # --- lo inesperado -------------------------------------------------------
    "error_inesperado": (
        "Volver a correr. Si se repite, es trabajo de programador: entregarle este mensaje y "
        "el archivo de alerta de data\\alertas."
    ),
}


def mensaje(tipo: str, detalle: str) -> str:
    """El detalle, qué hacer y el tipo (para buscar su ficha en la guía)."""
    return f"{detalle}\n  qué hacer: {CATALOGO[tipo]}\n  (alerta {tipo} en la guía)"


class Hallazgo(TypedDict):
    tipo: str
    severidad: Severidad  # aviso = mirarlo (el comando termina con código 3) | info = no
    detalle: str
    que_hacer: str


def hallazgo(tipo: str, severidad: Severidad, detalle: str) -> Hallazgo:
    return {"tipo": tipo, "severidad": severidad, "detalle": detalle, "que_hacer": CATALOGO[tipo]}


def lineas(h: Hallazgo) -> list[str]:
    """Cómo se muestra un hallazgo en pantalla y en el log."""
    return [
        f"  {h['severidad']}: {h['detalle']}",
        f"    qué hacer: {h['que_hacer']}",
        f"    (alerta {h['tipo']} en la guía)",
    ]


def error(e: BaseException) -> str:
    """Un error atrapado, como mensaje: tal cual si ya es una alerta; si no, con qué hacer."""
    texto = str(e).strip()
    if "\n  qué hacer: " in texto:
        return texto
    if isinstance(e, OSError):
        return mensaje("archivo_inaccesible", texto)
    return mensaje("error_inesperado", f"{type(e).__name__}: {texto}")
