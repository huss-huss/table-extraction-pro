#!/usr/bin/env python3
"""
Extract tables from a PDF with whatever backends are installed and export them.

    python examples/simple_extraction.py report.pdf [output_dir]
"""

import sys
from pathlib import Path

from table_extraction import MissingDependencyError, available_backends
from table_extraction.engine import extract_tables
from table_extraction.export import TableExporter


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    print(f"Backends: {available_backends()}")
    try:
        tables = extract_tables(pdf, engine="auto")
    except MissingDependencyError as e:
        print(e)
        return 1
    if not tables:
        print("No tables found.")
        return 0
    for t in tables:
        meta = t["metadata"]
        print(
            f"table {t['table_id']} page {t['page_number']}: {len(t['data'])} rows via {meta.get('parser')}"
        )
    paths = TableExporter(out).export_tables(tables, pdf.stem, ["csv", "json", "html"])
    for fmt, path in paths.items():
        print(f"{fmt}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
