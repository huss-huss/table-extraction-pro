| Backend | Tables found | Extra | GriTS-Con | Cell acc. | Exact | s/page |
|---|---|---|---|---|---|---|
| camelot (lattice) | 5/6 | 0 | 0.833 | 0.833 | 5/6 | 0.269 |
| camelot (stream) | 6/6 | 0 | 0.911 | 0.174 | 1/6 | 0.007 |
| tabula (lattice) | 5/6 | 0 | 0.833 | 0.833 | 5/6 | 0.257 |
| tabula (stream) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 0.742 |
| fallback (comparator) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 1.165 |
| tatr | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 0.276 |
| auto (tatr + fallback) | 6/6 | 0 | 1.000 | 1.000 | 6/6 | 1.487 |

Per fixture (GriTS-Con mean / exact tables / extra predictions / s per page):

| Backend | lattice_invoice | stream_quarterly | two_tables_one_page | multipage |
|---|---|---|---|---|
| camelot (lattice) | 1.00 / 1/1 / +0 / 0.33s | 0.00 / 0/1 / +0 / 0.20s | 1.00 / 2/2 / +0 / 0.21s | 1.00 / 2/2 / +0 / 0.34s |
| camelot (stream) | 0.91 / 0/1 / +0 / 0.02s | 0.86 / 0/1 / +0 / 0.01s | 0.94 / 1/2 / +0 / 0.01s | 0.91 / 0/2 / +0 / 0.00s |
| tabula (lattice) | 1.00 / 1/1 / +0 / 0.26s | 0.00 / 0/1 / +0 / 0.23s | 1.00 / 2/2 / +0 / 0.25s | 1.00 / 2/2 / +0 / 0.27s |
| tabula (stream) | 1.00 / 1/1 / +0 / 0.74s | 1.00 / 1/1 / +0 / 0.70s | 1.00 / 2/2 / +0 / 0.75s | 1.00 / 2/2 / +0 / 0.74s |
| fallback (comparator) | 1.00 / 1/1 / +0 / 1.18s | 1.00 / 1/1 / +0 / 1.12s | 1.00 / 2/2 / +0 / 1.19s | 1.00 / 2/2 / +0 / 1.15s |
| tatr | 1.00 / 1/1 / +0 / 0.28s | 1.00 / 1/1 / +0 / 0.22s | 1.00 / 2/2 / +0 / 0.44s | 1.00 / 2/2 / +0 / 0.27s |
| auto (tatr + fallback) | 1.00 / 1/1 / +0 / 1.49s | 1.00 / 1/1 / +0 / 1.38s | 1.00 / 2/2 / +0 / 1.68s | 1.00 / 2/2 / +0 / 1.48s |

Timing: median of 3 run(s) after one untimed warm-up, wall clock, single process.
Environment: python 3.12.11, platform Darwin arm64, java openjdk version "24.0.2" 2025-07-15, camelot-py 2.0.0, tabula-py 2.10.0, torch 2.14.1, transformers 5.20.1, PyMuPDF 1.28.2
