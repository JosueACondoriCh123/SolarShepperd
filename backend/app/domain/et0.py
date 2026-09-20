from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

ET0_MODEL_VERSION = "hargreaves-samani-v1"
SOLAR_CONSTANT_MJ_M2_MIN = 0.0820


class ET0InputError(ValueError):
    """Raised when ET0 inputs are physically invalid."""


@dataclass(frozen=True)
class ET0Result:
    value_mm_day: float
    extraterrestrial_radiation_mj_m2_day: float
    model_version: str = ET0_MODEL_VERSION


def extraterrestrial_radiation(latitude_deg: float, day_of_year: int) -> float:
    """FAO-56 daily extraterrestrial radiation in MJ m-2 day-1."""
    if not -90 <= latitude_deg <= 90:
        raise ET0InputError("latitude must be between -90 and 90 degrees")
    if not 1 <= day_of_year <= 366:
        raise ET0InputError("day_of_year must be between 1 and 366")

    latitude_rad = math.radians(latitude_deg)
    inverse_relative_distance = 1 + 0.033 * math.cos((2 * math.pi / 365) * day_of_year)
    solar_declination = 0.409 * math.sin((2 * math.pi / 365) * day_of_year - 1.39)
    sunset_argument = -math.tan(latitude_rad) * math.tan(solar_declination)
    sunset_argument = max(-1.0, min(1.0, sunset_argument))
    sunset_hour_angle = math.acos(sunset_argument)
    radiation = (
        (24 * 60 / math.pi)
        * SOLAR_CONSTANT_MJ_M2_MIN
        * inverse_relative_distance
        * (
            sunset_hour_angle * math.sin(latitude_rad) * math.sin(solar_declination)
            + math.cos(latitude_rad) * math.cos(solar_declination) * math.sin(sunset_hour_angle)
        )
    )
    return max(0.0, radiation)


def hargreaves_samani_et0(
    minimum_temperature_c: float,
    maximum_temperature_c: float,
    latitude_deg: float,
    observed_date: date,
) -> ET0Result:
    """Calculate reference evapotranspiration in mm/day.

    The function deliberately takes latitude and date instead of a free-form
    radiation number, preventing measured solar radiation from being silently
    substituted for extraterrestrial radiation.
    """
    values = (minimum_temperature_c, maximum_temperature_c, latitude_deg)
    if not all(math.isfinite(value) for value in values):
        raise ET0InputError("all numeric inputs must be finite")
    if maximum_temperature_c < minimum_temperature_c:
        raise ET0InputError("maximum temperature cannot be below minimum temperature")

    ra = extraterrestrial_radiation(latitude_deg, observed_date.timetuple().tm_yday)
    mean_temperature = (minimum_temperature_c + maximum_temperature_c) / 2
    daily_range = maximum_temperature_c - minimum_temperature_c
    value = 0.0023 * (mean_temperature + 17.8) * math.sqrt(daily_range) * ra
    return ET0Result(value_mm_day=max(0.0, value), extraterrestrial_radiation_mj_m2_day=ra)
