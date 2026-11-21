"""Checks against the loaded database: the data is internally consistent, it looks like a real hotel group,
and every planted story can be recovered with plain SQL. This is also the answer key for evals.

    uv run python tests/check.py            # uses DATABASE_URL, or the local compass_hotels database
"""
import os
import subprocess
import sys

DB = os.environ.get("DATABASE_URL", "postgresql:///compass_hotels")
failures = []


def q(sql):
    out = subprocess.run(["psql", DB, "-AtF", "|", "-v", "ON_ERROR_STOP=1", "-c", f"set search_path = hotel; {sql}"],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(out.stderr)
    return [line.split("|") for line in out.stdout.strip().splitlines() if line and line != "SET"]


def one(sql):
    return float(q(sql)[0][0])


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


print("\nIntegrity")
for name, sql in {
    "no night is oversold": "select count(*) from v_hotel_day where rooms_sold > rooms_available",
    "no booking made after the business date": "select count(*) from reservations where created_at::date > business_date()",
    "cancellations happen between booking and arrival":
        "select count(*) from reservations where cancelled_at is not null and "
        "(cancelled_at < created_at or cancelled_at::date > arrival_date)",
    "cancelled and no-show reservations have no stay nights":
        "select count(*) from reservation_nights n join reservations r using (reservation_id) "
        "where r.status in ('cancelled', 'no_show')",
    "every night falls inside its reservation":
        "select count(*) from reservation_nights n join reservations r using (reservation_id) "
        "where n.stay_date < r.arrival_date or n.stay_date >= r.departure_date",
    "status agrees with the business date":
        "select count(*) from reservations where (status = 'checked_out' and departure_date > business_date()) "
        "or (status = 'confirmed' and arrival_date < business_date())",
    "no review before check-out":
        "select count(*) from reviews v join reservations r using (reservation_id) where v.review_date < r.departure_date",
    "P&L revenue lines add up":
        "select count(*) from (select hotel_code, month, scenario, "
        "sum(amount) filter (where line in ('ROOMS_REVENUE','FNB_REVENUE','ME_REVENUE','OTHER_REVENUE')) a, "
        "sum(amount) filter (where line = 'TOTAL_REVENUE') b from pnl_monthly where scenario = 'actual' "
        "group by 1, 2, 3) x where abs(a - b) > 1",
}.items():
    n = one(sql)
    check(name, n == 0, f"{n:.0f} rows")

print("\nRealism (last 12 months of actuals)")
rows = q("select hotel_code, avg(occupancy), avg(ari), avg(mpi) from v_comp_set_index "
         "where date >= business_date() - 365 group by 1 order by 1")
occ = {r[0]: float(r[1]) for r in rows}
ari = {r[0]: float(r[2]) for r in rows}
check("every hotel runs 55% to 92% occupancy", all(0.55 <= v <= 0.92 for v in occ.values()),
      f"{min(occ.values()):.0%} to {max(occ.values()):.0%}")
check("every hotel prices within 80-120 of its comp set (ARI)", all(80 <= v <= 120 for v in ari.values()),
      f"{min(ari.values()):.0f} to {max(ari.values()):.0f}")
cancel = one("select avg((status = 'cancelled')::int) from reservations where arrival_date < business_date()")
check("cancellation rate between 12% and 30%", 0.12 <= cancel <= 0.30, f"{cancel:.1%}")
gop = one("select sum(amount) filter (where line = 'GOP') / sum(amount) filter (where line = 'TOTAL_REVENUE') "
          "from pnl_monthly where scenario = 'actual'")
check("group GOP margin between 25% and 55%", 0.25 <= gop <= 0.55, f"{gop:.1%}")

print("\nS1 Lisbon: manual rate override slows pickup")
pick = dict((r[0], float(r[1])) for r in q("""
  with now_ as (select * from otb_as_of(business_date(), null, business_date(), business_date() + 44)),
  before as (select * from otb_as_of(business_date() - 21, null, business_date(), business_date() + 44)),
  nights as (select i.hotel_code, i.date, i.rooms_available from room_inventory_daily i
             where i.date between business_date() and business_date() + 44)
  select n.hotel_code, sum(coalesce(a.rooms_on_books, 0) - coalesce(b.rooms_on_books, 0))::numeric / sum(n.rooms_available)
  from nights n left join now_ a on a.hotel_code = n.hotel_code and a.stay_date = n.date
  left join before b on b.hotel_code = n.hotel_code and b.stay_date = n.date
  join hotels h on h.hotel_code = n.hotel_code where h.region = 'Europe' group by 1"""))
others = sorted(v for k, v in pick.items() if k != "LIS")
check("Lisbon 21-day pickup is under 70% of the European median", pick["LIS"] < 0.7 * others[len(others) // 2],
      f"LIS {pick['LIS']:.1%} vs median {others[len(others) // 2]:.1%}")
pos = one("select avg(bar_vs_comp) from v_rate_position where hotel_code = 'LIS' and stay_date < business_date() + 45")
check("Lisbon BAR sits over 25% above the comp set median", pos > 1.25, f"{pos:.2f}x")
check("the override is a manual change by rm.lisbon",
      one("select count(*) from rate_changes where hotel_code = 'LIS' and source = 'manual' and changed_by = 'rm.lisbon'") > 30)

print("\nS2 New York: biggest corporate account leaves, OTA fills the gap")
mix = {r[0]: (float(r[1]), float(r[2])) for r in q("""
  select case when stay_date < business_date() - 200 then 'before' else 'after' end,
         avg((r.segment = 'COR')::int), avg((r.channel in ('BDC', 'EXP'))::int)
  from reservation_nights n join reservations r using (reservation_id)
  where n.hotel_code = 'NYC' and stay_date between business_date() - 365 and business_date() - 1
    and not stay_date between business_date() - 200 and business_date() - 150 group by 1""")}
check("corporate share of room nights falls by over a quarter", mix["after"][0] < 0.75 * mix["before"][0],
      f"{mix['before'][0]:.1%} -> {mix['after'][0]:.1%}")
check("OTA share of room nights rises", mix["after"][1] > mix["before"][1] + 0.02,
      f"{mix['before'][1]:.1%} -> {mix['after'][1]:.1%}")
check("Vantor Consulting has no New York stays after it left", one("""
  select count(*) from reservations r join accounts a using (account_id)
  where a.name = 'Vantor Consulting' and r.hotel_code = 'NYC' and r.created_at::date >= business_date() - 180""") == 0)

print("\nS3 Bali: kitchen shortage hurts F&B and food scores")
staff = dict((r[0], float(r[1])) for r in q("""
  select (date between business_date() - 45 and business_date() - 10)::text, sum(actual_hours) / sum(required_hours)
  from labor_daily where hotel_code = 'DPS' and department = 'Kitchen' and date >= business_date() - 120 group by 1"""))
check("kitchen worked under 75% of required hours during the shortage", staff["true"] < 0.75,
      f"{staff['true']:.0%} vs {staff['false']:.0%} otherwise")
cap = dict((r[0], float(r[1])) for r in q("""
  select (f.date between business_date() - 45 and business_date() - 10)::text, sum(f.covers)::numeric / sum(d.rooms_sold)
  from fnb_daily f join outlets o using (outlet_id) join v_hotel_day d on d.hotel_code = f.hotel_code and d.date = f.date
  where f.hotel_code = 'DPS' and o.outlet_type in ('restaurant', 'in_room') and f.meal_period <> 'lunch'
    and f.date >= business_date() - 120 group by 1"""))
check("dinner and in-room covers per occupied room drop by over 25%", cap["true"] < 0.75 * cap["false"],
      f"{cap['false']:.2f} -> {cap['true']:.2f}")
food = dict((r[0], float(r[1])) for r in q("""
  select (r.arrival_date <= business_date() - 10 and r.departure_date >= business_date() - 45)::text, avg(v.food)
  from reviews v join reservations r using (reservation_id)
  where v.hotel_code = 'DPS' and r.arrival_date >= business_date() - 150 group by 1"""))
check("food score drops by over 1.5 points", food["true"] < food["false"] - 1.5,
      f"{food['false']:.1f} -> {food['true']:.1f}")

print("\nS4 Amsterdam: mobile checkout broken after a release")
conv = {(r[0], r[1]): float(r[2]) for r in q("""
  select device, (date >= business_date() - 30)::text, sum(bookings)::numeric / sum(sessions)
  from web_daily where hotel_code = 'AMS' and date >= business_date() - 90 group by 1, 2""")}
check("mobile conversion falls below 60% of its earlier level",
      conv[("mobile", "true")] < 0.6 * conv[("mobile", "false")],
      f"{conv[('mobile', 'false')]:.2%} -> {conv[('mobile', 'true')]:.2%}")
check("desktop conversion stays within 25%",
      abs(conv[("desktop", "true")] / conv[("desktop", "false")] - 1) < 0.25,
      f"{conv[('desktop', 'false')]:.2%} -> {conv[('desktop', 'true')]:.2%}")
bdc = dict((r[0], float(r[1])) for r in q("""
  select (created_at::date >= business_date() - 30)::text, avg((channel = 'BDC')::int)
  from reservations where hotel_code = 'AMS' and segment in ('RET', 'ADV', 'PKG')
    and created_at::date >= business_date() - 90 group by 1"""))
check("Booking.com share of new bookings rises", bdc["true"] > bdc["false"] + 0.04,
      f"{bdc['false']:.1%} -> {bdc['true']:.1%}")

print("\nS5 Barcelona: a floor out of order for renovation")
check("at least 24 rooms out of order every night of the works", one("""
  select min(out_of_order) from room_inventory_daily
  where hotel_code = 'BCN' and date between business_date() - 60 and business_date() + 30""") >= 24)
check("guests mention construction noise", one(
    "select count(*) from reviews where hotel_code = 'BCN' and negative_text ilike '%construction noise%'") >= 5)

print("\nS6 Dubai Business Bay: Gulf Tech Week missing from the pricing calendar")
dxb = dict((r[0], float(r[1])) for r in q("""
  select hotel_code, avg(bar_vs_comp) from v_rate_position
  where hotel_code in ('DXB1', 'DXB2') and stay_date between '2026-12-15' and '2026-12-19' group by 1"""))
check("Business Bay prices under 0.8x the comp set on event nights", dxb["DXB2"] < 0.8, f"{dxb['DXB2']:.2f}x")
check("its sister hotel Dubai Marina does not", dxb["DXB1"] > 0.95, f"{dxb['DXB1']:.2f}x")
otb = one("""select sum(rooms_on_books)::numeric / (5 * 300) from otb_as_of(business_date(), 'DXB2', '2026-12-15', '2026-12-19')
             where stay_date between '2026-12-15' and '2026-12-19'""")
check("Business Bay is already over 70% full for the event, 3+ weeks out", otb > 0.7, f"{otb:.0%}")

print("\nS7 Berlin: POS feed stale")
check("POS source is flagged stale", q("select status from data_sources where hotel_code = 'BER' and system = 'POS'")[0][0] == "stale")
check("no F&B rows for the last three days", one(
    "select count(*) from fnb_daily where hotel_code = 'BER' and date >= business_date() - 3") == 0)

print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
