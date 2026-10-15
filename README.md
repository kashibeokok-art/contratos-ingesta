# contratos-ingesta

Contratos de suministro del Coordinador Eléctrico Nacional (Plataforma Mercado):
descarga → Bronze → Silver → PostgreSQL.

```
API pública del CEN ─► Bronze: Contratos_publica_AAAAMMDD_HHMMSS.xlsx (solo si cambió)
                    ─► Silver: contratos.parquet + contrato_barra.parquet
                    ─► PostgreSQL: esquema contratos (reemplazo completo en una transacción)
```

## Uso

```powershell
uv sync
copy .env.example .env          # completar rutas y conexión (sin comillas)
uv run contratos actualizar     # descargar + procesar + publicar
uv run contratos estado
```

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
