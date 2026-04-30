"""Vector similarity and distance functions.

All functions accept plain Python lists; numpy is not required.
"""

from __future__ import annotations

import math


def dot_product(a: list[float], b: list[float]) -> float:
    """Compute the dot product of two vectors."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    dot = dot_product(a, b)
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def euclidean_distance(a: list[float], b: list[float]) -> float:
    """Compute Euclidean distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))
