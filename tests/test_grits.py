import pytest

from table_extraction.evaluation import GriTSEvaluator, cell_accuracy, grits_con, grits_top, lcs_similarity
from table_extraction.evaluation.grits import align_1d

TRUE = [["a", "b"], ["c", "d"], ["e", "f"]]


def test_lcs_similarity():
    assert lcs_similarity("", "") == 1.0
    assert lcs_similarity("abc", "") == 0.0
    assert lcs_similarity("abc", "abc") == 1.0
    assert lcs_similarity("abc", "abd") == pytest.approx(2 * 2 / 6)


def test_align_1d_skips_inserted_element():
    seq1, seq2 = ["x", "y", "z"], ["x", "junk", "y", "z"]
    pairs, score = align_1d(3, 4, lambda i, j: float(seq1[i] == seq2[j]))
    assert pairs == [(0, 0), (1, 2), (2, 3)]
    assert score == 3


def test_identical_grids_score_one():
    for metric in (grits_con, grits_top):
        r = metric(TRUE, TRUE)
        assert r["f1"] == r["precision"] == r["recall"] == 1.0
    assert cell_accuracy(TRUE, TRUE) == 1.0


def test_empty_prediction_scores_zero():
    assert grits_con(TRUE, [])["f1"] == 0.0
    assert grits_top(TRUE, [])["recall"] == 0.0
    assert cell_accuracy(TRUE, []) == 0.0


def test_missing_row():
    r = grits_con(TRUE, TRUE[:2])
    assert r["precision"] == 1.0
    assert r["recall"] == pytest.approx(4 / 6)
    assert r["f1"] == pytest.approx(2 * 4 / (6 + 4))


def test_extra_junk_column_hurts_precision_only():
    pred = [row + ["zz"] for row in TRUE]
    r = grits_con(TRUE, pred)
    assert r["recall"] == 1.0
    assert r["precision"] == pytest.approx(6 / 9)


def test_inserted_caption_row_is_aligned_away():
    pred = [["Report", ""]] + TRUE
    r = grits_con(TRUE, pred)
    assert r["recall"] == 1.0
    assert r["precision"] == pytest.approx(6 / 8)
    # Strict cell accuracy has no alignment: every row is shifted.
    assert cell_accuracy(TRUE, pred) == 0.0


def test_partial_cell_credit():
    pred = [["a", "b"], ["c", "d"], ["e", "fx"]]
    r = grits_con(TRUE, pred)
    assert r["f1"] == pytest.approx((5 + 2 / 3) / 6)
    assert grits_top(TRUE, pred)["f1"] == 1.0


def test_symmetric_f1():
    pred = [["a", "q"], ["c", "d"]]
    assert grits_con(TRUE, pred)["f1"] == pytest.approx(grits_con(pred, TRUE)["f1"])


def test_ragged_rows_are_padded():
    assert grits_con([["a", "b"], ["c"]], [["a", "b"], ["c", ""]])["f1"] == 1.0


def test_evaluator_accepts_table_dicts_and_lists():
    ev = GriTSEvaluator()
    m = ev.evaluate_structure({"data": TRUE}, TRUE)
    assert m["grits_con"] == 1.0 and m["exact_match"] == 1.0
    batch = ev.evaluate_batch([TRUE, TRUE[:2]], [TRUE, TRUE])
    assert batch["num_samples"] == 2
    assert batch["grits_con"] == pytest.approx((1.0 + 0.8) / 2)
    with pytest.raises(ValueError):
        ev.evaluate_batch([TRUE], [])
