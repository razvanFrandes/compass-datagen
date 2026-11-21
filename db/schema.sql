-- Halcyon Hospitality Group: schema for the generated data (PostgreSQL 15+).
-- Money is in each hotel's local currency unless a column says _eur. fx_rates converts.
-- Run through db/load.sh, which creates the database, this schema and loads the CSVs.

drop schema if exists hotel cascade;
create schema hotel;
set search_path = hotel;

-- ------------------------------------------------------------ reference
create table settings (key text primary key, value text not null);

create table brands (
  brand_code text primary key, name text not null, tier text not null, group_name text not null);

create table hotels (
  hotel_code text primary key, name text not null, brand_code text not null references brands,
  city text not null, country char(2) not null, region text not null, currency char(3) not null,
  timezone text not null, rooms int not null, stars int not null, profile text not null,
  meeting_space_sqm int not null, pms_vendor text not null, pos_vendor text not null);

create table segments (
  segment text primary key, name text not null, rate_plan text not null, is_contracted boolean not null);

create table channels (
  channel text primary key, name text not null, channel_type text not null,
  commission_pct numeric(5,2) not null, fee_per_booking_eur numeric(8,2) not null);

create table room_types (
  hotel_code text references hotels, room_type text, name text not null, rooms int not null,
  rate_factor numeric(5,2) not null, primary key (hotel_code, room_type));

create table accounts (account_id int primary key, name text not null, account_type text not null);

create table fx_rates (currency char(3), date date, eur_per_unit numeric(18,8) not null, primary key (currency, date));
create table holidays (country char(2), date date, name text not null, primary key (country, date, name));
create table city_events (
  city text, name text, start_date date, end_date date not null, expected_demand_uplift numeric(4,2) not null,
  primary key (city, name, start_date));
create table weather_daily (
  hotel_code text references hotels, date date, temp_max_c numeric(4,1), precipitation_mm numeric(5,1),
  primary key (hotel_code, date));

-- ------------------------------------------------------------------ PMS
create table guests (
  guest_id int primary key, first_name text not null, last_name text not null, country char(2) not null,
  loyalty_tier text not null);

create table group_blocks (
  group_block_id int primary key, hotel_code text not null references hotels, account_id int references accounts,
  name text not null, group_type text not null, nights int not null, rooms_per_night int not null,
  group_rate numeric(16,2) not null, currency char(3) not null, created_at timestamp not null,
  arrival_date date not null, departure_date date not null, cutoff_date date not null, rooms_picked_up int not null);

create table reservations (
  reservation_id int primary key, confirmation_no text not null unique, hotel_code text not null references hotels,
  guest_id int not null references guests, account_id int references accounts,
  group_block_id int references group_blocks, created_at timestamp not null, arrival_date date not null,
  departure_date date not null, nights int not null, room_type_booked text not null, room_type_assigned text not null,
  rate_plan text not null, segment text not null references segments, channel text not null references channels,
  web_source text, web_device text, adults int not null, children int not null, breakfast_included boolean not null,
  status text not null check (status in ('confirmed', 'in_house', 'checked_out', 'cancelled', 'no_show')),
  cancelled_at timestamp, currency char(3) not null, avg_daily_rate numeric(16,2) not null,
  total_room_revenue numeric(16,2) not null);
comment on table reservations is
  'One row per reservation. created_at and cancelled_at let you rebuild what was on the books on any past date '
  '(see otb_as_of). Cancelled and no-show reservations keep the value they had when booked.';
comment on column reservations.status is
  'As of the business date: confirmed (future), in_house, checked_out, cancelled, no_show.';

create table reservation_nights (
  reservation_id int references reservations, hotel_code text not null references hotels, stay_date date,
  room_type text not null, room_revenue numeric(16,2) not null, guests int not null,
  primary key (reservation_id, stay_date));
comment on table reservation_nights is
  'One row per night actually stayed or still on the books (no cancelled or no-show reservations). '
  'Rooms sold = count of rows; room revenue = sum(room_revenue).';

create table room_inventory_daily (
  hotel_code text references hotels, date date, physical_rooms int not null, out_of_order int not null,
  rooms_available int not null, primary key (hotel_code, date));
comment on table room_inventory_daily is 'rooms_available = physical_rooms - out_of_order. Use it as the occupancy denominator.';

-- ------------------------------------------------------------------ RMS
create table rates_daily (
  hotel_code text references hotels, stay_date date, bar_rate numeric(16,2) not null, currency char(3) not null,
  primary key (hotel_code, stay_date));
comment on table rates_daily is 'Best available rate for a Standard room: final for past nights, current for future nights.';

create table rate_changes (
  hotel_code text references hotels, stay_date date not null, changed_at timestamp not null,
  old_rate numeric(16,2) not null, new_rate numeric(16,2) not null, source text not null, changed_by text not null);

create table forecasts (
  hotel_code text references hotels, stay_date date, forecast_date date not null, rooms_available int not null,
  rooms_on_books int not null, rooms_p10 int not null, rooms_p50 int not null, rooms_p90 int not null,
  adr_p50 numeric(16,2) not null, room_revenue_p50 numeric(16,2) not null, currency char(3) not null,
  primary key (hotel_code, stay_date, forecast_date));

create table budgets (
  hotel_code text references hotels, month date, rooms_available int not null, rooms_sold int not null,
  adr numeric(16,2) not null, room_revenue numeric(18,2) not null, currency char(3) not null,
  primary key (hotel_code, month));

create table lost_business (
  hotel_code text references hotels, request_date date not null, arrival_date date not null, segment text not null,
  channel text not null, reason text not null, requests int not null, room_nights int not null);
comment on table lost_business is 'Booking requests the hotel turned away: reason price (guest found BAR too high vs the market) or no_availability.';

-- --------------------------------------------------------------- market
create table competitors (
  competitor_id int primary key, hotel_code text not null references hotels, name text not null, stars int not null,
  rooms int not null, distance_km numeric(4,1) not null);

create table comp_rates (
  competitor_id int references competitors, stay_date date, shop_date date, rate numeric(16,2),
  currency char(3) not null, sold_out boolean not null, primary key (competitor_id, stay_date, shop_date));
comment on table comp_rates is 'Rate shops: a competitor''s Standard room rate for a stay date, as seen on shop_date. rate is null when sold out.';

create table comp_set_daily (
  hotel_code text references hotels, date date, rooms_available int not null, rooms_sold int not null,
  room_revenue numeric(18,2) not null, currency char(3) not null, primary key (hotel_code, date));
comment on table comp_set_daily is 'Benchmark feed: the comp set''s combined performance, past dates only. Basis for MPI, ARI, RGI.';

-- ---------------------------------------------------------- operations
create table outlets (outlet_id int primary key, hotel_code text not null references hotels, name text not null,
  outlet_type text not null);

create table fnb_daily (
  outlet_id int references outlets, hotel_code text not null references hotels, date date, meal_period text,
  covers int not null, in_house_covers int not null, food_revenue numeric(16,2) not null,
  beverage_revenue numeric(16,2) not null, food_cost numeric(16,2) not null, beverage_cost numeric(16,2) not null,
  currency char(3) not null, primary key (outlet_id, date, meal_period));

create table meeting_rooms (meeting_room_id int primary key, hotel_code text not null references hotels,
  name text not null, sqm int not null, capacity_theatre int not null);

create table me_events (
  event_id int primary key, hotel_code text not null references hotels, meeting_room_id int references meeting_rooms,
  name text not null, event_type text not null, start_date date not null, end_date date not null, attendees int not null,
  group_block_id int references group_blocks, account_id int references accounts, created_at date not null,
  status text not null, space_revenue numeric(16,2) not null, fnb_revenue numeric(16,2) not null,
  av_revenue numeric(16,2) not null, currency char(3) not null);

create table labor_daily (
  hotel_code text references hotels, date date, department text, required_hours numeric(8,1) not null,
  scheduled_hours numeric(8,1) not null, actual_hours numeric(8,1) not null, overtime_hours numeric(8,1) not null,
  headcount int not null, labor_cost numeric(16,2) not null, currency char(3) not null,
  primary key (hotel_code, date, department));
comment on table labor_daily is 'required_hours is the productivity standard for the day''s volume; actual below required means short-staffed.';

create table web_daily (
  hotel_code text references hotels, date date, source text, device text, sessions int not null, searches int not null,
  checkout_starts int not null, bookings int not null, booking_revenue numeric(16,2) not null, currency char(3) not null,
  primary key (hotel_code, date, source, device));

create table marketing_spend (
  hotel_code text references hotels, date date, source text, spend numeric(16,2) not null, currency char(3) not null,
  primary key (hotel_code, date, source));

create table reviews (
  review_id int primary key, hotel_code text not null references hotels, reservation_id int references reservations,
  source text not null, review_date date not null, overall_score numeric(3,1) not null, staff numeric(3,1),
  cleanliness numeric(3,1), comfort numeric(3,1), location numeric(3,1), value numeric(3,1), food numeric(3,1),
  language text not null, positive_text text, negative_text text, topics text);

-- -------------------------------------------------------------- finance
create table pnl_monthly (
  hotel_code text references hotels, month date, scenario text, line text, amount numeric(18,2) not null,
  currency char(3) not null, primary key (hotel_code, month, scenario, line));
comment on table pnl_monthly is 'USALI-style monthly P&L. scenario: actual (complete months), budget, forecast (current and future months).';

-- ---------------------------------------------------------- data health
create table data_sources (
  hotel_code text references hotels, system text, vendor text not null, connection text not null,
  last_sync_at timestamp not null, status text not null, primary key (hotel_code, system));

-- ============================================================== helpers
-- EUR per unit of a currency on a date; later dates use the latest known rate.
create function eur_rate(cur char(3), d date) returns numeric language sql stable as $$
  select case when cur = 'EUR' then 1 else
    (select eur_per_unit from hotel.fx_rates f where f.currency = cur and f.date <= d order by f.date desc limit 1) end
$$;

create function business_date() returns date language sql stable as $$
  select value::date from hotel.settings where key = 'business_date'
$$;

-- What was on the books on a given day, for every stay night. The heart of pace and pickup.
-- Pass a stay-date range whenever you can: it keeps the query to the reservations that matter.
create function otb_as_of(as_of date, p_hotel text default null, stay_from date default null, stay_to date default null)
returns table (hotel_code text, stay_date date, rooms_on_books bigint, revenue_on_books numeric)
language sql stable as $$
  select r.hotel_code, n::date, count(*), sum(r.avg_daily_rate)
  from hotel.reservations r
  cross join generate_series(greatest(r.arrival_date, coalesce(stay_from, r.arrival_date)),
                             least(r.departure_date - 1, coalesce(stay_to, r.departure_date - 1)), interval '1 day') n
  where r.created_at < as_of + 1
    and (r.cancelled_at is null or r.cancelled_at >= as_of + 1)
    and (p_hotel is null or r.hotel_code = p_hotel)
    and (stay_from is null or r.departure_date > stay_from)
    and (stay_to is null or r.arrival_date <= stay_to)
  group by 1, 2
$$;

-- On the books now vs the same time last year (STLY, -364 days so weekdays line up).
create function pace_vs_stly(p_hotel text default null, days_ahead int default 90)
returns table (hotel_code text, stay_date date, rooms_otb bigint, rooms_otb_stly bigint, revenue_otb numeric,
               revenue_otb_stly numeric)
language sql stable as $$
  with bd as (select hotel.business_date() as d),
       now_ as (select o.* from bd, hotel.otb_as_of(bd.d, p_hotel, bd.d, bd.d + days_ahead) o),
       ly as (select o.* from bd, hotel.otb_as_of(bd.d - 364, p_hotel, bd.d - 364, bd.d - 364 + days_ahead) o)
  select h.hotel_code, g.night::date, coalesce(n.rooms_on_books, 0), coalesce(l.rooms_on_books, 0),
         coalesce(n.revenue_on_books, 0), coalesce(l.revenue_on_books, 0)
  from hotel.hotels h
  cross join bd
  cross join generate_series(bd.d, bd.d + days_ahead, interval '1 day') g(night)
  left join now_ n on n.hotel_code = h.hotel_code and n.stay_date = g.night::date
  left join ly l on l.hotel_code = h.hotel_code and l.stay_date = g.night::date - 364
  where p_hotel is null or h.hotel_code = p_hotel
$$;

-- ================================================================ views
-- One row per hotel and day: the standard room statistics, in local currency and EUR.
create view v_hotel_day as
select i.hotel_code, i.date, i.rooms_available, coalesce(s.rooms_sold, 0) as rooms_sold,
       coalesce(s.room_revenue, 0) as room_revenue,
       round(coalesce(s.rooms_sold, 0)::numeric / nullif(i.rooms_available, 0), 4) as occupancy,
       round(s.room_revenue / nullif(s.rooms_sold, 0), 2) as adr,
       round(coalesce(s.room_revenue, 0) / nullif(i.rooms_available, 0), 2) as revpar,
       round(coalesce(s.room_revenue, 0) * eur_rate(h.currency, i.date), 2) as room_revenue_eur,
       h.currency, i.date < business_date() as is_actual
from room_inventory_daily i
join hotels h using (hotel_code)
left join (select hotel_code, stay_date as date, count(*) as rooms_sold, sum(room_revenue) as room_revenue
           from reservation_nights group by 1, 2) s using (hotel_code, date);

-- The hotel against its comp set: occupancy index (MPI), rate index (ARI), RevPAR index (RGI). 100 = fair share.
create view v_comp_set_index as
select d.hotel_code, d.date, d.occupancy, d.adr, d.revpar,
       round(c.rooms_sold::numeric / c.rooms_available, 4) as comp_occupancy,
       round(c.room_revenue / nullif(c.rooms_sold, 0), 2) as comp_adr,
       round(100 * d.occupancy / nullif(c.rooms_sold::numeric / c.rooms_available, 0), 1) as mpi,
       round(100 * d.adr / nullif(c.room_revenue / nullif(c.rooms_sold, 0), 0), 1) as ari,
       round(100 * d.revpar / nullif(c.room_revenue / c.rooms_available, 0), 1) as rgi
from v_hotel_day d join comp_set_daily c using (hotel_code, date);

-- Gross and net room revenue by channel and month: net = after commission and GDS fees.
create view v_channel_month as
select n.hotel_code, date_trunc('month', n.stay_date)::date as month, r.channel, c.channel_type,
       count(*) as room_nights, sum(n.room_revenue) as gross_revenue,
       sum(n.room_revenue * c.commission_pct / 100) as commission,
       sum(n.room_revenue * (1 - c.commission_pct / 100)) as net_revenue
from reservation_nights n
join reservations r using (reservation_id)
join channels c using (channel)
group by 1, 2, 3, 4;

-- Our BAR against the comp set median from the latest shop, for each future night.
create view v_rate_position as
with latest as (
  select cr.competitor_id, cr.stay_date, cr.rate,
         row_number() over (partition by cr.competitor_id, cr.stay_date order by cr.shop_date desc) as rn
  from comp_rates cr where cr.stay_date >= business_date())
select r.hotel_code, r.stay_date, r.bar_rate,
       percentile_cont(0.5) within group (order by l.rate) as comp_median,
       round(r.bar_rate / nullif(percentile_cont(0.5) within group (order by l.rate), 0)::numeric, 3) as bar_vs_comp,
       count(*) filter (where l.rate is null) as comps_sold_out
from rates_daily r
join competitors c on c.hotel_code = r.hotel_code
join latest l on l.competitor_id = c.competitor_id and l.stay_date = r.stay_date and l.rn = 1
where r.stay_date >= business_date()
group by r.hotel_code, r.stay_date, r.bar_rate;

-- ============================================================== indexes
create index on reservations (hotel_code, arrival_date);
create index on reservations (arrival_date, departure_date);
create index on reservations (hotel_code, created_at);
create index on reservations (hotel_code, cancelled_at);
create index on reservation_nights (hotel_code, stay_date);
create index on rate_changes (hotel_code, stay_date);
create index on lost_business (hotel_code, arrival_date);
create index on reviews (hotel_code, review_date);
create index on fnb_daily (hotel_code, date);
create index on comp_rates (stay_date);

-- ============================================================ embeddings
-- Optional: needs the pgvector extension. Skipped with a notice when it is not installed.
do $$
begin
  create extension if not exists vector;
  create table hotel.review_embeddings (
    review_id int primary key references hotel.reviews, model text not null, embedding vector(1024) not null);
  create table hotel.documents (
    document_id serial primary key, hotel_code text references hotel.hotels, kind text not null, title text not null,
    body text not null, created_at timestamp not null default now());
  create table hotel.document_chunks (
    document_id int references hotel.documents, chunk_no int, content text not null, model text not null,
    embedding vector(1024) not null, primary key (document_id, chunk_no));
exception when others then
  raise notice 'pgvector not available (%), embedding tables skipped', sqlerrm;
end $$;
