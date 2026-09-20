from datetime import date

import pytest

from app.domain.et0 import ET0InputError, extraterrestrial_radiation, hargreaves_samani_et0


def test_extraterrestrial_radiation_is_physical_at_jkuat() -> None:
    radiation = extraterrestrial_radiation(-1.1018, 180)
    assert 20 < radiation < 45


def test_hargreaves_returns_mm_per_day_and_version() -> None:
    result = hargreaves_samani_et0(15.0, 28.0, -1.1018, date(2026, 6, 29))
    assert result.value_mm_day > 0
    assert result.value_mm_day < 20
    assert result.model_version == "hargreaves-samani-v1"


def test_hargreaves_rejects_inverted_temperature_range() -> None:
    with pytest.raises(ET0InputError, match="maximum temperature"):
        hargreaves_samani_et0(30, 20, -1.1018, date(2026, 1, 1))


def test_hargreaves_allows_zero_daily_range_without_fabrication() -> None:
    result = hargreaves_samani_et0(20, 20, -1.1018, date(2026, 1, 1))
    assert result.value_mm_day == 0
