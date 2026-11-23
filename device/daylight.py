"""Approximate London sunrise and sunset in UTC using NOAA solar equations."""
import datetime as dt
from functools import lru_cache
from math import acos, cos, isfinite, radians, sin, tan, degrees, tau


@lru_cache(maxsize=4)
def london_daylight(day):
    year_days = (dt.date(day.year + 1, 1, 1) - dt.date(day.year, 1, 1)).days
    angle = tau * (day.timetuple().tm_yday - 1) / year_days
    equation = 229.18 * (0.000075 + 0.001868*cos(angle) - 0.032077*sin(angle)
                         - 0.014615*cos(2*angle) - 0.040849*sin(2*angle))
    declination = (0.006918 - 0.399912*cos(angle) + 0.070257*sin(angle)
                   - 0.006758*cos(2*angle) + 0.000907*sin(2*angle)
                   - 0.002697*cos(3*angle) + 0.00148*sin(3*angle))
    latitude = radians(51.5074)
    hour_angle = degrees(acos(cos(radians(90.833))/(cos(latitude)*cos(declination))
                              - tan(latitude)*tan(declination)))
    noon = 720 - 4*(-0.1278) - equation
    midnight = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
    return (midnight + dt.timedelta(minutes=noon - 4*hour_angle),
            midnight + dt.timedelta(minutes=noon + 4*hour_angle))


class Daylight:
    def __init__(self, config):
        margin = float(config.get("daylight_margin_minutes", 0))
        if not isfinite(margin) or not -120 <= margin <= 120:
            raise ValueError("daylight_margin_minutes must be between -120 and 120")
        self.margin = dt.timedelta(minutes=margin)

    def allows(self, now):
        now = now.astimezone(dt.timezone.utc)
        sunrise, sunset = london_daylight(now.date())
        return sunrise + self.margin <= now < sunset - self.margin
