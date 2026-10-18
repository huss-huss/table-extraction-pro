# Table Extraction Pro

Extract tables from PDFs (and table structure from images) into CSV, JSON,
HTML or Excel. A learned detector (Microsoft's Table Transformer, TATR) and
two rule-based parsers (Camelot, Tabula) run behind one interface; when more
than one is installed, their candidates are compared per table and the best
copy is kept.

## The problem

Tables in PDFs are drawn, not stored. A PDF page holds positioned glyphs and
line segments; rows, columns and cells have to be reconstructed. Each
approach fails differently:

- Rule-based parsers are fast and exact when their assumptions hold. Camelot
  `lattice` and Tabula `lattice` need ruling lines and return nothing for an
  unruled table; `stream` modes infer columns from whitespace and often sweep
  captions or nearby prose into the table.
- A learned detector handles layouts without rules, but its geometry is
  approximate and it needs a text source to fill cells.

Running several backends and choosing per table covers more documents than
any single one, provided the choice is measurable. That is what the
evaluation and benchmark parts of this repository are for.

## Architecture

```
                         PDF / image
                              |
            +-----------------+-------------------+
            |                                     |
   TATR pipeline  [ml extra]              Fallback parsers  [fallback extra]
   PyMuPDF render (150 dpi)               (PDF only)
   -> detection model: table boxes        Camelot lattice + stream
   -> crop with 15 pt margin              Tabula lattice + stream (Java)
   -> structure model: rows, columns      each: cells -> strings, page bbox
   -> cell grid = rows x columns                 in PDF points
   -> cells filled from the PDF text layer
            |                                     |
            +----------------+--------------------+
                             |
                    ParserComparator
          group candidates: same page and (bbox IoU >= 0.5
                            or cell-text overlap >= 0.6)
          score: confidence, completeness, row consistency,
                 size, parser tie-break -> keep best per group
                             |
                    TableExporter: CSV / JSON / HTML / Excel
                             |
              CLI (click)            REST API (FastAPI)
```

Package layout:

| Module | Role |
|---|---|
| `table_extraction/models/` | TATR detection and structure wrappers (transformers) |
| `table_extraction/extraction/` | page rendering, text layer, TATR pipeline |
| `table_extraction/parsers/` | Camelot / Tabula wrappers and `ParserComparator` |
| `table_extraction/engine.py` | `auto` / `tatr` / `fallback` engine selection shared by CLI and API |
| `table_extraction/evaluation/` | GriTS-Con, GriTS-Top, strict cell accuracy |
| `table_extraction/export/` | CSV, JSON, HTML, Excel writers |
| `table_extraction/cli/`, `api/` | entry points |

## How detection, fallback and comparison work

**TATR.** Each PDF page is rendered with PyMuPDF. The detection model returns
table boxes; each box is cropped with a 15 pt margin (a tight crop makes the
structure model drop the outer rows and columns) and passed to the structure
model, which returns row, column and header boxes. Rows intersected with
columns give the cell grid. For PDFs, every text-layer word is assigned to
the cell containing its center, after mapping crop pixels back to PDF points.
Image input gets structure only: OCR is not implemented, so cells are empty
and marked `text_source: "none"`.

**Fallbacks.** Camelot runs with both flavors and Tabula with both modes.
Tabula is called page by page because its output does not say which page a
table came from. All cells are normalized to strings, empty rows and columns
are dropped, and every table records its bounding box in PDF points
(top-left origin) so tables from different parsers can be matched.

**Comparison.** `ParserComparator` groups candidates that describe the same
table (same page, and either bbox IoU >= 0.5 or at least 60% shared cell
text), then scores each one:

```
0.20 * parser confidence
0.35 * completeness   share of non-empty cells
0.35 * consistency    share of rows filling at least half of the columns
0.05 * size
0.05 * parser preference (TATR > Camelot > Tabula), mostly a tie-breaker
```

The consistency term is what rejects a `stream` result that absorbed a title
line above the table. The winning table records the candidate parsers and its
score in `metadata`. The weights are hand-set and were checked only against
the fixtures in this repository. They are not tuned on a real corpus.

**Engines.** `tatr` runs TATR only, `fallback` runs the comparator over
Camelot and Tabula, and `auto` (the default) runs everything installed and
compares all candidates together. If a needed extra is missing, you get an
error naming the `pip install` command.

## Install

Python 3.10 or newer.

```bash
pip install -e .                    # base: CLI, API, exporters, evaluation (no torch, no Java)
pip install -e ".[fallback]"        # + Camelot and Tabula (Tabula needs a Java runtime)
pip install -e ".[ml]"              # + torch, transformers, timm for TATR
pip install -e ".[ml,fallback,dev]" # everything, plus test tooling
```

The TATR weights (`microsoft/table-transformer-detection` and
`-structure-recognition`, about 230 MB together) are downloaded from the
Hugging Face Hub on first use and cached under `HF_HOME`.

Check what is available:

```bash
table-extract backends
```

## CLI

```bash
# Default engine (auto), CSV + JSON into out/
table-extract extract -i report.pdf -o out/

# Rule-based parsers only, with metadata, HTML and Excel too
table-extract extract -i report.pdf -o out/ -e fallback -f csv -f html -f excel --include-metadata

# One output file
table-extract quick -i report.pdf -o out/report.xlsx -f excel

# Every PDF/image in a folder, plus out/extraction_summary.json
table-extract batch -i docs/ -o out/ -e auto
```

When a document has several tables, CSV output goes to a directory named
after the input (`out/report/table_1_page_1.csv`, ...). JSON, HTML and Excel
hold all tables in one file.

## API

```bash
table-extract serve --port 8000            # or: docker compose up --build
```

```bash
curl -s localhost:8000/healthz
# {"status":"ok","version":"0.2.0","backends":{"tatr":false,"camelot":true,"tabula":true}}

curl -s -F "file=@report.pdf;type=application/pdf" -F engine=fallback \
     -F include_metadata=false localhost:8000/extract
# {"filename":"report.pdf","engine":"fallback","total_tables":1,"format":"json",
#  "tables":[{"table_id":1,"page_number":1,"data":[["Item","Qty",...],...]}]}
```

| Endpoint | Description |
|---|---|
| `GET /healthz` | liveness, version, installed backends |
| `POST /extract` | multipart `file`; form fields `engine`, `confidence`, `output_format` (`json`, `csv`, `html`), `include_metadata` |
| `POST /extract/batch` | multipart `files` (up to `TEP_MAX_BATCH_FILES`); per-file results or errors |

Request handling:

- The request body limit (`TEP_MAX_UPLOAD_MB`, default 20) is enforced
  before multipart parsing, from `Content-Length` and by counting chunked
  bodies. Oversized requests get a 413.
- The file extension, declared content type and magic bytes must agree
  (PDF, PNG, JPEG, TIFF, BMP). A mismatch gets a 415 and an empty file a 400.
- Each request writes to its own temporary directory, which is removed on
  success and on failure.
- All errors use the same shape:
  `{"error": {"code": "...", "message": "...", "details": ...}}`. A missing
  backend returns 503 `backend_unavailable` with the extra to install.
- CORS is off unless `TEP_CORS_ORIGINS` is set. `TEP_DEFAULT_ENGINE` selects
  the engine used when a request does not specify one.

## Docker

```bash
docker build -t table-extraction-pro .                                  # fallback extra (default)
docker build --build-arg EXTRAS=ml,fallback -t table-extraction-pro:ml .  # adds CPU-only torch + TATR
docker build --build-arg EXTRAS= -t table-extraction-pro:base .           # base install only
TEP_EXTRAS=ml,fallback TEP_EXTRAS_TAG=ml docker compose up --build
```

The build is multi-stage: a builder venv is copied onto `python:3.12-slim`,
the app runs as a non-root user, and a Java runtime is installed only with
the fallback extra. The compose file runs with a read-only root filesystem,
a tmpfs `/tmp`, and a volume for the model cache. Local image sizes
(linux/arm64) were 400 MB for base, 744 MB for fallback and 1.68 GB for
ml,fallback.

## Evaluation and benchmark

`table_extraction.evaluation` implements GriTS (Smock et al., 2022) using the
factored 2D most-similar-substructure method: rows and columns are aligned by
dynamic programming, and cells are rewarded by normalized LCS on their text
(GriTS-Con). GriTS-Top is included for grids without spanning cells.
GriTS-Loc is not implemented. `cell_accuracy` is a stricter, position-wise
exact match with no alignment, so one inserted caption row zeroes it.

`benchmarks/run_benchmark.py` renders the fixture PDFs from
`tests/fixtures/generate.py`: a ruled invoice, an unruled quarterly table,
two ruled tables on one page, and a two-page document. That is 6 tables over
5 pages. The script runs every installed backend, matches each ground-truth
table to the best prediction on its page, and writes a markdown report.

One local run (macOS arm64, CPU only, Python 3.12.11, camelot-py 2.0.0,
tabula-py 2.10.0 with OpenJDK 24, torch 2.14.1, transformers 5.20.1; all
backends were available):

| Backend | Tables found | Extra | GriTS-Con | Cell acc. | Exact | s/page |
|---|---|---|---|---|---|---|
| camelot (lattice) | 5/6 | 0 | 0.833 | 0.833 | 5/6 | 0.269 |
| camelot (stream) | 6/6 | 0 | 0.911 | 0.174 | 1/6 | 0.007 |
| tabula (lattice) | 5/6 | 0 | 0.833 | 0.833 | 5/6 | 0.257 |
| tabula (stream) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 0.742 |
| fallback (comparator) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 1.165 |
| tatr | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 0.276 |
| auto (tatr + fallback) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 1.487 |

Full output, including per-fixture numbers: [benchmarks/results.md](benchmarks/results.md).

How to read these numbers:

- The fixtures are synthetic and clean: born-digital PDFs with a perfect text
  layer, no merged cells and no scans. They show that the pipeline and the
  selection logic work, and how the backends fail (lattice modes miss the
  unruled table; Camelot stream keeps the caption lines). They say nothing
  about accuracy on real documents.
- Times are wall clock on one laptop, as the median of 3 runs after an untimed
  warm-up. Tabula runs through a JVM subprocess per page, which dominates its
  time; installing `jpype1` would avoid that. The comparator and `auto` rows
  include every backend they run.
- Before the TATR crop-margin fix in this repository, the same TATR run
  scored between 0.48 and 0.91 GriTS-Con per table.

Reproduce:

```bash
python benchmarks/run_benchmark.py --repeat 3 --out benchmarks/results.md   # --no-tatr to skip TATR
```

## Development

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[fallback,dev]"
.venv/bin/pytest -q              # fast suite; Camelot/Tabula tests skip if not installed
.venv/bin/pytest -q -m ml        # real TATR models (needs [ml], downloads weights)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests generate their fixture PDFs with reportlab at session start and
compare against the golden CSVs in `tests/fixtures/golden/`. The TATR
pipeline is tested without torch through `tests/tatr_fakes.py`, which reads
the ruling lines of the fixture PDFs and answers detection and structure
queries in the same format as the model wrappers. CI
(`.github/workflows/ci.yml`) runs ruff, then the fast suite on Python 3.12
with the fallback parsers (pinned via `requirements/ci-constraints.txt`) and
on Python 3.10 with the base install.

## Limitations

- No OCR. Scanned PDFs and images get table structure but empty cells.
- Spanning (merged) cells are not reconstructed. TATR spanning-cell
  predictions are returned in `structure` but not applied to the grid.
- The fallback parsers read PDFs only.
- The comparator weights and thresholds are heuristics, validated only on the
  fixture set.
- Benchmark coverage is 6 synthetic tables. There is no evaluation on a
  public dataset such as PubTables-1M or FinTabNet yet.
- The API runs extraction synchronously in a worker thread per request, with
  no job queue. Large documents hold a worker for the whole extraction.
- TATR runs on CPU unless CUDA is available. GPU paths are untested.

## Roadmap

- OCR backend (Tesseract or PaddleOCR) for images and scanned pages.
- Apply TATR spanning-cell predictions and evaluate them with full GriTS-Top
  and GriTS-Loc.
- Benchmark on a public dataset subset, then tune the comparator weights on
  it instead of setting them by hand.
- Async job API (submit, poll, download) for large documents.
- Optional `jpype1` integration to keep Tabula's JVM in-process.

## License

MIT, see [LICENSE](LICENSE).
