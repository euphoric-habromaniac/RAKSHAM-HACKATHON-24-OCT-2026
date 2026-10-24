"""Equal error rate from bona fide and spoof scores.

Convention (as in ASVspoof): higher score = more likely bona fide.
"""
from __future__ import annotations

import numpy as np


def compute_eer(bonafide_scores, spoof_scores) -> tuple:
    """Return (eer, threshold).

    A trial is accepted as bona fide when score >= threshold. The false
    rejection rate (FRR) is the fraction of bona fide scores below the
    threshold; the false acceptance rate (FAR) is the fraction of spoof
    scores at or above it. The EER is read at the candidate threshold where FRR and
    FAR are closest, reported as their mean (the usual ROC method).
    """
    bona = np.asarray(bonafide_scores, dtype=np.float64).ravel()
    spoof = np.asarray(spoof_scores, dtype=np.float64).ravel()
    if bona.size == 0 or spoof.size == 0:
        raise ValueError("need at least one bona fide and one spoof score")
    if not (np.isfinite(bona).all() and np.isfinite(spoof).all()):
        raise ValueError("scores contain NaN or inf")

    # candidate thresholds: every distinct score, plus one above the maximum (accept nothing)
    thr = np.unique(np.concatenate([bona, spoof]))
    thr = np.concatenate([thr, [thr[-1] + 1.0]])
    bona_sorted, spoof_sorted = np.sort(bona), np.sort(spoof)
    frr = np.searchsorted(bona_sorted, thr, side="left") / bona.size
    far = 1.0 - np.searchsorted(spoof_sorted, thr, side="left") / spoof.size

    idx = int(np.argmin(np.abs(frr - far)))  # ROC point where FRR and FAR are closest
    return float((frr[idx] + far[idx]) / 2), float(thr[idx])
