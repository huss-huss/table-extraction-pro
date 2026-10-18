"""
Grid table similarity (GriTS) for 2D cell grids.

Implements the factored 2D most-similar-substructure (2D-MSS) approximation
from Smock, Pesala & Abraham, "GriTS: Grid table similarity metric for table
structure recognition" (2022), following the reference implementation in the
microsoft/table-transformer repository:

1. For every (true row, predicted row) pair, align the two rows' cells with a
   1D dynamic program and use the alignment score as the row-pair reward.
2. Align rows using those rewards (another 1D DP); do the same for columns.
3. The GriTS score is the summed cell reward over the aligned rows x columns
   substructure; precision / recall / F divide it by the predicted, true and
   mean grid sizes.

Rewards:
- GriTS-Con: 2 * LCS(a, b) / (len(a) + len(b)) on cell text (1.0 if both empty).
- GriTS-Top: every cell covers exactly its own grid slot (no spanning cells
  in this grid representation), so the reward is 1 for any pair and the
  score only measures how much of the grid shape is recovered.

GriTS-Loc (bounding-box IoU) needs cell boxes and is not computed here.
"""

from functools import lru_cache
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np

Grid = Sequence[Sequence[str]]


def _rectangular(grid: Grid) -> List[List[str]]:
    rows = [["" if c is None else str(c).strip() for c in row] for row in grid]
    width = max((len(r) for r in rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


@lru_cache(maxsize=65536)
def lcs_similarity(a: str, b: str) -> float:
    """Normalized longest-common-subsequence similarity of two strings."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for ch in a:
        cur = [0]
        for j, other in enumerate(b, start=1):
            cur.append(prev[j - 1] + 1 if ch == other else max(prev[j], cur[j - 1]))
        prev = cur
    return 2.0 * prev[-1] / (len(a) + len(b))


def align_1d(n1: int, n2: int, reward: Callable[[int, int], float]) -> Tuple[List[Tuple[int, int]], float]:
    """
    Order-preserving alignment of two sequences maximizing the summed reward.

    Returns the aligned index pairs and the total score.
    """
    scores = np.zeros((n1 + 1, n2 + 1))
    pointers = np.zeros((n1 + 1, n2 + 1), dtype=np.int8)  # 0 diag, -1 up, 1 left
    pointers[1:, 0] = -1
    pointers[0, 1:] = 1
    for i in range(1, n1 + 1):
        for j in range(1, n2 + 1):
            diag = scores[i - 1, j - 1] + reward(i - 1, j - 1)
            up = scores[i - 1, j]
            left = scores[i, j - 1]
            best = max(diag, up, left)
            scores[i, j] = best
            pointers[i, j] = 0 if diag == best else (-1 if up == best else 1)
    pairs = []
    i, j = n1, n2
    while i > 0 and j > 0:
        p = pointers[i, j]
        if p == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif p == -1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs, float(scores[n1, n2])


def factored_2dmss(
    true_grid: Grid, pred_grid: Grid, reward_fn: Callable[[str, str], float]
) -> Dict[str, float]:
    """Factored 2D-MSS between two grids; returns score, precision, recall, f1."""
    t = _rectangular(true_grid)
    p = _rectangular(pred_grid)
    n_true = len(t) * (len(t[0]) if t else 0)
    n_pred = len(p) * (len(p[0]) if p else 0)
    if n_true == 0 or n_pred == 0:
        both_empty = n_true == 0 and n_pred == 0
        v = 1.0 if both_empty else 0.0
        return {"score": 0.0, "precision": v, "recall": v, "f1": v}

    tr, tc, pr, pc = len(t), len(t[0]), len(p), len(p[0])
    rewards = np.empty((tr, pr, tc, pc))
    for a in range(tr):
        for b in range(pr):
            for c in range(tc):
                for d in range(pc):
                    rewards[a, b, c, d] = reward_fn(t[a][c], p[b][d])

    row_reward = np.empty((tr, pr))
    for a in range(tr):
        for b in range(pr):
            row_reward[a, b] = align_1d(tc, pc, lambda c, d, a=a, b=b: rewards[a, b, c, d])[1]
    col_reward = np.empty((tc, pc))
    for c in range(tc):
        for d in range(pc):
            col_reward[c, d] = align_1d(tr, pr, lambda a, b, c=c, d=d: rewards[a, b, c, d])[1]

    row_pairs, _ = align_1d(tr, pr, lambda a, b: row_reward[a, b])
    col_pairs, _ = align_1d(tc, pc, lambda c, d: col_reward[c, d])
    score = float(sum(rewards[a, b, c, d] for a, b in row_pairs for c, d in col_pairs))
    return {
        "score": score,
        "precision": score / n_pred,
        "recall": score / n_true,
        "f1": 2.0 * score / (n_true + n_pred),
    }


def grits_con(true_grid: Grid, pred_grid: Grid) -> Dict[str, float]:
    """GriTS-Con: content similarity of two text grids."""
    return factored_2dmss(true_grid, pred_grid, lcs_similarity)


def grits_top(true_grid: Grid, pred_grid: Grid) -> Dict[str, float]:
    """GriTS-Top for grids without spanning cells (shape agreement)."""
    return factored_2dmss(true_grid, pred_grid, lambda a, b: 1.0)


def cell_accuracy(true_grid: Grid, pred_grid: Grid) -> float:
    """
    Strict cell accuracy: share of positions (over the larger grid) whose text
    matches exactly at the same row/column index. No alignment, so a single
    inserted row or column shifts every following cell and counts as errors.
    """
    t = _rectangular(true_grid)
    p = _rectangular(pred_grid)
    rows = max(len(t), len(p))
    cols = max(len(t[0]) if t else 0, len(p[0]) if p else 0)
    if rows * cols == 0:
        return 1.0 if not t and not p else 0.0
    hits = 0
    for i in range(rows):
        for j in range(cols):
            a = t[i][j] if i < len(t) and j < len(t[i]) else None
            b = p[i][j] if i < len(p) and j < len(p[i]) else None
            hits += a is not None and a == b
    return hits / (rows * cols)
