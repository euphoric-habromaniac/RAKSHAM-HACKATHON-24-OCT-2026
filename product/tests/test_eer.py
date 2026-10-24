import numpy as np
import pytest

from eval.eer import compute_eer


def test_perfect_separation():
    eer, thr = compute_eer([2.0, 3.0, 4.0], [-1.0, 0.0, 1.0])
    assert eer == 0.0
    assert -1.0 < thr <= 2.0


def test_identical_scores_give_half():
    eer, _ = compute_eer([0.5] * 10, [0.5] * 10)
    assert eer == pytest.approx(0.5)


def test_same_distribution_approx_half():
    rng = np.random.default_rng(0)
    eer, _ = compute_eer(rng.normal(size=5000), rng.normal(size=5000))
    assert eer == pytest.approx(0.5, abs=0.03)


def test_inverted_scores_give_one():
    # every spoof scores above every bona fide: no threshold helps, EER is 100 %
    eer, _ = compute_eer([-3.0, -2.0], [2.0, 3.0])
    assert eer == pytest.approx(1.0)


def test_hand_computed_case():
    # bonafide 1,2,3,4 ; spoof 0,1.5,2.5,3.5 (higher = more bonafide)
    # threshold 2:   FRR = 1/4 (only 1 rejected), FAR = 2/4 (2.5, 3.5 accepted)
    # threshold 2.5: FRR = 2/4,                    FAR = 2/4  -> EER = 0.5
    eer, thr = compute_eer([1, 2, 3, 4], [0, 1.5, 2.5, 3.5])
    assert eer == pytest.approx(0.5)
    assert thr == pytest.approx(2.5)


def test_hand_computed_asymmetric():
    # bonafide 0.2,0.6,0.7,0.9 ; spoof 0.1,0.3,0.4,0.8
    # t=0.6: FRR 1/4 (0.2), FAR 1/4 (0.8) -> EER 0.25
    eer, thr = compute_eer([0.2, 0.6, 0.7, 0.9], [0.1, 0.3, 0.4, 0.8])
    assert eer == pytest.approx(0.25)
    assert thr == pytest.approx(0.6)


def test_matches_bruteforce():
    rng = np.random.default_rng(1)
    b, s = rng.normal(1, 1, 300), rng.normal(-0.5, 1, 400)
    eer, _ = compute_eer(b, s)
    best = min(
        abs((b < t).mean() - (s >= t).mean()) for t in np.concatenate([b, s])
    )
    frr_far = [((b < t).mean(), (s >= t).mean()) for t in np.concatenate([b, s])]
    f, a = min(frr_far, key=lambda p: abs(p[0] - p[1]))
    assert eer == pytest.approx((f + a) / 2, abs=1e-9)
    assert best < 0.01


def test_rejects_empty_and_nan():
    with pytest.raises(ValueError):
        compute_eer([], [1.0])
    with pytest.raises(ValueError):
        compute_eer([np.nan], [1.0])
