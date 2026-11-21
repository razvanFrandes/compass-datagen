# compass-datagen

Synthetic data for a fictional hotel group, **Halcyon Hospitality Group**: 20 hotels in 20 cities and 5 regions, under four brands (Kestrel, Arbor, Tessera, Lumen). It covers the systems a hotel analytics platform connects to: PMS, RMS, rate shopper, comp set benchmark, POS, M&E, labour, web analytics, reviews and finance. Everything is loaded into one Postgres database.

Everything is fictional: hotels, companies, competitors and city events.

```bash
uv sync
uv run python -m datagen --preview   # ~10 reservations per hotel plus everything attached -> out/preview (seconds)
uv run python -m datagen             # 2025-01-01 to 2027-05-31, ~1.2M reservations -> out/full (~2 minutes)
db/load.sh                           # creates the compass_hotels database, schema hotel, loads out/full (~1 minute)
uv run python tests/check.py         # integrity, realism and the planted stories
```

`db/load.sh` uses `DATABASE_URL` when it is set, for Neon, Supabase or any other Postgres server.

The business date is **2026-11-20**. Stays before it are actuals. Stays after it are on the books, and bookings that would be made after it do not exist yet.

## What is in the database

| Area | Tables |
|---|---|
| Reference | `hotels`, `brands`, `room_types`, `segments`, `channels` (commission %), `accounts`, `fx_rates`, `holidays`, `city_events`, `weather_daily`, `settings` |
| PMS | `reservations` (created_at, cancelled_at, status, segment, channel, rate plan, room type booked and assigned), `reservation_nights`, `guests`, `group_blocks`, `room_inventory_daily` (out-of-order rooms) |
| RMS | `rates_daily` (BAR), `rate_changes` (every change, automatic or manual), `forecasts` (P10/P50/P90), `budgets`, `lost_business` (turned away for price or no availability) |
| Market | `competitors`, `comp_rates` (rate shops by shop date), `comp_set_daily` (benchmark feed) |
| Operations | `outlets`, `fnb_daily`, `meeting_rooms`, `me_events`, `labor_daily` (required, scheduled and worked hours), `web_daily` (sessions to bookings, by source and device), `marketing_spend`, `reviews` (scores and text) |
| Finance | `pnl_monthly` (USALI lines: actual, budget, forecast) |
| Data health | `data_sources` (last sync and status per system) |
| RAG (with pgvector) | `review_embeddings`, `documents`, `document_chunks` |

**Helpers** (the definitions live in SQL, not in the app):

- `v_hotel_day`: occupancy, ADR and RevPAR per hotel and day, in local currency and EUR.
- `v_comp_set_index`: MPI, ARI and RGI.
- `v_channel_month`: gross revenue, commission and net revenue by channel.
- `v_rate_position`: BAR against the comp set median.
- `otb_as_of(date)`: on-the-books position as of any past day.
- `pace_vs_stly()`: OTB against the same time last year.
- `eur_rate()`: currency conversion.
- `business_date()`: the business date.

Typical sizes of the full run:

| Table | Rows |
|---|---|
| `reservations` | 1.2M |
| `reservation_nights` | 2.4M |
| `reviews` | 204k |
| `rate_changes` | 225k |
| `comp_rates` | 117k |
| `labor_daily` | 92k |

## How it works

The architecture follows [Isla Velaluz](https://github.com/chadwambles/isla-velaluz) (MIT): one config file, a world built first, a core simulation, then the areas that follow from it. The booking model is new.

| File | What it builds |
|---|---|
| `config.py` | hotels, segments, channels, events, regional labour shares, and the planted stories with the size of each effect |
| `world.py` | calendar, seasonality (northern and southern hemisphere), city events, holidays, weather, FX |
| `market.py` | comp set, competitor rate shops, comp set performance |
| `bookings.py` | **the core**, described below |
| `ops.py` | F&B (POS), M&E, labour, web analytics, marketing spend, reviews, forecast, data-source health |
| `finance.py` | monthly USALI-style P&L (actual, budget, forecast) and room budgets |

The core simulates day by day, in the order bookings were made:

- Cancellations release their rooms.
- An overnight revenue system reprices future nights from pickup against the booking curve, in steps of at most 10%.
- Guests on public rates compare BAR with the comp set median and may walk away.
- Capacity is checked by room type on every night of the stay, with free upgrades when the booked type is full.

Each reservation keeps `created_at` and `cancelled_at`, so the on-the-books position on any past day comes from plain SQL. Pace, pickup and STLY come from that, with no stored snapshots.

Calibration from the last 12 months of actuals:

- occupancy 63–79%;
- ARI 92–110;
- cancellations 18%, no-shows ~2%;
- GOP margin 31–44%;
- payroll set to regional benchmark shares (Europe 33%, North America 35%, Middle East 24%, South America 28%, Asia 27%).

Every random mechanism has its own seed stream, so a change to one does not reshuffle the others.

## Planted stories

The full definitions are in `STORIES` in `datagen/config.py`. `tests/check.py` recovers each story with SQL and doubles as the answer key for evals.

| # | Hotel | What happened | What the data shows |
|---|---|---|---|
| S1 | Lisbon | manual BAR override of +22% for 45 nights | 21-day pickup 11% vs 18% for European peers, pace -20% vs STLY |
| S2 | New York | biggest corporate account left | corporate share 30% → 21%, OTA share up, lower net ADR |
| S3 | Bali | kitchen at 68% of required hours for 5 weeks | dinner covers per occupied room -40%, food score 8.6 → 6.0, review text |
| S4 | Amsterdam | booking engine release broke mobile checkout | mobile conversion 1.8% → 0.8%, Booking.com share 39% → 49% |
| S5 | Barcelona | 24 rooms out of order for renovation | lower availability, construction noise in reviews |
| S6 | Dubai Business Bay | city event missing from the pricing calendar | 0.76× the comp set, 83% full three weeks out |
| S7 | Berlin | POS feed stale | no F&B for the last 3 days, source flagged stale |
