"""Reference tables, the preview cut and CSV output."""
import os
from datetime import date, timedelta

import pandas as pd

from . import config as C


def reference(world):
    hotels = [dict(hotel_code=h.code, name=h.name, brand_code=h.brand, city=h.city, country=h.country,
                   region=h.region, currency=h.currency, timezone=h.timezone, rooms=h.rooms, stars=h.stars,
                   profile=h.profile, meeting_space_sqm=h.meeting_sqm, pms_vendor=h.pms, pos_vendor=h.pos)
              for h in world.hotels]
    brands = [dict(brand_code=b.code, name=b.name, tier=b.tier, group_name=C.GROUP_NAME) for b in C.BRANDS.values()]
    segments = [dict(segment=s.code, name=s.name, rate_plan=s.rate_plan, is_contracted=s.contracted)
                for s in C.SEGMENTS.values()]
    channels = [dict(channel=c, name=nm, channel_type=t, commission_pct=pct, fee_per_booking_eur=fee)
                for c, nm, t, pct, fee in C.CHANNELS]
    weather, fx = [], []
    for h, hotel in enumerate(world.hotels):
        for i, d in enumerate(world.dates[:world.bd]):
            weather.append(dict(hotel_code=hotel.code, date=d, temp_max_c=float(world.temp_max[h, i]),
                                precipitation_mm=float(world.precip[h, i])))
    for cur, series in world.fx.items():
        if cur == "EUR":
            continue
        for i, d in enumerate(world.dates[:world.bd + 1]):
            fx.append(dict(currency=cur, date=d, eur_per_unit=round(float(series[i]), 8)))
    return dict(brands=brands, hotels=hotels, segments=segments, channels=channels, city_events=world.events,
                holidays=world.holidays(), weather_daily=weather, fx_rates=fx)


def _preview(t):
    """About ten reservations per hotel, everything that hangs off them, and one or two days of the daily tables."""
    bd = C.BUSINESS_DATE
    d1, d7 = bd - timedelta(days=1), bd + timedelta(days=7)
    res, reviews = t["reservations"], t["reviews"]
    reviewed = set(reviews["reservation_id"])
    picks = []
    for _, g in res.groupby("hotel_code"):
        chosen = []
        for status, k in (("checked_out", 2), ("checked_out", 2), ("in_house", 1), ("confirmed", 3),
                          ("cancelled", 1), ("no_show", 1)):
            pool = g[(g["status"] == status) & ~g["reservation_id"].isin(chosen)]
            if status == "checked_out" and len([c for c in chosen if c in reviewed]) < 2:
                pool = pool[pool["reservation_id"].isin(reviewed)]
            chosen += list(pool["reservation_id"].sample(min(k, len(pool)), random_state=1))
        rest = g[~g["reservation_id"].isin(chosen)]
        chosen += list(rest["reservation_id"].sample(max(0, 10 - len(chosen)), random_state=1))
        picks += chosen[:10]
    r = res[res["reservation_id"].isin(picks)]
    keep = dict(t)
    keep["reservations"] = r
    keep["reservation_nights"] = t["reservation_nights"][t["reservation_nights"]["reservation_id"].isin(picks)]
    keep["guests"] = t["guests"][t["guests"]["guest_id"].isin(r["guest_id"])]
    keep["reviews"] = reviews[reviews["reservation_id"].isin(picks)]
    blocks = t["group_blocks"]
    linked = blocks["group_block_id"].isin(r["group_block_id"].dropna())
    keep["group_blocks"] = pd.concat([blocks[linked], blocks[~linked].groupby("hotel_code").head(1)])
    acc = t["accounts"]
    keep["accounts"] = acc[(acc["account_type"] != "group") | acc["account_id"].isin(keep["group_blocks"]["account_id"])]
    me = t["me_events"]
    keep["me_events"] = me.sort_values("group_block_id", na_position="last").groupby("hotel_code").head(2)
    for name, col, days in (("room_inventory_daily", "date", {d1, d7}), ("rates_daily", "stay_date", {d1, d7}),
                            ("comp_set_daily", "date", {d1}), ("forecasts", "stay_date", {d7}),
                            ("fnb_daily", "date", {d1}), ("labor_daily", "date", {d1}), ("web_daily", "date", {d1}),
                            ("marketing_spend", "date", {d1}), ("weather_daily", "date", {d1}),
                            ("fx_rates", "date", {bd}), ("rate_changes", "stay_date", {d7}),
                            ("lost_business", "arrival_date", {d7})):
        keep[name] = t[name][t[name][col].isin(days)]
    cr = t["comp_rates"]
    keep["comp_rates"] = cr[(cr["stay_date"] == d7) & (cr["shop_date"] == cr["shop_date"].max())]
    oct_, nov = date(bd.year, bd.month, 1) - timedelta(days=1), date(bd.year, bd.month, 1)
    keep["pnl_monthly"] = t["pnl_monthly"][t["pnl_monthly"]["month"].isin({oct_.replace(day=1), nov})]
    keep["budgets"] = t["budgets"][t["budgets"]["month"] == nov]
    return keep


def save(tables, out, preview=False):
    t = {k: pd.DataFrame(v) for k, v in tables.items()}
    if preview:
        t = _preview(t)
    os.makedirs(out, exist_ok=True)
    counts = {}
    for name, df in sorted(t.items()):
        for col in df.columns:  # nullable ids would otherwise be written as 12.0, which Postgres rejects
            if col.endswith("_id") and df[col].dtype.kind == "f":
                df[col] = df[col].astype("Int64")
        df.to_csv(os.path.join(out, f"{name}.csv"), index=False)
        counts[name] = len(df)
    return counts
