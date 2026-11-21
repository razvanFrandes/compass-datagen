"""A monthly P&L per hotel in a simplified USALI layout, posted from the
operating tables: actual for complete months, budget for every month, and a
forecast for the current and future months. Amounts are in local currency.
"""
from datetime import date

import numpy as np
import pandas as pd

from . import config as C

LINES = ["ROOMS_REVENUE", "FNB_REVENUE", "ME_REVENUE", "OTHER_REVENUE", "TOTAL_REVENUE",
         "ROOMS_EXPENSE", "FNB_EXPENSE", "DEPARTMENTAL_PROFIT",
         "AG_EXPENSE", "SM_EXPENSE", "POM_EXPENSE", "UTILITIES_EXPENSE", "GOP"]
COMMISSION = {code: pct / 100 for code, _, _, pct, _ in C.CHANNELS}
# Used for a hotel with no complete month of actuals yet: each line as a share of room revenue.
DEFAULT_RATIO = {"ROOMS_REVENUE": 1, "FNB_REVENUE": 0.3, "ME_REVENUE": 0.05, "OTHER_REVENUE": 0.04,
                 "TOTAL_REVENUE": 1.39, "ROOMS_EXPENSE": 0.3, "FNB_EXPENSE": 0.25, "DEPARTMENTAL_PROFIT": 0.84,
                 "AG_EXPENSE": 0.1, "SM_EXPENSE": 0.07, "POM_EXPENSE": 0.05, "UTILITIES_EXPENSE": 0.05, "GOP": 0.57}


def _month(d):
    return date(d.year, d.month, 1)


def _sum(df, by, col):
    """Sum a column by (hotel_code, month[, extra]) into a dict; empty frames give an empty dict."""
    if df.empty:
        return {}
    return df.groupby(by)[col].sum().to_dict()


def build(world, tables, ops, rng):
    res = pd.DataFrame(tables["reservations"]).set_index("reservation_id")
    nights = pd.DataFrame(tables["reservation_nights"])
    nights["month"] = nights["stay_date"].map(_month)
    nights["commission"] = nights["room_revenue"] * nights["reservation_id"].map(res["channel"]).map(COMMISSION)
    fnb, labor = pd.DataFrame(ops["fnb_daily"]), pd.DataFrame(ops["labor_daily"])
    me, mkt = pd.DataFrame(ops["me_events"]), pd.DataFrame(ops["marketing_spend"])
    for df, col in ((fnb, "date"), (labor, "date"), (mkt, "date")):
        if not df.empty:
            df["month"] = df[col].map(_month)
    if not me.empty:
        me = me[me["status"] == "definite"].copy()
        me["month"] = me["start_date"].map(_month)
        me["space_av"] = me["space_revenue"] + me["av_revenue"]
    if not fnb.empty:
        fnb["revenue"] = fnb["food_revenue"] + fnb["beverage_revenue"]
        fnb["cost"] = fnb["food_cost"] + fnb["beverage_cost"]

    key = ["hotel_code", "month"]
    rooms_rev = _sum(nights, key, "room_revenue")
    rooms_sold = nights.groupby(key).size().to_dict()
    commission = _sum(nights, key, "commission")
    fnb_rev, fnb_cost = _sum(fnb, key, "revenue"), _sum(fnb, key, "cost")
    banquet, me_rev = _sum(me, key, "fnb_revenue"), _sum(me, key, "space_av")
    lab = _sum(labor, key + ["department"], "labor_cost")
    spend = _sum(mkt, key, "spend")
    nights_past = nights[nights["stay_date"] < C.BUSINESS_DATE]
    to_date = _sum(nights_past, key, "room_revenue")
    fc = pd.DataFrame(ops["forecasts"])
    fc["month"] = fc["stay_date"].map(_month)
    ahead = _sum(fc, key, "room_revenue_p50")

    bd_month = _month(C.BUSINESS_DATE)
    months = sorted({_month(d) for d in world.dates})
    # a month has actuals only if the window covers all of it and it ended before the business date
    complete = [m for m in months if m >= world.start and m < bd_month]
    month_idx = {m: [i for i, d in enumerate(world.dates) if _month(d) == m] for m in months}
    rows, budgets = [], []

    for h, hotel in enumerate(world.hotels):
        def g(d, m, extra=None):
            return float(d.get((hotel.code, m) if extra is None else (hotel.code, m, extra), 0.0))

        def labour(m, *depts):
            return sum(g(lab, m, dep) for dep in depts)

        actual = {}
        for m in complete:
            rooms = g(rooms_rev, m)
            fnb_total = g(fnb_rev, m) + g(banquet, m)
            other = g(rooms_sold, m) * hotel.avg_check * 0.25  # parking, spa, laundry, minibar
            revenue = rooms + fnb_total + g(me_rev, m) + other
            rooms_exp = labour(m, "Front Office", "Housekeeping") + g(commission, m) + rooms * 0.08  # guest supplies, laundry, reservation systems
            fnb_exp = labour(m, "Kitchen", "F&B Service") + g(fnb_cost, m) + fnb_total * 0.10
            dept = revenue - rooms_exp - fnb_exp
            ag = labour(m, "Administration & General") + revenue * 0.05  # IT, insurance, card fees
            sm = labour(m, "Sales & Marketing") + g(spend, m) + revenue * 0.035  # brand and loyalty fees
            pom = labour(m, "Maintenance") + revenue * 0.035
            util = revenue * 0.04
            actual[m] = dict(ROOMS_REVENUE=rooms, FNB_REVENUE=fnb_total, ME_REVENUE=g(me_rev, m), OTHER_REVENUE=other,
                             TOTAL_REVENUE=revenue, ROOMS_EXPENSE=rooms_exp, FNB_EXPENSE=fnb_exp,
                             DEPARTMENTAL_PROFIT=dept, AG_EXPENSE=ag, SM_EXPENSE=sm, POM_EXPENSE=pom,
                             UTILITIES_EXPENSE=util, GOP=dept - ag - sm - pom - util)
        ratio = {k: float(np.mean([a[k] / a["ROOMS_REVENUE"] for a in actual.values() if a["ROOMS_REVENUE"]]))
                 for k in LINES} if actual else DEFAULT_RATIO

        for m in months:
            idx = month_idx[m]
            cap = hotel.rooms * len(idx)
            sold = hotel.rooms * np.minimum(world.target_occ[h, idx], 0.95) * 0.98
            budget_rooms = float((sold * world.base_price[h, idx]).sum() * C.ADR_TO_BAR * 0.97)
            budgets.append(dict(hotel_code=hotel.code, month=m, rooms_available=cap, rooms_sold=int(sold.sum()),
                                adr=round(budget_rooms / sold.sum(), 2), room_revenue=round(budget_rooms, 2),
                                currency=hotel.currency))
            scenarios = [("budget", {k: budget_rooms * ratio[k] * rng.normal(1, 0.015) for k in LINES})]
            if m in actual:
                scenarios.append(("actual", actual[m]))
            elif m >= bd_month:
                rooms = g(to_date, m) + g(ahead, m)
                scenarios.append(("forecast", {k: rooms * ratio[k] for k in LINES}))
            for scenario, values in scenarios:
                for line in LINES:
                    rows.append(dict(hotel_code=hotel.code, month=m, scenario=scenario, line=line,
                                     amount=round(values[line], 2), currency=hotel.currency))
    return dict(pnl_monthly=rows, budgets=budgets)
