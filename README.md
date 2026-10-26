# contratos-ingesta

Contratos de suministro del Coordinador Eléctrico Nacional (Plataforma Mercado):
descarga → Bronze → Silver → PostgreSQL.

```
API pública del CEN ─► Bronze: Contratos_publica_AAAAMMDD_HHMMSS.xlsx (solo si cambió)
                    ─► Silver: contratos.parquet + contrato_barra.parquet
                    ─► PostgreSQL: esquema contratos (reemplazo completo en una transacción)
```

## Para mantenerlo

**[GUIA_MANTENIMIENTO.md](GUIA_MANTENIMIENTO.md)**: instalar en un equipo nuevo, la rutina
diaria, qué hacer ante cada alerta y cómo corregir lo que cambia con el tiempo **sin tocar el
código**:

- `.env`: dónde están las carpetas y la base (uno por equipo; plantilla en `.env.example`).
- `config/fuente.toml`: de dónde se baja el Excel.
- `config/excel.toml`: cómo se lee el Excel (hoja, columnas, años, formas de fecha).
- `config/reglas.toml`: reglas que se ajustan (días por vencer, puntos vacíos, sufijos).

## Uso

```powershell
uv sync
Copy-Item .env.example .env       # completar (ver la guía, sección 3)
uv run contratos diagnostico      # revisa todo y dice qué hacer
uv run contratos actualizar       # descargar + procesar + publicar (tarea diaria)
uv run contratos estado
```

Más comandos: `revisar-config`, `probar-excel`, `volver-a-bajar` (guía, sección 9).

Códigos de salida: 0 bien · 1 no se pudo · 2 comando mal escrito · 3 hay algo que revisar.

## Reglas principales

- Vigencia: el mayor entre Término y Término de renovación; `estado_distinto` marca cuando el
  "Estado Contrato" de la fuente dice otra cosa.
- Energía: máximo anual en GWh, sin años aislados, sin dato = 0.
- `fecha_ingreso`: el primer día en que el contrato entró a la base.
- Puntos de retiro y suministro en formato largo (`contrato_barra`).
- Correo y dirección del cliente no se guardan.

Detalle y decisiones: [`CLAUDE.md`](CLAUDE.md). Guías del código: [`docs/aprendizaje/`](docs/aprendizaje/).

## Desarrollo

```powershell
uv run ruff check . ; uv run ruff format --check . ; uv run mypy ; uv run pytest
```

Las pruebas no tocan la red ni las carpetas reales. `tests/test_alertas.py` y
`tests/test_guia.py` vigilan que cada mensaje diga qué hacer y que la guía calce con el código.
