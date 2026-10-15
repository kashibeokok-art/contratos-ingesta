# 01 — Andamiaje

**Problema:** antes de procesar contratos hace falta un proyecto que cualquiera pueda instalar
igual y que revise el código solo.

| Pieza | Qué hace | Comando |
|---|---|---|
| `uv` + `pyproject.toml` + `uv.lock` | fija las librerías y sus versiones exactas | `uv sync` |
| `ruff` | revisa errores y estilo, y formatea | `uv run ruff check .` · `uv run ruff format .` |
| `mypy` (strict) | revisa tipos sin ejecutar | `uv run mypy` |
| `pytest` | corre los tests | `uv run pytest` |
| `.gitignore` | deja fuera `.env` y los datos (Excel, Parquet), salvo `tests/fixtures/` | — |
| `.gitattributes` | saltos de línea LF; Excel y Parquet como binarios | — |

**Por qué ya hay un test** aunque no hay lógica: `mypy` falla si `tests/` no tiene un `.py` (A1) y
`pytest` sin tests sale con código 5, no 0 (A2).

**Por qué no hay `[project.scripts]` todavía:** `uv init` lo crea apuntando a una función `main`
de ejemplo. Se agrega en el paso 6, cuando exista la línea de comandos de verdad.

**Frase:** el proyecto se instala igual en cualquier equipo y se revisa solo antes de seguir.
