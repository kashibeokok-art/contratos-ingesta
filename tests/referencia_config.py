"""Copia CONGELADA de lo que estaba en el código el 2026-10-26, antes de pasar a `config/`.

No se edita: es la referencia contra la que se prueba que los archivos editables leen
exactamente lo mismo que el código de antes (tests/test_config_*.py). Viene de:

- `bronze.py`: URL_API, PARAMS, HEADERS, REINTENTOS
- `deriva.py`: COLUMNAS_CONOCIDAS, ANIO_MIN/ANIO_MAX, COLUMNAS_FECHA, _POR_ANIO
- `silver.py`: HOJA, header=1, TEXTOS, FECHAS, PUNTOS y `_por_anio` (comparación sin tildes)
- `dominio/fechas.py`: FORMATOS
- `dominio/puntos.py`: el "NULO" y _SUFIJO_AIS_GIS
- `cli.py`: los 180 días de `estado`
"""

import re
import unicodedata
from datetime import date, datetime

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

COLUMNAS_CONOCIDAS = (
    "Id Contrato", "Empresa Suministradora", "Rut Suministradora", "Tipo Suministrador",
    "Tipo Contrato", "Red Distribuidora", "Tipo Cliente", "Empresa Cliente", "Rut Empresa Cliente",
    "Suscripción", "Inicio", "Término", "Fecha Renovación", "Fecha Inicio Renovación",
    "Fecha Término Renovación", "Estado Contrato", "Afecto Ley", "Régimen Compra Potencia",
    "Correo Cliente", "Región", "Dirección Comercial", "Sector Económico", "Subsector Económico",
    "Listado de puntos de Suministro", "Listado de puntos de Retiro",
    "Listado de Potencia Conectada [MW]", "Listado Dirección de Referencia", "Numero Cliente",
    "Distribuidora Conectada", "Listado Región",
)  # fmt: skip
ANIO_MIN, ANIO_MAX = 1986, 2060
COLUMNAS_FECHA = ("Suscripción", "Inicio", "Término", "Fecha Término Renovación")
POR_ANIO = re.compile(r"^(Energía|Potencia) (\d{4})$")

HOJA = "contratos"
HEADER = 1  # pd.read_excel(header=1): la 2.a fila
TEXTOS = {
    "Id Contrato": "id_contrato",
    "Empresa Suministradora": "suministrador",
    "Rut Suministradora": "rut_suministrador",
    "Tipo Suministrador": "tipo_suministrador",
    "Tipo Contrato": "tipo_contrato",
    "Red Distribuidora": "red_distribuidora",
    "Tipo Cliente": "tipo_cliente",
    "Empresa Cliente": "cliente",
    "Rut Empresa Cliente": "rut_cliente",
    "Estado Contrato": "estado_fuente",
    "Región": "region",
    "Sector Económico": "sector_economico",
    "Subsector Económico": "subsector_economico",
}
FECHAS = {
    "Suscripción": "fecha_suscripcion",
    "Inicio": "fecha_inicio",
    "Término": "fecha_termino",
    "Fecha Término Renovación": "fecha_termino_renovacion",
}
PUNTOS = {"Listado de puntos de Retiro": "retiro", "Listado de puntos de Suministro": "suministro"}

FORMATOS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")
SUFIJO_AIS_GIS = re.compile(r"\s*\((?:AIS|GIS)\)$", re.IGNORECASE)
DIAS_POR_VENCER = 180


def sin_tildes(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto)
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).lower().split())


def anio_silver(columna: str, magnitud: str) -> int | None:
    """Lo que hacía `silver._por_anio` con una columna: su año, o None si no es de esa magnitud."""
    partes = sin_tildes(columna).split()
    if len(partes) == 2 and partes[0] == magnitud and partes[1].isdigit():
        return int(partes[1])
    return None


def leer_fecha(valor: object) -> date | None:
    """`dominio/fechas.leer_fecha` tal como estaba (con las 4 formas)."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor is None:
        return None
    texto = str(valor).strip()
    for formato in FORMATOS:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def es_vacio(punto: str) -> bool:
    """`dominio/puntos.separar_punto`: un punto vacío o NULO no es un punto."""
    t = " ".join(punto.split())
    return not t or t.upper() == "NULO"
