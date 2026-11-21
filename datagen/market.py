"""The market around each hotel: a comp set of four fictional competitors,
their rates as a rate shopper would see them, and comp set performance
(what a benchmarking feed such as an STR-style report would deliver).
"""
from datetime import timedelta

import numpy as np

from . import config as C

COMP_NAMES = ["Grand", "Plaza", "Residence", "Harbour", "Central", "Royal", "Quarter", "House"]
SHOP_LEADS = [0, 7, 14, 28]  # days before the business date the shops ran, for future stay dates


def build(world, rng):
    H, n = len(world.hotels), world.n
    # The market's own price: it sees every event, unlike some hotels' pricing calendars.
    inflation = 1.04 ** world.years_from_bd
    base = np.array([h.base_adr for h in world.hotels])[:, None]
    market_price = base / C.ADR_TO_BAR * (1 + 0.8 * (world.season - 1)) * (1 + 0.5 * (world.week - 1)) \
        * world.event ** 1.1 * inflation

    competitors, rates, perf = [], [], []
    comp_ref = np.zeros((H, n))
    cid = 0
    for h, hotel in enumerate(world.hotels):
        names = rng.choice(COMP_NAMES, 4, replace=False)
        levels = np.sort(rng.uniform(0.82, 1.18, 4))[::-1]
        per_comp = []
        for name, level in zip(names, levels):
            cid += 1
            competitors.append(dict(competitor_id=cid, hotel_code=hotel.code, name=f"{hotel.city} {name}",
                                    stars=hotel.stars, rooms=int(hotel.rooms * rng.uniform(0.6, 1.6)),
                                    distance_km=round(float(rng.uniform(0.2, 2.5)), 1)))
            final = market_price[h] * level * rng.normal(1, 0.04, n)
            per_comp.append(final)
            for i, d in enumerate(world.dates):
                if i < world.bd:
                    shops = [(d - timedelta(days=1), final[i])]
                else:
                    shops = [(C.BUSINESS_DATE - timedelta(days=k), final[i] * (1 - 0.002 * (i - world.bd + k)))
                             for k in SHOP_LEADS if C.BUSINESS_DATE - timedelta(days=k) < d]
                for shop_date, rate in shops:
                    sold_out = world.target_occ[h, i] > 1.02 and rng.random() < 0.5
                    rates.append(dict(competitor_id=cid, stay_date=d, shop_date=shop_date,
                                      rate=None if sold_out else round(float(rate), 2),
                                      currency=hotel.currency, sold_out=sold_out))
        comp_ref[h] = np.median(np.stack(per_comp), axis=0)

        supply = sum(c["rooms"] for c in competitors if c["hotel_code"] == hotel.code)
        occ = np.clip(world.target_occ[h] * rng.normal(1, 0.035, n), 0.25, 0.97)
        adr = comp_ref[h] * C.ADR_TO_BAR * rng.normal(1, 0.02, n)  # the comp set's ADR, all room types
        for i, d in enumerate(world.dates[:world.bd]):
            perf.append(dict(hotel_code=hotel.code, date=d, rooms_available=supply,
                             rooms_sold=int(supply * occ[i]), room_revenue=round(float(supply * occ[i] * adr[i]), 2),
                             currency=hotel.currency))
    return dict(competitors=competitors, comp_rates=rates, comp_set_daily=perf), comp_ref
