"""The environment the bookings happen in: calendar, seasonality, city events,
holidays, weather and exchange rates. Built once, before any booking exists.
"""
from datetime import date, timedelta

import numpy as np

from . import config as C

HOLIDAYS = {  # fixed-date public holidays, enough for a calendar table
    "NL": [(1, 1, "New Year's Day"), (4, 27, "King's Day"), (12, 25, "Christmas Day")],
    "GB": [(1, 1, "New Year's Day"), (12, 25, "Christmas Day"), (12, 26, "Boxing Day")],
    "FR": [(1, 1, "New Year's Day"), (7, 14, "Bastille Day"), (12, 25, "Christmas Day")],
    "ES": [(1, 1, "New Year's Day"), (10, 12, "National Day"), (12, 25, "Christmas Day")],
    "PT": [(1, 1, "New Year's Day"), (6, 10, "Portugal Day"), (12, 25, "Christmas Day")],
    "DE": [(1, 1, "New Year's Day"), (10, 3, "German Unity Day"), (12, 25, "Christmas Day")],
    "AT": [(1, 1, "New Year's Day"), (10, 26, "National Day"), (12, 25, "Christmas Day")],
    "US": [(1, 1, "New Year's Day"), (7, 4, "Independence Day"), (12, 25, "Christmas Day")],
    "CA": [(1, 1, "New Year's Day"), (7, 1, "Canada Day"), (12, 25, "Christmas Day")],
    "AE": [(1, 1, "New Year's Day"), (12, 2, "National Day")],
    "QA": [(1, 1, "New Year's Day"), (12, 18, "National Day")],
    "BR": [(1, 1, "New Year's Day"), (9, 7, "Independence Day"), (12, 25, "Christmas Day")],
    "AR": [(1, 1, "New Year's Day"), (7, 9, "Independence Day"), (12, 25, "Christmas Day")],
    "SG": [(1, 1, "New Year's Day"), (8, 9, "National Day"), (12, 25, "Christmas Day")],
    "JP": [(1, 1, "New Year's Day"), (11, 3, "Culture Day"), (11, 23, "Labour Thanksgiving Day")],
    "ID": [(1, 1, "New Year's Day"), (8, 17, "Independence Day"), (12, 25, "Christmas Day")],
}


class World:
    def __init__(self, start: date, end: date, rng: np.random.Generator):
        self.start, self.end, self.rng = start, end, rng
        self.n = (end - start).days + 1
        self.dates = [start + timedelta(days=i) for i in range(self.n)]
        self.month = np.array([d.month for d in self.dates])
        self.dow = np.array([d.weekday() for d in self.dates])
        self.doy = np.array([d.timetuple().tm_yday for d in self.dates])
        self.years_from_bd = np.array([(d - C.BUSINESS_DATE).days / 365.25 for d in self.dates])
        self.bd = self.idx(C.BUSINESS_DATE)
        self.hotels = C.HOTELS
        H = len(self.hotels)

        self.season = np.zeros((H, self.n))
        self.week = np.zeros((H, self.n))
        self.event = np.ones((H, self.n))  # true demand multiplier from city events
        self.event_in_rms = np.ones((H, self.n))  # what the hotel's own pricing calendar knows about
        self.events = []  # rows for the city_events table
        for h, hotel in enumerate(self.hotels):
            self.season[h] = self._smooth_season(C.SEASON[hotel.season])
            self.week[h] = np.array(C.WEEK[hotel.week])[self.dow]
        self._city_events()

        growth = 1.02 ** self.years_from_bd  # the market grows about 2% a year
        self.target_occ = np.array([h.base_occ for h in self.hotels])[:, None] * self.season * self.week \
            * self.event * growth
        # The price the hotel's revenue system starts from before it sees any pickup.
        inflation = 1.04 ** self.years_from_bd
        base = np.array([h.base_adr for h in self.hotels])[:, None]
        self.base_price = base / C.ADR_TO_BAR * (1 + 0.8 * (self.season - 1)) * (1 + 0.5 * (self.week - 1)) \
            * self.event_in_rms ** 0.8 * inflation
        self._weather()
        self._fx()

    def idx(self, d: date) -> int:
        return (d - self.start).days

    def in_range(self, d: date) -> bool:
        return 0 <= self.idx(d) < self.n

    def _smooth_season(self, months):
        anchors = np.array([15 + 30.44 * m for m in range(12)])
        xs = np.concatenate([anchors - 365.25, anchors, anchors + 365.25])
        return np.interp(self.doy, xs, np.array(months * 3))

    def _city_events(self):
        s6 = C.STORIES["S6_DXB_EVENT_UNDERPRICED"]
        for city, name, month, day, nights, mult in C.CITY_EVENTS:
            for year in range(self.start.year - 1, self.end.year + 1):
                first = date(year, month, day)
                last = first + timedelta(days=nights - 1)
                if last < self.start or first > self.end:
                    continue
                self.events.append(dict(city=city, name=name, start_date=first, end_date=last,
                                        expected_demand_uplift=round(mult - 1, 2)))
                a, b = max(self.idx(first), 0), min(self.idx(last), self.n - 1)
                for h, hotel in enumerate(self.hotels):
                    if hotel.city != city:
                        continue
                    self.event[h, a:b + 1] *= mult
                    if not (hotel.code == s6["hotel"] and name == s6["event"]):
                        self.event_in_rms[h, a:b + 1] *= mult

    def _weather(self):
        rng, H = self.rng, len(self.hotels)
        self.temp_max = np.zeros((H, self.n))
        self.precip = np.zeros((H, self.n))
        for h, hotel in enumerate(self.hotels):
            seasonal = hotel.temp_mean + hotel.temp_amp * -np.cos(2 * np.pi * (self.doy - 20) / 365.25)
            ar = np.zeros(self.n)
            for i in range(1, self.n):
                ar[i] = 0.7 * ar[i - 1] + rng.normal(0, 1.6)
            self.temp_max[h] = np.round(seasonal + 4 + ar, 1)
            rain = rng.random(self.n) < hotel.rain_p
            self.precip[h] = np.round(np.where(rain, rng.gamma(1.4, 5.0, self.n), 0), 1)

    def _fx(self):
        self.fx = {}
        for cur, rate in C.FX_TO_EUR.items():
            if cur == "EUR":
                self.fx[cur] = np.ones(self.n)
                continue
            walk = np.cumsum(self.rng.normal(0, 0.004, self.n))
            walk -= walk[min(self.bd, self.n - 1)]
            self.fx[cur] = rate * np.exp(walk)

    def holidays(self):
        rows = []
        for country, days in HOLIDAYS.items():
            for year in range(self.start.year, self.end.year + 1):
                for month, day, name in days:
                    d = date(year, month, day)
                    if self.in_range(d):
                        rows.append(dict(country=country, date=d, name=name))
        return rows
