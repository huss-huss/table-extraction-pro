# Contributing

## Setup

```bash
git clone https://github.com/huss-huss/table-extraction-pro.git
cd table-extraction-pro
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[fallback,dev]"   # add ml for TATR
```

Tabula needs a Java runtime on `PATH`.

## Checks

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q          # fast suite, no model downloads
.venv/bin/pytest -q -m ml    # real TATR models (needs the ml extra)
```

CI runs the first three on every push and pull request.

## Guidelines

- Keep the base install light: import torch, transformers, camelot and tabula
  through `table_extraction._deps.require` inside the function that needs
  them, never at module import time.
- New behaviour comes with tests. Tests that need a real model use the `ml`
  marker; anything else must run offline.
- New extraction behaviour should be checked against the fixtures
  (`tests/fixtures/generate.py`) and, if it changes results, the benchmark
  (`benchmarks/run_benchmark.py`). Only report numbers you measured.
- Use conventional commit messages (`fix:`, `feat:`, `test:`, `docs:` ...).

## License

Contributions are licensed under the MIT License (see `LICENSE`).
