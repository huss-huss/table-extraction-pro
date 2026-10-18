"""Deterministic fixture PDFs with known tables.

Each fixture is described by a ``FixtureSpec``: a list of pages, each page a
list of tables, each table a list of rows (first row is the header). The PDF
is rendered with reportlab so the text layer is exact, and the same data is
stored as golden CSVs under ``tests/fixtures/golden``.

Run ``python tests/fixtures/generate.py`` to (re)write the golden CSVs and a
copy of the PDFs into ``tests/fixtures/pdfs`` (PDFs are git-ignored; tests and
benchmarks regenerate them on the fly).
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN_DIR = HERE / "golden"

Table = list[list[str]]


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    style: str  # "lattice" (ruled grid) or "stream" (whitespace aligned)
    pages: list[list[Table]] = field(default_factory=list)
    description: str = ""

    def golden_name(self, page: int, index: int) -> str:
        return f"{self.name}_p{page}_t{index}.csv"

    def iter_tables(self):
        """Yield ``(page_number, table_index, rows)``, both 1-based."""
        for p, tables in enumerate(self.pages, start=1):
            for t, rows in enumerate(tables, start=1):
                yield p, t, rows


INVOICE: Table = [
    ["Item", "Qty", "Unit Price", "Total"],
    ["Widget A", "4", "2.50", "10.00"],
    ["Widget B", "10", "1.25", "12.50"],
    ["Service fee", "1", "30.00", "30.00"],
    ["Shipping", "1", "7.95", "7.95"],
]

QUARTERLY: Table = [
    ["Region", "Q1", "Q2", "Q3", "Q4"],
    ["North", "1200", "1350", "1100", "1600"],
    ["South", "980", "1020", "1075", "990"],
    ["East", "1430", "1500", "1620", "1710"],
    ["West", "870", "910", "-45", "1005"],
    ["Total", "4480", "4780", "3750", "5305"],
]

STAFF: Table = [
    ["Name", "Team", "Start"],
    ["Alice", "Platform", "2021-03-01"],
    ["Bilal", "Data", "2022-07-15"],
    ["Chen", "Search", "2020-11-30"],
]

INVENTORY: Table = [
    ["SKU", "Description", "On hand", "Reorder"],
    ["A-100", "Bolt M6", "520", "200"],
    ["A-101", "Bolt M8", "75", "150"],
    ["B-200", "Washer 6mm", "1300", "500"],
]

METRICS: Table = [
    ["Metric", "Value"],
    ["Latency p50 (ms)", "41"],
    ["Latency p95 (ms)", "118"],
    ["Error rate (%)", "0.42"],
]

FIXTURES: list[FixtureSpec] = [
    FixtureSpec("lattice_invoice", "lattice", [[INVOICE]], "single ruled table"),
    FixtureSpec("stream_quarterly", "stream", [[QUARTERLY]], "single unruled table"),
    FixtureSpec(
        "two_tables_one_page",
        "lattice",
        [[STAFF, METRICS]],
        "two ruled tables stacked on one page",
    ),
    FixtureSpec("multipage", "lattice", [[INVENTORY], [QUARTERLY]], "one ruled table per page"),
]


def fixture_by_name(name: str) -> FixtureSpec:
    for spec in FIXTURES:
        if spec.name == name:
            return spec
    raise KeyError(name)


def _draw_lattice(c, rows: Table, top: float, left: float = 72) -> float:
    """Draw a fully ruled table; return the y coordinate below it."""
    from reportlab.lib import colors
    from reportlab.platypus import Table as RLTable
    from reportlab.platypus import TableStyle

    t = RLTable(rows)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    _, h = t.wrapOn(c, 450, 700)
    t.drawOn(c, left, top - h)
    return top - h


def _draw_stream(c, rows: Table, top: float, left: float = 72) -> float:
    """Draw a whitespace-aligned table with no rules; return y below it."""
    col_x = [left + i * 90 for i in range(len(rows[0]))]
    y = top
    for r, row in enumerate(rows):
        c.setFont("Helvetica-Bold" if r == 0 else "Helvetica", 10)
        for x, cell in zip(col_x, row):
            c.drawString(x, y, cell)
        y -= 16
    return y


def render_pdf(spec: FixtureSpec, path: Path) -> Path:
    """Render ``spec`` to ``path`` (US letter) and return the path."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter, invariant=1)
    c.setTitle(spec.name)
    draw = _draw_lattice if spec.style == "lattice" else _draw_stream
    for tables in spec.pages:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(72, 740, f"Report: {spec.name.replace('_', ' ')}")
        c.setFont("Helvetica", 10)
        c.drawString(72, 722, "The figures below are synthetic test data.")
        top = 690.0
        for rows in tables:
            bottom = draw(c, rows, top)
            top = bottom - 80
        c.showPage()
    c.save()
    return path


def read_golden(spec: FixtureSpec, page: int, index: int) -> Table:
    with open(GOLDEN_DIR / spec.golden_name(page, index), newline="", encoding="utf-8") as f:
        return [row for row in csv.reader(f)]


def write_golden() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for spec in FIXTURES:
        for page, index, rows in spec.iter_tables():
            out = GOLDEN_DIR / spec.golden_name(page, index)
            with open(out, "w", newline="", encoding="utf-8") as f:
                csv.writer(f, lineterminator="\n").writerows(rows)


def render_all(out_dir: Path) -> dict[str, Path]:
    return {spec.name: render_pdf(spec, out_dir / f"{spec.name}.pdf") for spec in FIXTURES}


if __name__ == "__main__":
    write_golden()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "pdfs"
    for name, p in render_all(out).items():
        print(f"{name}: {p}")
