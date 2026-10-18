import pytest

from table_extraction.parsers.base import build_table
from table_extraction.parsers.parser_comparator import ParserComparator
from tests.fixtures.generate import INVOICE, METRICS, QUARTERLY, STAFF

BOX_A = [72, 100, 300, 190]
BOX_B = [72, 300, 300, 380]


def t(data, parser, page=1, bbox=None, confidence=0.9, table_id=1):
    return build_table([list(r) for r in data], page, parser, confidence, page_bbox=bbox, table_id=table_id)


@pytest.fixture
def comparator():
    return ParserComparator()


def test_same_table_with_spilled_title_row_is_grouped(comparator):
    with_title = [["Quarterly report", "", "", "", ""]] + QUARTERLY
    camelot = t(with_title, "camelot", bbox=[68, 90, 420, 240], confidence=0.96)
    tabula = t(QUARTERLY, "tabula", bbox=[71, 101, 418, 222], confidence=0.8)
    best = comparator._select_best_tables([camelot, tabula])
    assert len(best) == 1
    assert best[0]["data"] == QUARTERLY
    assert sorted(best[0]["metadata"]["candidates"]) == ["camelot", "tabula"]


def test_distinct_tables_on_same_page_are_kept(comparator):
    tables = [
        t(STAFF, "camelot", bbox=BOX_A),
        t(METRICS, "camelot", bbox=BOX_B, table_id=2),
        t(STAFF, "tabula", bbox=BOX_A),
        t(METRICS, "tabula", bbox=BOX_B, table_id=2),
    ]
    best = comparator._select_best_tables(tables)
    assert [b["data"] for b in best] == [STAFF, METRICS]


def test_same_shape_different_content_not_merged_without_bbox(comparator):
    a = [["a", "b"], ["1", "2"], ["3", "4"]]
    b = [["x", "y"], ["5", "6"], ["7", "8"]]
    best = comparator._select_best_tables([t(a, "camelot"), t(b, "tabula")])
    assert len(best) == 2


def test_tables_on_different_pages_never_grouped(comparator):
    best = comparator._select_best_tables(
        [t(INVOICE, "camelot", page=2, bbox=BOX_A), t(INVOICE, "tabula", page=1, bbox=BOX_A)]
    )
    assert [(b["page_number"], b["table_id"]) for b in best] == [(1, 1), (2, 2)]


def test_ids_are_unique_and_ordered_top_to_bottom(comparator):
    tables = [
        t(METRICS, "camelot", bbox=BOX_B, table_id=1),
        t(STAFF, "tabula", bbox=BOX_A, table_id=1),
    ]
    best = comparator._select_best_tables(tables)
    assert [b["data"] for b in best] == [STAFF, METRICS]
    assert [b["table_id"] for b in best] == [1, 2]


def test_text_less_tatr_table_loses_to_fallback_with_text(comparator):
    tatr = t([[""] * 4 for _ in INVOICE], "tatr", bbox=[70, 98, 302, 192], confidence=0.99)
    camelot = t(INVOICE, "camelot", bbox=BOX_A, confidence=0.95)
    best = comparator._select_best_tables([tatr, camelot])
    assert len(best) == 1
    assert best[0]["metadata"]["parser"] == "camelot"


def test_tatr_with_text_preferred_on_tie(comparator):
    tatr = t(INVOICE, "tatr", bbox=BOX_A, confidence=0.9)
    tabula = t(INVOICE, "tabula", bbox=BOX_A, confidence=0.9)
    best = comparator._select_best_tables([tabula, tatr])
    assert best[0]["metadata"]["parser"] == "tatr"


def test_score_rewards_completeness(comparator):
    full = t(INVOICE, "camelot")
    sparse_data = [row[:] for row in INVOICE]
    for row in sparse_data[1:]:
        row[2] = ""
    sparse = t(sparse_data, "camelot")
    assert comparator._calculate_table_score(full) > comparator._calculate_table_score(sparse)


def test_compare_parsers_end_to_end_skips_missing_backends(monkeypatch, comparator):
    from table_extraction.parsers import parser_comparator

    monkeypatch.setattr(parser_comparator, "is_available", lambda name: name == "camelot")
    monkeypatch.setattr(
        comparator.camelot_parser,
        "extract_tables_with_multiple_flavors",
        lambda path: [t(INVOICE, "camelot", bbox=BOX_A)],
    )
    best = comparator.compare_parsers("doc.pdf")
    assert [b["data"] for b in best] == [INVOICE]
