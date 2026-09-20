from __future__ import annotations

import math

SPECTRAL_MODEL_VERSION = "spectral-indices-v1"


def normalized_difference(first: float, second: float) -> float | None:
    if not math.isfinite(first) or not math.isfinite(second):
        return None
    denominator = first + second
    if abs(denominator) < 1e-12:
        return None
    return max(-1.0, min(1.0, (first - second) / denominator))


def ndvi(nir_b08: float, red_b04: float) -> float | None:
    return normalized_difference(nir_b08, red_b04)


def ndmi(nir_b08: float, swir_b11: float) -> float | None:
    return normalized_difference(nir_b08, swir_b11)
