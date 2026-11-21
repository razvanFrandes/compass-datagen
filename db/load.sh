#!/bin/sh
# Load the generated CSVs into Postgres.
#   db/load.sh                         loads out/full into the local database compass_hotels
#   db/load.sh out/preview             loads the preview instead
#   DATABASE_URL=postgres://... db/load.sh   loads into another server (Neon, Supabase, ...)
set -e
DIR="${1:-out/full}"
BUSINESS_DATE="${BUSINESS_DATE:-2026-11-20}"
if [ -z "$DATABASE_URL" ]; then
  DB=compass_hotels
  psql -d postgres -Atqc "select 1 from pg_database where datname = '$DB'" | grep -q 1 || createdb "$DB"
  DATABASE_URL="postgresql:///$DB"
fi
[ -f "$DIR/reservations.csv" ] || { echo "no CSVs in $DIR; run: uv run python -m datagen" >&2; exit 1; }

psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f "$(dirname "$0")/schema.sql"
psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -c "insert into hotel.settings values ('business_date', '$BUSINESS_DATE'), ('reporting_currency', 'EUR')"

# parents before children
for t in brands hotels segments channels room_types accounts guests group_blocks reservations reservation_nights \
         room_inventory_daily rates_daily rate_changes forecasts budgets lost_business competitors comp_rates \
         comp_set_daily fx_rates holidays city_events weather_daily outlets fnb_daily meeting_rooms me_events \
         labor_daily web_daily marketing_spend reviews pnl_monthly data_sources; do
  cols=$(head -1 "$DIR/$t.csv")
  psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -c "\copy hotel.$t ($cols) from '$DIR/$t.csv' with (format csv, header true)"
  printf '  %-22s %s\n' "$t" "$(psql "$DATABASE_URL" -Atqc "select count(*) from hotel.$t")"
done
psql "$DATABASE_URL" -q -c "analyze"
echo "loaded $DIR into $DATABASE_URL (schema hotel)"
