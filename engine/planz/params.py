"""Planning parameters transcribed from the Objective sheet of program_z.xlsx.

The Objective sheet is prose, so machine-relevant values are transcribed here
(single source of truth) and written into the DB by ingest. Row references are
to the Objective sheet as read with header=None.
"""

# --- Horizon (derived from Data - 104 weeks: actuals fill 2021W41..2023W39) ---
FIRST_ACTUAL_WEEK = "2021W41"
LAST_ACTUAL_WEEK = "2023W39"
HORIZON_START = "2023W40"   # first forecast week = start of CQ+1
HORIZON_END = "2024W39"     # 4 fiscal quarters = 52 weeks
HOLDOUT_START = "2023W27"   # last 13 actual weeks: backtest window (docs D9)

# --- WOS targets (rows 10-13) ---
WOS_KANBAN = 6
WOS_SEA_FREIGHT = 6
WOS_KANBAN_SEA_TARGET = 12   # Kanban + Sea Freight
WOS_CHANNEL_TARGET = 13      # Channel / reseller inventory

# --- Capacity & pack-out (rows 24-26) ---
QUARTERLY_CAPACITY_CAP = 224_000
WEEKLY_CAPACITY_CAP = 17_280
PACKOUT_SLOTS_PER_WEEK = 4   # max distinct variants packed out per week

# --- Enclosure-shortage scenario (row 29) ---
SCENARIO_VARIANTS = ("Variant V2", "Variant V4")
SCENARIO_WEEKLY_CAP = 4_500  # combined V2+V4 units/week
SCENARIO_N_WEEKS = 6         # first 6 weeks of CQ+1 -> 2023W40..2023W45

# --- Freight options (rows 17-22); geo "ANY" = available to all geos ---
OEM_LOCATION = "Thailand"
FREIGHT_OPTIONS = [
    # (mode, geo, lead_time_weeks, cost_per_unit_usd)
    ("Air", "ANY", 1, 7.0),
    ("Ground", "Geo G4", 1, 2.5),
    ("Fast Boat Ocean", "Geo G1", 5, 3.5),
    ("Standard Ocean", "Geo G1", 8, 2.0),
    ("Standard Ocean", "Geo G2", 11, 2.5),
]

# --- Channel identities (row 1) ---
CHANNELS_SI_EQ_ST = ("Channel 1", "Channel 2")  # Sell-In == Sell-Through
RESELLER_CHANNEL = "Channel 3"                  # carries reseller buffer


def as_param_rows() -> list[tuple[str, str]]:
    """Scalar params as (key, value) rows for the DB params table."""
    return [
        ("first_actual_week", FIRST_ACTUAL_WEEK),
        ("last_actual_week", LAST_ACTUAL_WEEK),
        ("horizon_start", HORIZON_START),
        ("horizon_end", HORIZON_END),
        ("holdout_start", HOLDOUT_START),
        ("wos_kanban", str(WOS_KANBAN)),
        ("wos_sea_freight", str(WOS_SEA_FREIGHT)),
        ("wos_kanban_sea_target", str(WOS_KANBAN_SEA_TARGET)),
        ("wos_channel_target", str(WOS_CHANNEL_TARGET)),
        ("quarterly_capacity_cap", str(QUARTERLY_CAPACITY_CAP)),
        ("weekly_capacity_cap", str(WEEKLY_CAPACITY_CAP)),
        ("packout_slots_per_week", str(PACKOUT_SLOTS_PER_WEEK)),
        ("scenario_variants", ",".join(SCENARIO_VARIANTS)),
        ("scenario_weekly_cap", str(SCENARIO_WEEKLY_CAP)),
        ("scenario_n_weeks", str(SCENARIO_N_WEEKS)),
        ("oem_location", OEM_LOCATION),
    ]
