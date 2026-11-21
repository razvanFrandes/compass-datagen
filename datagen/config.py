"""Single source of truth for the generator.

Everything a planted story depends on lives here: the hotels, the market
behaviour and the dated stories with the size of each effect. The answer key
is written from STORIES, so if an effect is not here it was not planted.

All hotels, brands, companies, competitors and events are fictional.
"""
from dataclasses import dataclass
from datetime import date, timedelta

SEED = 2026
# The day the data is "frozen" at: everything before it is actuals, everything
# after it is on the books. Bookings created after this day do not exist yet.
BUSINESS_DATE = date(2026, 11, 20)

GROUP_NAME = "Halcyon Hospitality Group"
REPORTING_CURRENCY = "EUR"


def bd(days: int) -> date:
    """A date relative to the business date."""
    return BUSINESS_DATE + timedelta(days=days)


# ------------------------------------------------------------------ brands
@dataclass(frozen=True)
class Brand:
    code: str
    name: str
    tier: str
    review_base: float  # mean guest score out of 10 before any effect


BRANDS = {
    "KES": Brand("KES", "Kestrel", "luxury", 8.9),
    "ARB": Brand("ARB", "Arbor", "upscale", 8.4),
    "TES": Brand("TES", "Tessera", "select service", 8.0),
    "LUM": Brand("LUM", "Lumen", "resort", 8.6),
}


# ------------------------------------------------------------------ hotels
@dataclass(frozen=True)
class Hotel:
    code: str
    name: str
    brand: str
    city: str
    country: str  # ISO 3166 alpha-2
    region: str
    currency: str
    timezone: str
    rooms: int
    stars: int
    base_adr: float  # local currency, at the business date, average season
    base_occ: float  # long-run occupancy the market supports
    profile: str  # drives the segment mix
    season: str  # key into SEASON
    week: str  # key into WEEK
    avg_check: float  # dinner check per cover, local currency
    meeting_sqm: int
    pms: str
    pos: str
    temp_mean: float  # degrees C, yearly mean
    temp_amp: float  # half the summer-winter swing; negative in the southern hemisphere
    rain_p: float  # chance of a rainy day


HOTELS = [
    Hotel("AMS", "Arbor Amsterdam Centraal", "ARB", "Amsterdam", "NL", "Europe", "EUR", "Europe/Amsterdam",
          220, 4, 195, 0.82, "city_business", "europe_city", "business", 55, 900, "Mews", "Lightspeed", 10.5, 7, 0.45),
    Hotel("LON1", "Kestrel London Mayfair", "KES", "London", "GB", "Europe", "GBP", "Europe/London",
          120, 5, 560, 0.80, "luxury_city", "europe_city", "leisure", 95, 600, "Opera Cloud", "Micros Simphony", 11.5, 7, 0.4),
    Hotel("LON2", "Tessera London King's Cross", "TES", "London", "GB", "Europe", "GBP", "Europe/London",
          260, 3, 175, 0.86, "city_business", "europe_city", "business", 38, 0, "Apaleo", "Lightspeed", 11.5, 7, 0.4),
    Hotel("PAR", "Arbor Paris Opera", "ARB", "Paris", "FR", "Europe", "EUR", "Europe/Paris",
          180, 4, 310, 0.81, "city_leisure", "europe_city", "leisure", 70, 450, "Opera Cloud", "Micros Simphony", 12.5, 8, 0.35),
    Hotel("BCN", "Lumen Barcelona Mar", "LUM", "Barcelona", "ES", "Europe", "EUR", "Europe/Madrid",
          300, 4, 235, 0.78, "resort", "med_resort", "resort", 45, 1200, "Mews", "Lightspeed", 16.5, 7.5, 0.18),
    Hotel("LIS", "Arbor Lisbon Chiado", "ARB", "Lisbon", "PT", "Europe", "EUR", "Europe/Lisbon",
          150, 4, 180, 0.80, "city_leisure", "europe_city", "leisure", 38, 300, "Mews", "Lightspeed", 17.5, 5.5, 0.2),
    Hotel("BER", "Tessera Berlin Mitte", "TES", "Berlin", "DE", "Europe", "EUR", "Europe/Berlin",
          240, 3, 120, 0.79, "city_business", "europe_city", "business", 35, 350, "Apaleo", "Lightspeed", 10.0, 9.5, 0.33),
    Hotel("VIE", "Kestrel Vienna Ring", "KES", "Vienna", "AT", "Europe", "EUR", "Europe/Vienna",
          140, 5, 380, 0.78, "luxury_city", "europe_city", "leisure", 85, 700, "Opera Cloud", "Micros Simphony", 11.0, 10, 0.3),
    Hotel("NYC", "Arbor New York Midtown", "ARB", "New York", "US", "North America", "USD", "America/New_York",
          380, 4, 345, 0.87, "city_business", "us_city", "business", 75, 1500, "Opera Cloud", "Micros Simphony", 13.0, 12, 0.3),
    Hotel("MIA", "Lumen Miami Beach", "LUM", "Miami", "US", "North America", "USD", "America/New_York",
          260, 4, 395, 0.76, "resort", "us_resort", "resort", 70, 800, "Opera Cloud", "Micros Simphony", 25.5, 4, 0.35),
    Hotel("CHI", "Tessera Chicago Loop", "TES", "Chicago", "US", "North America", "USD", "America/Chicago",
          280, 3, 195, 0.74, "city_business", "us_city", "business", 48, 400, "Mews", "Lightspeed", 10.5, 14, 0.3),
    Hotel("YYZ", "Arbor Toronto Financial District", "ARB", "Toronto", "CA", "North America", "CAD", "America/Toronto",
          230, 4, 290, 0.77, "city_business", "us_city", "business", 60, 650, "Apaleo", "Lightspeed", 9.0, 14, 0.3),
    Hotel("DXB1", "Kestrel Dubai Marina", "KES", "Dubai", "AE", "Middle East", "AED", "Asia/Dubai",
          320, 5, 1500, 0.79, "resort", "gulf", "resort", 380, 1800, "Opera Cloud", "Micros Simphony", 28.0, 7, 0.03),
    Hotel("DXB2", "Tessera Dubai Business Bay", "TES", "Dubai", "AE", "Middle East", "AED", "Asia/Dubai",
          300, 3, 560, 0.80, "city_business", "gulf", "business", 160, 500, "Opera Cloud", "Micros Simphony", 28.0, 7, 0.03),
    Hotel("DOH", "Arbor Doha West Bay", "ARB", "Doha", "QA", "Middle East", "QAR", "Asia/Qatar",
          250, 4, 650, 0.72, "city_business", "gulf", "business", 220, 1400, "Opera Cloud", "Micros Simphony", 28.5, 7.5, 0.03),
    Hotel("GRU", "Arbor Sao Paulo Faria Lima", "ARB", "Sao Paulo", "BR", "South America", "BRL", "America/Sao_Paulo",
          240, 4, 820, 0.71, "city_business", "south_city", "business", 160, 700, "Opera Cloud", "Micros Simphony", 20.0, -3.5, 0.4),
    Hotel("EZE", "Tessera Buenos Aires Palermo", "TES", "Buenos Aires", "AR", "South America", "USD", "America/Argentina/Buenos_Aires",
          180, 3, 165, 0.74, "city_leisure", "south_city", "leisure", 35, 0, "Mews", "Lightspeed", 18.0, -6, 0.25),
    Hotel("SIN", "Kestrel Singapore Marina", "KES", "Singapore", "SG", "Asia", "SGD", "Asia/Singapore",
          280, 5, 620, 0.84, "luxury_city", "asia_city", "business", 110, 1300, "Opera Cloud", "Micros Simphony", 27.5, 0.8, 0.45),
    Hotel("TYO", "Arbor Tokyo Ginza", "ARB", "Tokyo", "JP", "Asia", "JPY", "Asia/Tokyo",
          210, 4, 52000, 0.85, "city_leisure", "asia_city", "leisure", 9000, 300, "Opera Cloud", "Micros Simphony", 16.0, 10, 0.3),
    Hotel("DPS", "Lumen Bali Uluwatu", "LUM", "Bali", "ID", "Asia", "IDR", "Asia/Makassar",
          200, 5, 4_800_000, 0.77, "resort", "tropical_resort", "resort", 650_000, 400, "Mews", "Lightspeed", 27.0, 1, 0.4),
]
HOTEL = {h.code: h for h in HOTELS}

# Labour cost as a share of total revenue. Hourly wages are derived from it, so payroll stays realistic
# whatever the local price level (typical ranges from hotel benchmarking).
LABOUR_SHARE = {"Europe": 0.33, "North America": 0.35, "Middle East": 0.24, "South America": 0.28, "Asia": 0.27}

# EUR per one unit of local currency at the business date.
FX_TO_EUR = {"EUR": 1.0, "GBP": 1.17, "USD": 0.92, "CAD": 0.66, "AED": 0.25, "QAR": 0.25,
             "BRL": 0.17, "SGD": 0.69, "JPY": 0.0061, "IDR": 0.000057}

# Occupancy multiplier per month, January first.
SEASON = {
    "europe_city": [0.72, 0.78, 0.88, 0.98, 1.05, 1.08, 1.05, 0.98, 1.08, 1.05, 0.92, 0.85],
    "med_resort": [0.62, 0.68, 0.80, 0.95, 1.05, 1.18, 1.30, 1.32, 1.12, 0.95, 0.72, 0.70],
    "us_city": [0.75, 0.85, 0.95, 1.00, 1.05, 1.05, 1.00, 0.98, 1.05, 1.08, 0.95, 0.85],
    "us_resort": [1.25, 1.30, 1.28, 1.10, 0.95, 0.82, 0.85, 0.80, 0.75, 0.90, 1.05, 1.15],
    "gulf": [1.15, 1.18, 1.12, 1.05, 0.88, 0.70, 0.62, 0.65, 0.85, 1.05, 1.15, 1.15],
    "south_city": [0.75, 0.85, 1.02, 1.05, 1.05, 1.00, 0.95, 1.02, 1.05, 1.08, 1.05, 0.88],
    "asia_city": [0.90, 0.92, 1.02, 1.08, 0.98, 0.95, 1.00, 1.00, 0.98, 1.05, 1.05, 1.05],
    "tropical_resort": [0.85, 0.80, 0.85, 0.95, 1.00, 1.10, 1.25, 1.28, 1.10, 0.98, 0.85, 1.10],
}
# Occupancy multiplier per stay night, Monday first.
WEEK = {
    "business": [1.05, 1.12, 1.12, 1.02, 0.82, 0.72, 0.75],
    "leisure": [0.85, 0.85, 0.90, 0.98, 1.15, 1.22, 0.85],
    "resort": [0.92, 0.90, 0.92, 0.98, 1.10, 1.15, 0.98],
}

# ------------------------------------------------------------- room types
# base_adr is the average rate the hotel achieves. BAR is quoted for a Standard room, and the room mix,
# upgrades and segment discounts bring the average back up to base_adr, so BAR = base_adr / ADR_TO_BAR.
ADR_TO_BAR = 1.12
# code, name, share of rooms, rate factor vs BAR
ROOM_TYPES = [
    ("STD", "Standard", 0.58, 1.00),
    ("SUP", "Superior", 0.25, 1.22),
    ("DLX", "Deluxe", 0.12, 1.50),
    ("STE", "Suite", 0.05, 2.60),
]


# --------------------------------------------------------------- segments
@dataclass(frozen=True)
class Segment:
    code: str
    name: str
    lead_mean: float  # days
    los_mean: float  # nights
    cancel_p: float  # share of bookings that cancel before arrival
    rate_factor: float  # vs BAR
    rate_plan: str
    breakfast_p: float
    contracted: bool  # price is negotiated, so the guest does not compare BAR with the market
    channels: dict


SEGMENTS = {
    "RET": Segment("RET", "Transient retail", 24, 2.2, 0.24, 1.00, "BAR", 0.35, False,
                   {"WEB": 0.30, "VOICE": 0.06, "BDC": 0.40, "EXP": 0.18, "GDS": 0.06}),
    "ADV": Segment("ADV", "Advance purchase", 55, 2.6, 0.03, 0.85, "NRF", 0.30, False,
                   {"WEB": 0.45, "BDC": 0.38, "EXP": 0.17}),
    "COR": Segment("COR", "Corporate negotiated", 12, 1.9, 0.18, 0.88, "CORP", 0.55, True,
                   {"GDS": 0.55, "WEB": 0.20, "VOICE": 0.25}),
    "GRP": Segment("GRP", "Group", 0, 3.0, 0.08, 0.80, "GROUP", 0.75, True, {"GRPDESK": 1.0}),
    "WHL": Segment("WHL", "Wholesale", 70, 4.0, 0.15, 0.75, "WHS-NET", 0.60, True, {"WHS": 1.0}),
    "PKG": Segment("PKG", "Leisure package", 45, 3.6, 0.20, 1.12, "PKG-BB", 1.00, False,
                   {"WEB": 0.50, "BDC": 0.30, "EXP": 0.20}),
}

# Segment mix by hotel profile (room nights).
SEGMENT_MIX = {
    "city_business": {"RET": 0.38, "ADV": 0.12, "COR": 0.28, "GRP": 0.12, "WHL": 0.05, "PKG": 0.05},
    "city_leisure": {"RET": 0.45, "ADV": 0.18, "COR": 0.08, "GRP": 0.07, "WHL": 0.12, "PKG": 0.10},
    "luxury_city": {"RET": 0.48, "ADV": 0.08, "COR": 0.14, "GRP": 0.06, "WHL": 0.10, "PKG": 0.14},
    "resort": {"RET": 0.40, "ADV": 0.15, "COR": 0.02, "GRP": 0.08, "WHL": 0.17, "PKG": 0.18},
}

# code, name, type, commission %, fixed fee per booking in EUR
CHANNELS = [
    ("WEB", "Brand website", "direct", 3.0, 0.0),
    ("VOICE", "Reservations office", "direct", 0.0, 0.0),
    ("GRPDESK", "Group sales", "direct", 0.0, 0.0),
    ("BDC", "Booking.com", "OTA", 17.0, 0.0),
    ("EXP", "Expedia", "OTA", 18.0, 0.0),
    ("GDS", "GDS (travel agents)", "GDS", 10.0, 8.0),
    ("WHS", "Wholesalers", "wholesale", 0.0, 0.0),
]

# Fictional companies. weight = share of a hotel's corporate demand.
CORPORATE_ACCOUNTS = [
    ("Vantor Consulting", 0.36), ("Norrland Pharma", 0.16), ("Bellweather Bank", 0.14),
    ("Quillon Software", 0.11), ("Atlas Freight Lines", 0.09), ("Mirela Energy", 0.08), ("Osric Legal", 0.06),
]
WHOLESALERS = [("SunPath Tours", 0.45), ("Globetrail Travel", 0.35), ("Kairo Holidays", 0.20)]

WEB_SOURCES = {"organic": 0.30, "paid_search": 0.25, "metasearch": 0.20, "direct": 0.15, "email": 0.07, "social": 0.03}
PAID_SOURCES = ["paid_search", "metasearch", "social", "email"]

# ----------------------------------------------------------- city events
# city, name, month, day, nights, demand multiplier. Recur every year. Fictional.
CITY_EVENTS = [
    ("Amsterdam", "Canal Lights Festival", 12, 1, 10, 1.10),
    ("Amsterdam", "North Sea Tech Expo", 5, 12, 3, 1.35),
    ("London", "West End Winter Fair", 12, 5, 12, 1.12),
    ("London", "Thames Finance Week", 3, 16, 4, 1.30),
    ("Paris", "Rive Gauche Fashion Days", 9, 28, 6, 1.35),
    ("Barcelona", "Mobile Devices Congress", 2, 23, 4, 1.65),
    ("Lisbon", "Atlantic Web Forum", 11, 9, 4, 1.40),
    ("Berlin", "Spree Fintech Forum", 11, 25, 3, 1.30),
    ("Vienna", "Ringstrasse Christmas Markets", 11, 15, 40, 1.12),
    ("New York", "Hudson Holiday Season", 12, 12, 18, 1.15),
    ("Miami", "Bayfront Art Week", 12, 3, 5, 1.50),
    ("Chicago", "Lakeshore Manufacturing Expo", 10, 19, 4, 1.40),
    ("Toronto", "Toronto Film Week", 9, 10, 8, 1.40),
    ("Dubai", "Gulf Tech Week", 12, 15, 5, 1.80),
    ("Doha", "West Bay Energy Summit", 2, 9, 3, 1.45),
    ("Sao Paulo", "Paulista Motor Weekend", 11, 6, 3, 1.40),
    ("Buenos Aires", "Palermo Tango Week", 8, 14, 6, 1.25),
    ("Singapore", "Marina Night Race", 9, 19, 3, 1.60),
    ("Tokyo", "Ginza Autumn Foliage Season", 11, 10, 20, 1.08),
    ("Bali", "Uluwatu Surf Classic", 6, 5, 6, 1.20),
]

# ----------------------------------------------------------------- stories
# Each story is planted on purpose, with a size, and has a check in tests/.
# Dates are relative to the business date so the stories stay "recent".
STORIES = {
    "S1_LIS_RATE_OVERRIDE": dict(
        hotel="LIS", changed_on=bd(-21), stay_from=bd(0), stay_to=bd(45), uplift=1.22, user="rm.lisbon",
        what="A manual BAR override of +22% on Lisbon for the next 45 nights. Lisbon now sits well above its "
             "comp set, so price-sensitive retail and OTA pickup slows and pace for those nights falls below STLY.",
    ),
    "S2_NYC_CORPORATE_LOSS": dict(
        hotel="NYC", account="Vantor Consulting", lost_from=bd(-180),
        what="New York's biggest corporate account moved its travel programme elsewhere six months ago. The "
             "freed weekday rooms are refilled through Booking.com and Expedia, so occupancy holds but net "
             "revenue after commission falls.",
    ),
    "S3_DPS_KITCHEN_SHORTAGE": dict(
        hotel="DPS", start=bd(-45), end=bd(-10), staffing=0.68, capture_drop=0.40,
        what="Bali ran its kitchen at about two thirds of the hours it needs for five weeks. Restaurant capture "
             "and in-room dining fall, and guest scores on food drop with complaints about slow service.",
    ),
    "S4_AMS_MOBILE_CHECKOUT": dict(
        hotel="AMS", start=bd(-30), mobile_fail=0.55, switch_to_ota=0.70,
        what="A booking engine release in Amsterdam broke part of the mobile checkout. Mobile conversion on the "
             "brand website drops, and most of the lost guests book the same hotel on Booking.com instead.",
    ),
    "S5_BCN_RENOVATION": dict(
        hotel="BCN", start=bd(-60), end=bd(30), rooms_out=24,
        what="Barcelona has a floor of 24 standard rooms out of order for renovation. Rooms available drop, "
             "and guests near the works mention noise.",
    ),
    "S6_DXB_EVENT_UNDERPRICED": dict(
        hotel="DXB2", event="Gulf Tech Week",
        what="Gulf Tech Week is not in Dubai Business Bay's pricing calendar. The hotel fills early at normal "
             "rates while the comp set prices the week at nearly double, so its rate index is far below the "
             "market for those nights.",
    ),
    "S7_BER_POS_FEED": dict(
        hotel="BER", stale_since=bd(-3),
        what="Berlin's point-of-sale feed stopped syncing three days ago, so F&B for the last three days is "
             "missing and the data health page shows the source as stale.",
    ),
}
