"""The core: every reservation, simulated in the order it was made.

Each day of the simulation:
  1. cancellations due that day give their rooms back;
  2. the revenue system re-prices future nights from pickup vs the expected booking curve;
  3. the booking requests made that day arrive. A guest who is not on a negotiated rate compares the
     price with the market and may walk away. A request is accepted only if its room type, or a higher
     one as a free upgrade, is free on every night of the stay.

Because every reservation keeps created_at and cancelled_at, the on-the-books position for any past date
can be rebuilt with plain SQL. That is where pace, pickup and STLY come from; nothing is stored twice.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import numpy as np

from . import config as C

ELASTICITY = 3.0  # how fast price-sensitive demand falls once BAR is above the comp set median
CURVE_DAYS = 32.0  # the expected booking curve: share on the books at lead L is exp(-L / CURVE_DAYS)
RMS_HORIZON = 180
PAD = 20  # stay nights past the end of the window

FIRST = ["Anna", "Liam", "Sofia", "Noah", "Mia", "Lucas", "Emma", "Mateo", "Olivia", "Yuki", "Aisha", "Omar",
         "Chen", "Priya", "Lars", "Elena", "Diego", "Hana", "Ines", "Tom", "Fatima", "Jonas", "Camila", "Ravi"]
LAST = ["Smith", "Jansen", "Garcia", "Muller", "Rossi", "Silva", "Tanaka", "Haddad", "Novak", "Kim", "Dubois",
        "Costa", "Schmidt", "Lopez", "Ivanova", "Okafor", "Nielsen", "Santos", "Khan", "Wright", "Moreau", "Sato"]
SOURCE_MARKETS = {
    "Europe": ["GB", "DE", "FR", "US", "NL", "IT", "ES", "CH", "SE", "BE"],
    "North America": ["US", "CA", "GB", "MX", "DE", "BR", "FR", "JP", "AU", "IN"],
    "Middle East": ["SA", "GB", "IN", "DE", "RU", "US", "FR", "EG", "CN", "KW"],
    "South America": ["BR", "AR", "US", "CL", "UY", "ES", "CO", "FR", "DE", "MX"],
    "Asia": ["CN", "AU", "US", "GB", "IN", "KR", "JP", "SG", "DE", "MY"],
}
GROUP_ORGS = [  # organiser, group type
    ("Iberian Cardiology Society", "Association congress"), ("Nordic Data Alliance", "Association congress"),
    ("Andes Mining Forum", "Association congress"), ("Halvorsen & Lie", "Corporate offsite"),
    ("Orion Robotics", "Corporate offsite"), ("Silverline Insurance", "Incentive trip"),
    ("Kito Motors Dealers", "Incentive trip"), ("Pacific Rim Rugby XV", "Sports team"),
    ("Marlowe-Ito wedding", "Wedding party"), ("Delta Choir Festival", "Tour group"),
    ("Brightwave Media", "Corporate offsite"), ("Old Town Heritage Tours", "Tour group"),
]


def _nice(x, base_adr):
    step = 10 ** (np.floor(np.log10(base_adr)) - 1) / 2
    return np.round(x / step) * step


def simulate(world, comp_ref, rng):
    H, n, bd = len(world.hotels), world.n, world.bd
    N = n + PAD
    seg_codes = list(C.SEGMENTS)
    rt_factor = np.array([r[3] for r in C.ROOM_TYPES])
    start_dow = world.start.weekday()

    # ---------------------------------------------------------- inventory
    rt_count = np.zeros((H, 4), int)
    for h, hotel in enumerate(world.hotels):
        c = np.round(np.array([r[2] for r in C.ROOM_TYPES]) * hotel.rooms).astype(int)
        c[0] += hotel.rooms - c.sum()
        rt_count[h] = c
    ooo = np.zeros((H, 4, N), int)
    ooo[:, 0] = rng.poisson(np.array([h.rooms for h in world.hotels])[:, None] * 0.006, (H, N))
    s5 = C.STORIES["S5_BCN_RENOVATION"]
    h5 = [h.code for h in world.hotels].index(s5["hotel"])
    a, b = max(world.idx(s5["start"]), 0), min(world.idx(s5["end"]), N - 1)
    if a <= b:
        ooo[h5, 0, a:b + 1] += s5["rooms_out"]
    cap = rt_count[:, :, None] - ooo
    occ = np.zeros((H, 4, N), int)

    # ------------------------------------------------------------- prices
    base = np.concatenate([world.base_price, np.repeat(world.base_price[:, -1:], PAD, 1)], 1)
    ref = np.concatenate([comp_ref, np.repeat(comp_ref[:, -1:], PAD, 1)], 1)
    adr0 = np.array([h.base_adr for h in world.hotels])
    bar = np.stack([_nice(base[h], adr0[h]) for h in range(H)])
    locked = np.zeros((H, N), bool)
    target = np.concatenate([world.target_occ, np.repeat(world.target_occ[:, -1:], PAD, 1)], 1)
    rate_changes = []

    # ----------------------------------------------------------- accounts
    accounts = []
    for name, _ in C.CORPORATE_ACCOUNTS:
        accounts.append(dict(account_id=len(accounts) + 1, name=name, account_type="corporate"))
    for name, _ in C.WHOLESALERS:
        accounts.append(dict(account_id=len(accounts) + 1, name=name, account_type="wholesaler"))
    corp_ids = np.arange(1, len(C.CORPORATE_ACCOUNTS) + 1)
    corp_w = np.array([w for _, w in C.CORPORATE_ACCOUNTS])
    whs_ids = np.arange(len(C.CORPORATE_ACCOUNTS) + 1, len(accounts) + 1)
    whs_w = np.array([w for _, w in C.WHOLESALERS])
    vantor = 1 + [nm for nm, _ in C.CORPORATE_ACCOUNTS].index(C.STORIES["S2_NYC_CORPORATE_LOSS"]["account"])

    # ------------------------------------------------------------ requests
    cols = defaultdict(list)
    blocks = []
    org_account = {}

    def add(h, s, created, seg, los, rt, ch, acct, block, fixed_rate, device, source):
        k = len(s)
        for name, v in (("h", np.full(k, h)), ("s", s), ("created", created), ("seg", seg), ("los", los),
                        ("rt", rt), ("ch", ch), ("acct", acct), ("block", block), ("fixed", fixed_rate),
                        ("device", device), ("source", source)):
            cols[name].append(np.asarray(v))

    web_sources = list(C.WEB_SOURCES)
    web_w = np.array(list(C.WEB_SOURCES.values()))
    for h, hotel in enumerate(world.hotels):
        mix = C.SEGMENT_MIX[hotel.profile]
        trans = [k for k in mix if k != "GRP"]
        arr_w = np.array([mix[k] / C.SEGMENTS[k].los_mean for k in trans])
        avg_los = sum(mix[k] for k in trans) / arr_w.sum()
        arr_w /= arr_w.sum()
        lam = hotel.rooms * world.target_occ[h] * (1 - mix["GRP"]) / avg_los * 1.42  # grossed up for cancellations
        counts = rng.poisson(lam * rng.gamma(30, 1 / 30, n))
        s = np.repeat(np.arange(n), counts)
        k = len(s)
        seg = rng.choice([seg_codes.index(c) for c in trans], k, p=arr_w)
        lead_mean = np.array([C.SEGMENTS[c].lead_mean for c in seg_codes])[seg]
        lead = np.clip(rng.gamma(1.3, lead_mean / 1.3), 0, 330).astype(int)
        los_mean = np.array([C.SEGMENTS[c].los_mean for c in seg_codes])[seg]
        los = np.clip(rng.poisson(los_mean - 1) + 1, 1, 14)
        rt = rng.choice(4, k, p=[r[2] for r in C.ROOM_TYPES])
        ch = np.empty(k, object)
        acct = np.zeros(k, int)
        for si, code in enumerate(seg_codes):
            m = seg == si
            if m.any():
                chans = C.SEGMENTS[code].channels
                ch[m] = rng.choice(list(chans), m.sum(), p=list(chans.values()))
        is_cor, is_whl = seg == seg_codes.index("COR"), seg == seg_codes.index("WHL")
        acct[is_cor] = rng.choice(corp_ids, is_cor.sum(), p=corp_w / corp_w.sum())
        acct[is_whl] = rng.choice(whs_ids, is_whl.sum(), p=whs_w / whs_w.sum())
        created = s - lead
        keep = created <= bd
        if hotel.code == C.STORIES["S2_NYC_CORPORATE_LOSS"]["hotel"]:
            keep &= ~((acct == vantor) & (created >= world.idx(C.STORIES["S2_NYC_CORPORATE_LOSS"]["lost_from"])))
        device = np.where(rng.random(k) < 0.58, "mobile", "desktop")
        source = rng.choice(web_sources, k, p=web_w)
        add(h, s[keep], created[keep], seg[keep], los[keep], rt[keep], ch[keep], acct[keep],
            np.zeros(keep.sum(), int), np.zeros(keep.sum()), device[keep], source[keep])

        # group blocks: contracted up front, picked up by individual reservations until the cutoff
        grp_rn = (hotel.rooms * np.minimum(world.target_occ[h], 0.95) * mix["GRP"]).sum()
        for _ in range(rng.poisson(grp_rn / 36)):
            arr = int(rng.choice(n, p=world.target_occ[h] / world.target_occ[h].sum()))
            nights = int(rng.integers(2, 5))
            per_night = int(np.clip(rng.lognormal(np.log(16), 0.45), 6, hotel.rooms * 0.25))
            b_created = arr - int(rng.uniform(45, 240))
            if b_created > bd:
                continue
            cutoff = arr - 21
            org, kind = GROUP_ORGS[int(rng.integers(len(GROUP_ORGS)))]
            if org not in org_account:  # one account per organiser, reused across blocks and hotels
                accounts.append(dict(account_id=len(accounts) + 1, name=org, account_type="group"))
                org_account[org] = len(accounts)
            rate = float(_nice(base[h, arr] * 0.82, adr0[h]))
            block_id = len(blocks) + 1
            blocks.append(dict(group_block_id=block_id, hotel_code=hotel.code, account_id=org_account[org],
                               name=f"{org} - {kind}", group_type=str(kind), created_idx=b_created,
                               arrival_idx=arr, nights=nights, rooms_per_night=per_night, cutoff_idx=cutoff,
                               group_rate=rate, currency=hotel.currency))
            pick = int(round(per_night * rng.uniform(0.55, 1.0)))
            g_created = rng.integers(b_created + 3, max(cutoff, b_created + 4), pick)
            ok = g_created <= bd
            g = ok.sum()
            add(h, np.full(g, arr), g_created[ok], np.full(g, seg_codes.index("GRP")), np.full(g, nights),
                np.zeros(g, int), np.full(g, "GRPDESK", object), np.full(g, org_account[org]), np.full(g, block_id),
                np.full(g, rate), np.full(g, "", object), np.full(g, "", object))

    R = {k: np.concatenate(v) for k, v in cols.items()}
    order = np.argsort(R["created"], kind="stable")
    R = {k: v[order] for k, v in R.items()}
    total = len(R["s"])
    u_price, u_cancel, u_when, u_noshow = (rng.random(total) for _ in range(4))
    u_web = rng.random(total)

    # --------------------------------------------------------- simulation
    s1, s4 = C.STORIES["S1_LIS_RATE_OVERRIDE"], C.STORIES["S4_AMS_MOBILE_CHECKOUT"]
    h1 = [h.code for h in world.hotels].index(s1["hotel"])
    h4 = [h.code for h in world.hotels].index(s4["hotel"])
    s1_day, s4_day = world.idx(s1["changed_on"]), world.idx(s4["start"])
    releases = defaultdict(list)
    res = defaultdict(list)
    lost = defaultdict(lambda: [0, 0])
    web = defaultdict(int)
    first_day = int(R["created"][0]) if total else bd
    ptr = 0
    for d in range(first_day, bd + 1):
        for i_res in releases.pop(d, []):
            h_, rt_, s_, los_ = res["h"][i_res], res["rt_assigned"][i_res], res["s"][i_res], res["los"][i_res]
            occ[h_, rt_, s_:s_ + los_] -= 1
        # revenue system: daily for the next 30 nights, weekly (Mondays) beyond
        lo, hi = max(d, 0), min(d + RMS_HORIZON, N - 1)
        if lo <= hi:
            L = np.arange(lo, hi + 1) - d
            due = (L <= 30) | ((start_dow + d) % 7 == 0)
            for h in range(H):
                otb = occ[h, :, lo:hi + 1].sum(0)
                cap_h = cap[h, :, lo:hi + 1].sum(0)
                exp_otb = np.minimum(target[h, lo:hi + 1], 0.97) * cap_h * np.exp(-L / CURVE_DAYS)
                ratio = (otb + 3) / (exp_otb + 3)
                mult = np.clip(1 + 0.45 * (ratio - 1), 0.85, 1.35) * np.where(otb >= 0.95 * cap_h, 1.12, 1.0)
                cur = bar[h, lo:hi + 1]
                # move towards the target in steps of at most 10%, as a revenue system would
                new = _nice(np.clip(base[h, lo:hi + 1] * mult, cur * 0.9, cur * 1.1), adr0[h])
                upd = due & (np.abs(new / cur - 1) >= 0.03) & ~locked[h, lo:hi + 1]
                for j in np.flatnonzero(upd):
                    rate_changes.append((h, lo + j, d, float(cur[j]), float(new[j]), "rms", "auto"))
                bar[h, lo:hi + 1] = np.where(upd, new, cur)
        if d == s1_day:
            a1, b1 = world.idx(s1["stay_from"]), world.idx(s1["stay_to"])
            for j in range(max(a1, 0), min(b1, N - 1) + 1):
                new = float(_nice(bar[h1, j] * s1["uplift"], adr0[h1]))
                rate_changes.append((h1, j, d, float(bar[h1, j]), new, "manual", s1["user"]))
                bar[h1, j] = new
                locked[h1, j] = True

        while ptr < total and R["created"][ptr] == d:
            i = ptr
            ptr += 1
            h, s, los, rt = int(R["h"][i]), int(R["s"][i]), int(R["los"][i]), int(R["rt"][i])
            seg = C.SEGMENTS[seg_codes[R["seg"][i]]]
            ch = R["ch"][i]
            los = min(los, N - s)
            is_web = ch == "WEB"
            key_web = (h, d, R["device"][i], R["source"][i])
            if not seg.contracted:
                ratio = bar[h, s] / ref[h, s]
                if ratio > 1 and u_price[i] > np.exp(-ELASTICITY * (ratio - 1)):
                    lost[(h, d, s, seg.code, ch, "price")][0] += 1
                    lost[(h, d, s, seg.code, ch, "price")][1] += los
                    if is_web:
                        web[key_web + ("priced_out",)] += 1
                    continue
            if is_web and h == h4 and d >= s4_day and R["device"][i] == "mobile" and u_web[i] < s4["mobile_fail"]:
                web[key_web + ("checkout_failed",)] += 1
                if u_web[i] < s4["mobile_fail"] * s4["switch_to_ota"]:
                    ch, is_web = "BDC", False
                else:
                    continue
            got = -1
            for r2 in range(rt, 4):
                if (cap[h, r2, s:s + los] - occ[h, r2, s:s + los]).min() > 0:
                    got = r2
                    break
            if got < 0:
                lost[(h, d, s, seg.code, ch, "no_availability")][0] += 1
                lost[(h, d, s, seg.code, ch, "no_availability")][1] += los
                if is_web:
                    web[key_web + ("no_availability",)] += 1
                continue
            occ[h, got, s:s + los] += 1
            if is_web:
                web[key_web + ("booked",)] += 1
            if R["fixed"][i] > 0:
                nightly = np.full(los, R["fixed"][i])
            else:
                nightly = np.round(bar[h, s:s + los] * seg.rate_factor * rt_factor[rt], 2)
            lead = s - d
            p_cancel = min(seg.cancel_p * (0.6 + 0.4 * min(lead / max(seg.lead_mean, 1), 2.5)), 0.6)
            cancel_day = None
            if u_cancel[i] < p_cancel:
                cancel_day = d + int(u_when[i] ** 1.4 * max(s - d, 0))
                if cancel_day <= bd:
                    releases[cancel_day].append(len(res["h"]))
                else:
                    cancel_day = None  # that cancellation has not happened yet
            for name, v in (("h", h), ("s", s), ("los", los), ("rt", rt), ("rt_assigned", got),
                            ("seg", seg.code), ("ch", ch), ("acct", int(R["acct"][i])),
                            ("block", int(R["block"][i])), ("created", d), ("cancel", cancel_day),
                            ("nightly", nightly), ("device", R["device"][i] if is_web else None),
                            ("source", R["source"][i] if is_web else None), ("u_noshow", u_noshow[i])):
                res[name].append(v)

    return _tables(world, rng, res, rate_changes, lost, web, bar, cap, ooo, rt_count, accounts, blocks)


def _ts(world, idx, rng, hour_lo=7, hour_hi=23):
    d = world.start + timedelta(days=int(idx))
    return datetime.combine(d, time(int(rng.integers(hour_lo, hour_hi)), int(rng.integers(0, 60)), int(rng.integers(0, 60))))


def _tables(world, rng, res, rate_changes, lost, web, bar, cap, ooo, rt_count, accounts, blocks):
    bd, D = world.bd, (lambda i: world.start + timedelta(days=int(i)))
    hotels = world.hotels
    reservations, nights, guests = [], [], []
    guest_pool = defaultdict(list)
    repeat_p = {"RET": 0.12, "ADV": 0.10, "COR": 0.45, "GRP": 0.03, "WHL": 0.05, "PKG": 0.15}
    rt_codes = [r[0] for r in C.ROOM_TYPES]
    for i in range(len(res["h"])):
        h, s, los = res["h"][i], res["s"][i], res["los"][i]
        hotel, seg = hotels[h], res["seg"][i]
        cancelled = res["cancel"][i] is not None
        noshow_p = 0.025 if seg in ("RET", "COR") else 0.01
        if cancelled:
            status = "cancelled"
        elif s < bd and res["u_noshow"][i] < noshow_p:
            status = "no_show"
        elif s + los <= bd:
            status = "checked_out"
        elif s < bd:
            status = "in_house"
        else:
            status = "confirmed"
        pool = guest_pool[h]
        if pool and rng.random() < repeat_p[seg]:
            gid = pool[int(rng.integers(len(pool)))]
        else:
            gid = len(guests) + 1
            home = rng.random() < 0.3
            country = hotel.country if home else str(rng.choice(SOURCE_MARKETS[hotel.region]))
            guests.append(dict(guest_id=gid, first_name=str(rng.choice(FIRST)), last_name=str(rng.choice(LAST)),
                               country=country, loyalty_tier=str(rng.choice(["none", "silver", "gold", "platinum"],
                                                                             p=[0.62, 0.22, 0.12, 0.04]))))
            pool.append(gid)
        nightly = res["nightly"][i]
        rid = i + 1
        created_ts = _ts(world, res["created"][i], rng)
        cancelled_ts = None
        if cancelled:  # same-day cancellations come after the booking, never before
            cancelled_ts = _ts(world, res["cancel"][i], rng)
            if cancelled_ts <= created_ts:
                end_of_day = datetime.combine(created_ts.date(), time(23, 59, 59))
                cancelled_ts = min(created_ts + timedelta(minutes=int(rng.integers(5, 240))), end_of_day)
        adults = 1 if seg == "COR" else int(rng.choice([1, 2, 2, 2, 3]))
        children = int(rng.choice([0, 0, 0, 1, 2])) if hotel.profile == "resort" and seg != "COR" else 0
        breakfast = seg == "PKG" or rng.random() < C.SEGMENTS[seg].breakfast_p
        reservations.append(dict(
            reservation_id=rid, confirmation_no=f"{hotel.code}-{rid:07d}", hotel_code=hotel.code, guest_id=gid,
            account_id=res["acct"][i] or None, group_block_id=res["block"][i] or None,
            created_at=created_ts, arrival_date=D(s), departure_date=D(s + los), nights=los,
            room_type_booked=rt_codes[res["rt"][i]], room_type_assigned=rt_codes[res["rt_assigned"][i]],
            rate_plan=C.SEGMENTS[seg].rate_plan, segment=seg, channel=res["ch"][i],
            web_source=res["source"][i], web_device=res["device"][i], adults=adults, children=children,
            breakfast_included=bool(breakfast), status=status,
            cancelled_at=cancelled_ts,
            currency=hotel.currency, avg_daily_rate=round(float(nightly.mean()), 2),
            total_room_revenue=round(float(nightly.sum()), 2),
        ))
        if status in ("checked_out", "in_house", "confirmed"):
            for k in range(los):
                if s + k < world.n:
                    nights.append(dict(reservation_id=rid, hotel_code=hotel.code, stay_date=D(s + k),
                                       room_type=rt_codes[res["rt_assigned"][i]], room_revenue=float(nightly[k]),
                                       guests=adults + children))
    for g in blocks:
        g["created_at"] = _ts(world, g.pop("created_idx"), rng)
        g["arrival_date"] = D(g.pop("arrival_idx"))
        g["departure_date"] = g["arrival_date"] + timedelta(days=g["nights"])
        g["cutoff_date"] = D(g.pop("cutoff_idx"))
    picked = defaultdict(int)
    for r in reservations:
        if r["group_block_id"] and r["status"] != "cancelled":
            picked[r["group_block_id"]] += 1
    for g in blocks:
        g["rooms_picked_up"] = picked[g["group_block_id"]]

    inv = []
    for h, hotel in enumerate(hotels):
        for i in range(world.n):
            inv.append(dict(hotel_code=hotel.code, date=D(i), physical_rooms=hotel.rooms,
                            out_of_order=int(ooo[h, :, i].sum()), rooms_available=int(cap[h, :, i].sum())))
    rates_daily = [dict(hotel_code=hotel.code, stay_date=D(i), bar_rate=float(bar[h, i]), currency=hotel.currency)
                   for h, hotel in enumerate(hotels) for i in range(world.n)]
    # the revenue system runs overnight; people change rates during office hours
    changes = [dict(hotel_code=hotels[h].code, stay_date=D(s),
                    changed_at=_ts(world, d, rng, *((3, 6) if src == "rms" else (9, 18))),
                    old_rate=o, new_rate=nw, source=src, changed_by=who)
               for h, s, d, o, nw, src, who in rate_changes if s < world.n]
    lost_rows = [dict(hotel_code=hotels[h].code, request_date=D(d), arrival_date=D(s), segment=seg, channel=ch,
                      reason=why, requests=v[0], room_nights=v[1])
                 for (h, d, s, seg, ch, why), v in lost.items() if d >= 0 and s < world.n]
    web_rows = defaultdict(lambda: defaultdict(int))
    for (h, d, device, source, outcome), v in web.items():
        if d >= 0:
            web_rows[(h, d, device, source)][outcome] += v
    room_types = [dict(hotel_code=hotel.code, room_type=rt, name=nm, rooms=int(rt_count[h, k]), rate_factor=f)
                  for h, hotel in enumerate(hotels) for k, (rt, nm, _, f) in enumerate(C.ROOM_TYPES)]
    return dict(reservations=reservations, reservation_nights=nights, guests=guests, accounts=accounts,
                group_blocks=blocks, room_inventory_daily=inv, rates_daily=rates_daily, rate_changes=changes,
                lost_business=lost_rows, room_types=room_types), web_rows
