"""Everything that follows from the guests in house: F&B (POS), meetings and
events, labour, the brand website and marketing, guest reviews, the forecast
and the data-source health page. Nothing here feeds back into the bookings.
"""
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd

from . import config as C
from .bookings import CURVE_DAYS

OUTLETS = {
    "luxury": [("Signature Restaurant", "restaurant"), ("Lobby Bar", "bar"), ("Breakfast Room", "breakfast"),
               ("In-Room Dining", "in_room")],
    "upscale": [("Brasserie", "restaurant"), ("Bar", "bar"), ("Breakfast Room", "breakfast")],
    "select service": [("Breakfast & Market", "breakfast"), ("Bar", "bar")],
    "resort": [("Restaurant", "restaurant"), ("Pool Bar", "bar"), ("Breakfast Terrace", "breakfast"),
               ("Beach Club", "beach"), ("In-Room Dining", "in_room")],
}
# outlet kind -> [(meal period, share of in-house guests, walk-ins per room, check vs dinner check, food share)]
PERIODS = {
    "breakfast": [("breakfast", None, 0.01, 0.38, 0.90)],
    "restaurant": [("lunch", 0.05, 0.06, 0.60, 0.75), ("dinner", 0.14, 0.08, 1.00, 0.68)],
    "bar": [("all_day", 0.22, 0.10, 0.42, 0.15)],
    "in_room": [("all_day", 0.05, 0.0, 0.85, 0.80)],
    "beach": [("lunch", 0.25, 0.03, 0.70, 0.60)],
}
DEPARTMENTS = {  # fixed hours per room in the hotel, and hours per unit of the driver
    "Front Office": (0.18, 0.15, "arrivals"),
    "Housekeeping": (0.05, 0.55, "occupied"),
    "Kitchen": (0.12, 0.22, "covers"),
    "F&B Service": (0.08, 0.28, "covers"),
    "Administration & General": (0.12, 0.0, None),
    "Sales & Marketing": (0.05, 0.0, None),
    "Maintenance": (0.07, 0.0, None),
}
DEPT_WAGE = {"Front Office": 1.0, "Housekeeping": 0.9, "Kitchen": 1.1, "F&B Service": 0.95,
             "Administration & General": 1.6, "Sales & Marketing": 1.5, "Maintenance": 1.1}
TIER_LABOUR = {"luxury": 1.35, "upscale": 1.0, "select service": 0.75, "resort": 1.15}
CPC_EUR = {"paid_search": 0.90, "metasearch": 1.40, "social": 0.50, "email": 0.05}

POSITIVE = {
    "staff": ["The team at reception went out of their way to help us.", "Friendly, warm staff throughout our stay.",
              "The concierge sorted out restaurant bookings for every night.", "Housekeeping remembered how we liked "
              "the room after the first day."],
    "cleanliness": ["Spotless room and bathroom.", "Everything was very clean.", "The room smelled fresh and the "
                    "linen was crisp.", "Public areas were kept immaculate all day."],
    "comfort": ["Very comfortable bed and a quiet room.", "Great sleep, the blackout curtains worked perfectly.",
                "Spacious room with a proper desk for working.", "The shower had great pressure and the room "
                "stayed cool."],
    "location": ["Perfect location, walking distance to everything.", "Great area with lots of places to eat.",
                 "Easy to reach from the airport and the station.", "Lovely views from the upper floors."],
    "value": ["Good value for the price.", "Worth every penny.", "Fair price for the quality, we will be back.",
              "The breakfast included made it great value."],
    "food": ["Breakfast was excellent with lots of fresh options.", "Dinner at the restaurant was a highlight.",
             "The bar made the best cocktails we had on the trip.", "Room service was quick and the food was hot."],
}
NEGATIVE = {
    "staff": ["Check-in took far too long.", "Staff seemed overwhelmed.", "Nobody answered the phone at reception.",
              "We had to ask three times for extra towels."],
    "cleanliness": ["The room was not properly cleaned on arrival.", "Dusty corners and a stained carpet.",
                    "Hair in the shower and the bin was not emptied.", "The carpet in the corridor looked tired."],
    "comfort": ["The room was noisy at night.", "The air conditioning was loud.", "The bed was too soft and the "
                "pillows were flat.", "The room was smaller than in the photos."],
    "location": ["The area is not great at night.", "Hard to find a taxi from the hotel.",
                 "Street noise until late in the evening."],
    "value": ["Too expensive for what you get.", "Pricier than similar hotels nearby.",
              "Extra charges for everything, even the gym.", "Breakfast was overpriced."],
    "food": ["Breakfast ran out of items and nothing was refilled.", "The food was average for the price.",
             "Limited choice for vegetarians.", "The coffee at breakfast was poor."],
}
STORY_NEGATIVE = {
    "S3": ("food", "The restaurant was clearly understaffed. Dinner took over an hour and room service never came."),
    "S5": ("comfort", "Construction noise from the floor below started early every morning."),
    "S1": ("value", "Noticeably more expensive than the hotels around it, and more than we paid last time."),
}


def _days(world, lo=None, hi=None):
    lo = 0 if lo is None else lo
    hi = world.n if hi is None else hi
    return [world.start + timedelta(days=i) for i in range(lo, hi)]


def build(world, comp_ref, tables, web_rows, rng):
    hotels, bd = world.hotels, world.bd
    res = pd.DataFrame(tables["reservations"])
    nights = pd.DataFrame(tables["reservation_nights"])
    stay = res.set_index("reservation_id")
    nights["breakfast"] = nights["reservation_id"].map(stay["breakfast_included"])

    by_day = nights.groupby(["hotel_code", "stay_date"]).agg(occupied=("reservation_id", "size"),
                                                           guests=("guests", "sum"))
    bb = nights[nights["breakfast"]].groupby(["hotel_code", "stay_date"])["guests"].sum()
    live = res[res["status"].isin(["checked_out", "in_house", "confirmed"])]
    arrivals = live.groupby(["hotel_code", "arrival_date"]).size()
    departures = live.groupby(["hotel_code", "departure_date"]).size()

    # plain dicts: far faster than MultiIndex lookups inside the day loops
    occupied_d, guests_d = by_day["occupied"].to_dict(), by_day["guests"].to_dict()
    rooms_rev_d = nights.groupby(["hotel_code", "stay_date"])["room_revenue"].sum().to_dict()
    bb_d, arr_d, dep_d = bb.to_dict(), arrivals.to_dict(), departures.to_dict()

    out = {k: [] for k in ("outlets", "fnb_daily", "labor_daily", "meeting_rooms", "me_events", "web_daily",
                           "marketing_spend", "reviews", "forecasts", "data_sources")}
    s3, s7 = C.STORIES["S3_DPS_KITCHEN_SHORTAGE"], C.STORIES["S7_BER_POS_FEED"]
    past = _days(world, 0, bd)

    covers_needed = {}
    for h, hotel in enumerate(hotels):
        tier = C.BRANDS[hotel.brand].tier
        for name, kind in OUTLETS[tier]:
            oid = len(out["outlets"]) + 1
            out["outlets"].append(dict(outlet_id=oid, hotel_code=hotel.code, name=name, outlet_type=kind))
            for d in past:
                occupied = occupied_d.get((hotel.code, d), 0)
                guests = guests_d.get((hotel.code, d), 0)
                bb_guests = bb_d.get((hotel.code, d), 0)
                weekend = d.weekday() >= 4
                shortage = hotel.code == s3["hotel"] and s3["start"] <= d <= s3["end"]
                for period, share, walkin, check_f, food in PERIODS[kind]:
                    if period == "breakfast":
                        in_house = bb_guests * 0.88 + (guests - bb_guests) * 0.18
                    else:
                        cap = 0.30 if tier == "resort" and period == "dinner" else (share or 0)
                        in_house = (occupied if kind == "in_room" else guests) * cap
                    walk = hotel.rooms * walkin * (0.25 if tier == "resort" else 1.0) * (1.2 if weekend else 1.0)
                    covers_needed[(hotel.code, d)] = covers_needed.get((hotel.code, d), 0) + in_house + walk
                    if shortage and kind in ("restaurant", "in_room"):
                        in_house *= 1 - s3["capture_drop"]
                        walk *= 1 - s3["capture_drop"]
                    if hotel.code == s7["hotel"] and d >= s7["stale_since"]:
                        continue  # the POS feed stopped: these rows never arrived
                    ih, wk = int(rng.poisson(in_house)), int(rng.poisson(walk))
                    if ih + wk == 0:
                        continue
                    revenue = (ih + wk) * hotel.avg_check * check_f * rng.normal(1, 0.06)
                    out["fnb_daily"].append(dict(
                        outlet_id=oid, hotel_code=hotel.code, date=d, meal_period=period, covers=ih + wk,
                        in_house_covers=ih, food_revenue=round(revenue * food, 2),
                        beverage_revenue=round(revenue * (1 - food), 2),
                        food_cost=round(revenue * food * rng.uniform(0.28, 0.33), 2),
                        beverage_cost=round(revenue * (1 - food) * rng.uniform(0.19, 0.24), 2),
                        currency=hotel.currency))

        # labour: required hours from the drivers, then what was scheduled and worked
        mult = TIER_LABOUR[tier]
        hotel_labour = []
        for d in past:
            drivers = dict(arrivals=arr_d.get((hotel.code, d), 0),
                           occupied=occupied_d.get((hotel.code, d), 0),
                           covers=covers_needed.get((hotel.code, d), 0))
            shortage = hotel.code == s3["hotel"] and s3["start"] <= d <= s3["end"]
            for dept, (fixed, per_unit, driver) in DEPARTMENTS.items():
                if dept == "Sales & Marketing" and d.weekday() >= 5:
                    continue
                required = (hotel.rooms * fixed + per_unit * (drivers[driver] if driver else 0)) * mult
                if dept == "Housekeeping":
                    required += 0.25 * dep_d.get((hotel.code, d), 0) * mult
                scheduled = required * rng.normal(1.0, 0.04)
                worked = scheduled * rng.normal(0.99, 0.03)
                if shortage and dept == "Kitchen":
                    worked = required * s3["staffing"] * rng.normal(1, 0.03)
                elif shortage and dept == "F&B Service":
                    worked = required * 0.86 * rng.normal(1, 0.03)
                overtime = max(worked - scheduled, 0) + max(0.0, rng.normal(0.02, 0.01)) * worked
                rel = DEPT_WAGE[dept]
                hotel_labour.append(dict(
                    hotel_code=hotel.code, date=d, department=dept, required_hours=round(required, 1),
                    scheduled_hours=round(scheduled, 1), actual_hours=round(worked, 1),
                    overtime_hours=round(overtime, 1), headcount=max(1, int(round(worked / 7.5))),
                    labor_cost=worked * rel + overtime * rel * 0.5, currency=hotel.currency))
        # Hourly cost is set so payroll lands on the region's typical share of revenue.
        revenue = sum(v for (code, d), v in rooms_rev_d.items() if code == hotel.code and d < C.BUSINESS_DATE) \
            + sum(r["food_revenue"] + r["beverage_revenue"] for r in out["fnb_daily"] if r["hotel_code"] == hotel.code)
        units = sum(r["labor_cost"] for r in hotel_labour) or 1
        wage = C.LABOUR_SHARE[hotel.region] * revenue / units * rng.normal(1, 0.04)
        for r in hotel_labour:
            r["labor_cost"] = round(r["labor_cost"] * wage, 2)
        out["labor_daily"] += hotel_labour

    _meetings(world, tables, out, rng)
    _web(world, res, web_rows, out, rng)
    _reviews(world, res, nights, comp_ref, out, rng)
    _forecast(world, tables, out, rng)

    for hotel in hotels:
        systems = [("PMS", hotel.pms), ("RMS", "Duetto" if hotel.region in ("Europe", "Asia") else "IDeaS"),
                   ("POS", hotel.pos), ("Rate shopper", "Lighthouse"), ("Comp set benchmark", "Benchmark feed"),
                   ("Web analytics", "GA4"), ("Finance", "Fairmas")]
        for system, vendor in systems:
            last = datetime.combine(C.BUSINESS_DATE, time(5, int(rng.integers(0, 50))))
            status = "ok"
            if hotel.code == s7["hotel"] and system == "POS":
                last, status = datetime.combine(s7["stale_since"], time(4, 12)), "stale"
            out["data_sources"].append(dict(hotel_code=hotel.code, system=system, vendor=vendor,
                                            connection="api" if hotel.pms != "Opera Cloud" or system != "PMS"
                                            else "ohip", last_sync_at=last, status=status))
    return out


def _meetings(world, tables, out, rng):
    events_by_hotel = {}
    for h, hotel in enumerate(world.hotels):
        if hotel.meeting_sqm == 0:
            continue
        rooms = [("Grand Ballroom", 0.45), ("Salon A", 0.2), ("Salon B", 0.2), ("Boardroom", 0.15)]
        ids = []
        for name, share in rooms:
            rid = len(out["meeting_rooms"]) + 1
            sqm = int(hotel.meeting_sqm * share)
            out["meeting_rooms"].append(dict(meeting_room_id=rid, hotel_code=hotel.code, name=name, sqm=sqm,
                                             capacity_theatre=int(sqm / 1.1)))
            ids.append((rid, sqm))
        events_by_hotel[hotel.code] = ids

    def add(hotel, rooms, name, etype, first, days, attendees, block_id, account_id, created):
        rid, sqm = max(rooms, key=lambda r: r[1]) if attendees > 80 else rooms[int(rng.integers(1, len(rooms)))]
        status = "definite" if created <= C.BUSINESS_DATE - timedelta(days=30) or first < C.BUSINESS_DATE \
            else str(rng.choice(["definite", "tentative"], p=[0.6, 0.4]))
        if rng.random() < 0.05:
            status = "cancelled"
        per_day = attendees * hotel.avg_check
        out["me_events"].append(dict(
            event_id=len(out["me_events"]) + 1, hotel_code=hotel.code, meeting_room_id=rid, name=name,
            event_type=etype, start_date=first, end_date=first + timedelta(days=days - 1), attendees=attendees,
            group_block_id=block_id, account_id=account_id, created_at=created, status=status,
            space_revenue=round(per_day * 0.6 * days, 2), fnb_revenue=round(per_day * 1.1 * days, 2),
            av_revenue=round(per_day * 0.15 * days, 2), currency=hotel.currency))

    hotel_by_code = {h.code: h for h in world.hotels}
    for g in tables["group_blocks"]:
        hotel = hotel_by_code[g["hotel_code"]]
        rooms = events_by_hotel.get(hotel.code)
        if rooms and g["group_type"] in ("Association congress", "Corporate offsite", "Incentive trip", "Wedding party") \
                and rng.random() < 0.7:
            etype = {"Association congress": "conference", "Corporate offsite": "meeting",
                     "Incentive trip": "gala dinner", "Wedding party": "wedding"}[g["group_type"]]
            add(hotel, rooms, g["name"], etype, g["arrival_date"], g["nights"], max(20, int(g["rooms_per_night"] * 1.7)),
                g["group_block_id"], g["account_id"], g["created_at"].date())
    for hotel in world.hotels:
        rooms = events_by_hotel.get(hotel.code)
        if not rooms:
            continue
        for d in _days(world):
            created = d - timedelta(days=int(rng.integers(10, 120)))
            if created > C.BUSINESS_DATE:
                continue
            if d.weekday() < 5 and rng.random() < 0.5:
                add(hotel, rooms, "Day meeting", "day meeting", d, 1, int(rng.integers(10, 80)), None, None, created)
            if d.weekday() == 5 and rng.random() < 0.15:
                add(hotel, rooms, "Wedding reception", "wedding", d, 1, int(rng.integers(60, 200)), None, None, created)


def _web(world, res, web_rows, out, rng):
    web = res[res["channel"] == "WEB"].copy()
    web["created_date"] = pd.to_datetime(web["created_at"]).dt.date
    revenue = web.groupby(["hotel_code", "created_date", "web_device", "web_source"])["total_room_revenue"].sum()
    for (h, d_idx, device, source), outcomes in sorted(web_rows.items()):
        hotel = world.hotels[h]
        d = world.start + timedelta(days=d_idx)
        attempts = sum(outcomes.values())
        sessions = int(attempts * (48 if device == "mobile" else 28) * rng.uniform(0.85, 1.15))
        out["web_daily"].append(dict(
            hotel_code=hotel.code, date=d, source=source, device=device, sessions=sessions,
            searches=int(attempts * rng.uniform(2.5, 3.5)),
            checkout_starts=outcomes.get("booked", 0) + outcomes.get("checkout_failed", 0),
            bookings=outcomes.get("booked", 0),
            booking_revenue=round(float(revenue.get((hotel.code, d, device, source), 0.0)), 2),
            currency=hotel.currency))
    spend = pd.DataFrame(out["web_daily"])
    if spend.empty:
        return
    clicks = spend[spend["source"].isin(C.PAID_SOURCES)].groupby(["hotel_code", "date", "source"])["sessions"].sum()
    fx = {h.code: C.FX_TO_EUR[h.currency] for h in world.hotels}
    cur = {h.code: h.currency for h in world.hotels}
    for (code, d, source), n_clicks in clicks.items():
        out["marketing_spend"].append(dict(hotel_code=code, date=d, source=source,
                                           spend=round(n_clicks * CPC_EUR[source] / fx[code] * rng.uniform(0.9, 1.1), 2),
                                           currency=cur[code]))


def _reviews(world, res, nights, comp_ref, out, rng):
    s1, s3, s5 = (C.STORIES[k] for k in ("S1_LIS_RATE_OVERRIDE", "S3_DPS_KITCHEN_SHORTAGE", "S5_BCN_RENOVATION"))
    occ = nights.groupby(["hotel_code", "stay_date"]).size().to_dict()
    hotel_by_code = {h.code: (i, h) for i, h in enumerate(world.hotels)}
    done = res[(res["status"] == "checked_out")]
    for r in done.itertuples():
        if rng.random() > 0.22:
            continue
        h, hotel = hotel_by_code[r.hotel_code]
        review_date = r.departure_date + timedelta(days=int(rng.integers(0, 10)))
        if review_date >= C.BUSINESS_DATE:
            continue
        base = C.BRANDS[hotel.brand].review_base
        busy = occ.get((r.hotel_code, r.arrival_date), 0) / hotel.rooms
        scores = {k: base + rng.normal(0, 0.9) for k in POSITIVE}
        scores["staff"] -= 2.5 * max(busy - 0.9, 0)
        scores["cleanliness"] -= 2.0 * max(busy - 0.92, 0)
        story = None
        if r.hotel_code == s3["hotel"] and r.arrival_date <= s3["end"] and r.departure_date >= s3["start"]:
            scores["food"] -= 2.6
            scores["staff"] -= 0.8
            story = "S3"
        if r.hotel_code == s5["hotel"] and r.arrival_date <= s5["end"] and r.departure_date >= s5["start"] \
                and rng.random() < 0.35:
            scores["comfort"] -= 3.0
            story = "S5"
        i = world.idx(r.arrival_date)
        if 0 <= i < world.n and r.avg_daily_rate > comp_ref[h, i] * 1.12:
            scores["value"] -= 1.6
            if r.hotel_code == s1["hotel"]:
                story = story or "S1"
        scores = {k: float(np.clip(v, 1, 10)) for k, v in scores.items()}
        overall = float(np.clip(np.mean(list(scores.values())) + rng.normal(0, 0.4), 1, 10))
        ranked = sorted(scores, key=scores.get)
        best, second, worst = ranked[-1], ranked[-2], ranked[0]
        negative = str(rng.choice(NEGATIVE[worst])) if scores[worst] < 7.5 else None
        if story:
            worst, negative = STORY_NEGATIVE[story]
        source = "Booking.com" if r.channel == "BDC" and rng.random() < 0.8 else \
            "Expedia" if r.channel == "EXP" and rng.random() < 0.7 else \
            str(rng.choice(["Google", "TripAdvisor", "Post-stay survey"], p=[0.5, 0.3, 0.2]))
        out["reviews"].append(dict(
            review_id=len(out["reviews"]) + 1, hotel_code=r.hotel_code, reservation_id=r.reservation_id,
            source=source, review_date=review_date, overall_score=round(overall, 1),
            staff=round(scores["staff"], 1), cleanliness=round(scores["cleanliness"], 1),
            comfort=round(scores["comfort"], 1), location=round(scores["location"], 1),
            value=round(scores["value"], 1), food=round(scores["food"], 1), language="en",
            positive_text=f"{rng.choice(POSITIVE[best])} {rng.choice(POSITIVE[second])}",
            negative_text=negative,
            topics=",".join(sorted({best, second} | ({worst} if negative else set())))))


def _forecast(world, tables, out, rng):
    nights = pd.DataFrame(tables["reservation_nights"])
    otb = nights.groupby(["hotel_code", "stay_date"]).agg(rooms=("reservation_id", "size"),
                                                        revenue=("room_revenue", "sum"))
    inv = pd.DataFrame(tables["room_inventory_daily"]).set_index(["hotel_code", "date"])["rooms_available"].to_dict()
    rates = pd.DataFrame(tables["rates_daily"]).set_index(["hotel_code", "stay_date"])["bar_rate"].to_dict()
    otb_rooms, otb_rev = otb["rooms"].to_dict(), otb["revenue"].to_dict()
    for h, hotel in enumerate(world.hotels):
        for i in range(world.bd, world.n):
            d = world.start + timedelta(days=i)
            cap = int(inv[(hotel.code, d)])
            key = (hotel.code, d)
            on_books = int(otb_rooms.get(key, 0))
            lead = i - world.bd
            final = min(world.target_occ[h, i], 0.97) * cap
            p50 = min(cap, max(on_books, on_books + final * (1 - np.exp(-lead / CURVE_DAYS)) * rng.normal(1, 0.03)))
            spread = 0.04 + lead / 500
            adr = (otb_rev.get(key, 0) / on_books) if on_books else float(rates[key]) * 0.9
            out["forecasts"].append(dict(
                hotel_code=hotel.code, stay_date=d, forecast_date=C.BUSINESS_DATE, rooms_available=cap,
                rooms_on_books=on_books, rooms_p10=int(max(on_books, p50 * (1 - spread))), rooms_p50=int(round(p50)),
                rooms_p90=int(min(cap, p50 * (1 + spread))), adr_p50=round(float(adr), 2),
                room_revenue_p50=round(float(adr * p50), 2), currency=hotel.currency))
