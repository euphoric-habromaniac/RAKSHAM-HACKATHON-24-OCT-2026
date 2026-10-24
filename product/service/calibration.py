"""Platt (logistic) scaling: probability = 1 / (1 + exp(-(a * x + b)))."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import PlattParams


@dataclass(frozen=True)
class Platt:
    a: float
    b: float

    @classmethod
    def from_config(cls, p: PlattParams) -> "Platt":
        return cls(a=p.a, b=p.b)

    def __call__(self, x: float) -> float:
        z = self.a * x + self.b
        # numerically stable sigmoid
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        e = math.exp(z)
        return e / (1.0 + e)


def fit_platt(scores, labels, iters: int = 5000, lr: float = 0.1) -> Platt:
    """Fit a, b by gradient descent on log loss. Offline helper, not used at runtime.

    labels are 1 for the positive (risky) class. Plain Python so the service
    needs no numpy; use scikit-learn for large sets.
    """
    n = len(scores)
    if n == 0 or n != len(labels):
        raise ValueError("scores and labels must be the same non-zero length")
    a, b = 0.0, 0.0
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(scores, labels):
            p = Platt(a, b)(x)
            ga += (p - y) * x
            gb += (p - y)
        a -= lr * ga / n
        b -= lr * gb / n
    return Platt(a, b)
