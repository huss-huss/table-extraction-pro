#!/usr/bin/env python3
"""
Benchmark the installed extraction backends on the generated fixture PDFs.

For every backend and fixture the script extracts all tables, matches each
ground-truth table to the predicted table on the same page with the highest
GriTS-Con, and reports:

- tables: matched ground-truth tables / expected, plus extra (unmatched) predictions
- GriTS-Con: mean F1 over ground-truth tables (0 for a missed table)
- cell acc.: mean strict position-wise cell accuracy (no alignment)
- exact: ground-truth tables reproduced cell for cell
- s/page: median wall time per page over --repeat runs (after one warm-up)

Backends that are not installed are listed as skipped. Usage:

    python benchmarks/run_benchmark.py [--repeat 3] [--out benchmarks/results.md] [--no-tatr]
"""

import argparse
import importlib.metadata
import logging
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_extraction._deps import available_backends  # noqa: E402
from table_extraction.evaluation import cell_accuracy, grits_con  # noqa: E402
from tests.fixtures.generate import FIXTURES, render_all  # noqa: E402


def backend_runners(include_tatr: bool, dpi: int):
    """name -> (callable(pdf_path) -> tables) for every installed backend."""
    avail = available_backends()
    java = shutil.which("java") is not None
    runners, skipped = {}, {}

    if avail["camelot"]:
        from table_extraction.parsers import CamelotParser

        runners["camelot (lattice)"] = lambda p: CamelotParser().extract_tables(p, flavor="lattice")
        runners["camelot (stream)"] = lambda p: CamelotParser().extract_tables(p, flavor="stream")
    else:
        skipped["camelot"] = "camelot-py not installed"

    if avail["tabula"] and java:
        from table_extraction.parsers import TabulaParser

        runners["tabula (lattice)"] = lambda p: TabulaParser().extract_tables(p, method={"lattice": True})
        runners["tabula (stream)"] = lambda p: TabulaParser().extract_tables(p, method={"stream": True})
    else:
        skipped["tabula"] = "tabula-py not installed" if not avail["tabula"] else "no java runtime"

    if avail["camelot"] or (avail["tabula"] and java):
        from table_extraction.parsers import ParserComparator

        runners["fallback (comparator)"] = lambda p: ParserComparator().compare_parsers(str(p))

    if include_tatr and avail["tatr"]:
        from table_extraction.engine import extract_tables
        from table_extraction.extraction.pipeline import TableExtractionPipeline

        pipeline = TableExtractionPipeline(dpi=dpi)  # models load once, on the warm-up run
        runners["tatr"] = lambda p: pipeline.extract_from_pdf(p)
        if "fallback (comparator)" in runners:
            runners["auto (tatr + fallback)"] = lambda p: extract_tables(p, "auto", pipeline=pipeline)
    elif not include_tatr:
        skipped["tatr"] = "disabled with --no-tatr"
    else:
        skipped["tatr"] = "torch/transformers not installed (ml extra)"
    return runners, skipped


def score(spec, tables):
    gts = list(spec.iter_tables())
    used = set()
    con, acc, exact = [], [], 0
    for page, _, rows in gts:
        best, best_i = None, None
        for i, t in enumerate(tables):
            if i in used or t["page_number"] != page:
                continue
            g = grits_con(rows, t["data"])["f1"]
            if best is None or g > best:
                best, best_i = g, i
        if best_i is None:
            con.append(0.0)
            acc.append(0.0)
            continue
        used.add(best_i)
        pred = tables[best_i]["data"]
        con.append(best)
        acc.append(cell_accuracy(rows, pred))
        exact += pred == rows
    return {
        "expected": len(gts),
        "matched": len(used),
        "extra": len(tables) - len(used),
        "con": con,
        "acc": acc,
        "exact": exact,
    }


def run(repeat: int, include_tatr: bool, dpi: int):
    logging.disable(logging.WARNING)
    runners, skipped = backend_runners(include_tatr, dpi)
    with tempfile.TemporaryDirectory() as tmp:
        pdfs = render_all(Path(tmp))
        pages = {spec.name: len(spec.pages) for spec in FIXTURES}
        rows = []
        per_fixture = []
        for name, fn in runners.items():
            agg = {"expected": 0, "matched": 0, "extra": 0, "con": [], "acc": [], "exact": 0}
            spp = []
            for spec in FIXTURES:
                pdf = pdfs[spec.name]
                tables = fn(pdf)  # warm-up (JVM start, model load) - not timed
                times = []
                for _ in range(repeat):
                    t0 = time.perf_counter()
                    tables = fn(pdf)
                    times.append(time.perf_counter() - t0)
                s = score(spec, tables)
                for k in ("expected", "matched", "extra", "exact"):
                    agg[k] += s[k]
                agg["con"] += s["con"]
                agg["acc"] += s["acc"]
                spp.append(statistics.median(times) / pages[spec.name])
                per_fixture.append((name, spec.name, s, statistics.median(times) / pages[spec.name]))
            rows.append((name, agg, statistics.median(spp)))
    return rows, per_fixture, skipped


def environment():
    def ver(pkg):
        try:
            return importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            return None

    java = None
    if shutil.which("java"):
        out = subprocess.run(["java", "-version"], capture_output=True, text=True).stderr.splitlines()
        java = out[0] if out else "unknown"
    pkgs = {p: ver(p) for p in ("camelot-py", "tabula-py", "torch", "transformers", "PyMuPDF")}
    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "java": java,
        **{k: v for k, v in pkgs.items() if v},
    }


def to_markdown(rows, per_fixture, skipped, env, repeat):
    out = []
    out.append("| Backend | Tables found | Extra | GriTS-Con | Cell acc. | Exact | s/page |")
    out.append("|---|---|---|---|---|---|---|")
    for name, a, spp in rows:
        out.append(
            f"| {name} | {a['matched']}/{a['expected']} | {a['extra']} | "
            f"{statistics.mean(a['con']):.3f} | {statistics.mean(a['acc']):.3f} | "
            f"{a['exact']}/{a['expected']} | {spp:.3f} |"
        )
    out.append("")
    out.append("Per fixture (GriTS-Con mean / exact tables / extra predictions / s per page):")
    out.append("")
    names = [spec.name for spec in FIXTURES]
    out.append("| Backend | " + " | ".join(names) + " |")
    out.append("|---|" + "---|" * len(names))
    by_backend = {}
    for backend, fixture, s, spp in per_fixture:
        cell = f"{statistics.mean(s['con']):.2f} / {s['exact']}/{s['expected']} / +{s['extra']} / {spp:.2f}s"
        by_backend.setdefault(backend, {})[fixture] = cell
    for backend, cells in by_backend.items():
        out.append(f"| {backend} | " + " | ".join(cells[n] for n in names) + " |")
    out.append("")
    out.append(f"Timing: median of {repeat} run(s) after one untimed warm-up, wall clock, single process.")
    out.append("Environment: " + ", ".join(f"{k} {v}" for k, v in env.items()))
    if skipped:
        out.append("Skipped: " + "; ".join(f"{k} ({v})" for k, v in skipped.items()))
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None, help="Also write the markdown table to this file")
    ap.add_argument("--no-tatr", action="store_true", help="Skip TATR even if installed")
    ap.add_argument("--dpi", type=int, default=150, help="Render DPI for TATR (default 150)")
    args = ap.parse_args()
    rows, per_fixture, skipped = run(args.repeat, not args.no_tatr, args.dpi)
    md = to_markdown(rows, per_fixture, skipped, environment(), args.repeat)
    print(md)
    if args.out:
        args.out.write_text(md)


if __name__ == "__main__":
    main()
