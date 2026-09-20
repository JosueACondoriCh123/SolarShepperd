from app.domain.indices import ndmi, ndvi, normalized_difference


def test_ndvi_and_ndmi_use_intended_bands() -> None:
    assert ndvi(0.7, 0.2) == normalized_difference(0.7, 0.2)
    assert ndmi(0.7, 0.3) == normalized_difference(0.7, 0.3)


def test_normalized_difference_handles_zero_denominator() -> None:
    assert normalized_difference(0.0, 0.0) is None


def test_normalized_difference_is_bounded() -> None:
    result = normalized_difference(2.0, -1.5)
    assert result == 1.0
