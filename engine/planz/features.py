"""Feature engineering for the demand forecast.

One FeatureBuilder instance loads everything static from planz.db; rows are
generated per (series, week-offset) from a history array, so the exact same
code path serves training and recursive prediction. Week offsets are 0-based
from 2021W41 (offset 0) through 2024W39 (offset 155); actuals span 0..103.

Missing values (unavailable lags, unpriced variants) are NaN — XGBoost
handles them natively.
"""
from __future__ import annotations

import sqlite3

import numpy as np

from . import calendar as cal
from . import params

BASE_OFFSET = cal.week_index(params.FIRST_ACTUAL_WEEK)   # 2021W41
N_WEEKS = 156
N_ACTUAL = 104

# ML models exclude: zero-history NPIs (analog-ramped) and the dead drop
NON_ML_VARIANTS = {"Variant V10", "Variant V11", "Variant V12"}

EVENT_GROUPS = {
    "Promo Q1": "promo_q1", "Promo Q1 Rollover": "promo_q1",
    "Black Friday": "black_friday", "Cyber Monday": "cyber_monday",
    "Pre - XMAS W1": "pre_xmas", "Pre - XMAS W2": "pre_xmas",
    "XMAS": "xmas",
    "Mother's Day W1": "mothers_day", "Mother's Day W2": "mothers_day",
    "Father's Day W1": "fathers_day", "Father's Day W2": "fathers_day",
    "Promo Q4": "promo_q4", "Promo Q4 Rollover": "promo_q4",
}
GROUPS = ["promo_q1", "black_friday", "cyber_monday", "pre_xmas", "xmas",
          "mothers_day", "fathers_day", "promo_q4"]

FEATURES = (
    ["variant_code", "geo_code", "channel_code",
     "is_core", "is_otd", "is_exclusive",
     "fiscal_week", "fiscal_qtr", "week_in_qtr"]
    + [f"ev_{g}" for g in GROUPS]
    + ["ev_any_next", "ev_any_prev",
       "rel_price",
       "lag1", "lag2", "lag3", "lag4", "lag13", "lag_yoy",
       "roll4_mean", "roll13_mean", "roll4_max",
       "weeks_since_first_sale", "weeks_since_release"]
)


def offset_of(label: str) -> int:
    return cal.week_index(label) - BASE_OFFSET


def label_of(offset: int) -> str:
    return cal.from_index(offset + BASE_OFFSET)


def yoy_offset(offset: int) -> int | None:
    """Offset of the same fiscal week one year earlier (label-based, so the
    53-week fiscal 2021 is handled), or None if before the data window."""
    year, week = cal.parse_week(label_of(offset))
    if year - 1 < cal.BASE_YEAR:
        return None
    prev = (year - 1, min(week, cal.weeks_in_year(year - 1)))
    o = cal.week_index(cal.week_label(*prev)) - BASE_OFFSET
    return o if o >= 0 else None


class FeatureBuilder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._load_calendar()
        self._load_events()
        self._load_variants()
        self._load_prices()
        self._load_series()

    # ---------- loading ----------

    def _load_calendar(self):
        self.week_meta = {}
        for r in self.conn.execute(
                "SELECT week_label, fiscal_week, fiscal_qtr, week_in_qtr"
                " FROM calendar"):
            self.week_meta[offset_of(r["week_label"])] = (
                r["fiscal_week"], r["fiscal_qtr"], r["week_in_qtr"])

    def _load_events(self):
        flags = np.zeros((N_WEEKS, len(GROUPS)))
        for r in self.conn.execute("SELECT event, week_label FROM seasonality"):
            try:
                o = offset_of(r["week_label"])
            except ValueError:
                continue
            if 0 <= o < N_WEEKS:
                flags[o, GROUPS.index(EVENT_GROUPS[r["event"]])] = 1.0
        self.event_flags = flags
        self.any_event = flags.max(axis=1)

    def _load_variants(self):
        self.variant_meta = {}
        for r in self.conn.execute(
                "SELECT variant, part_number, classification, release_week"
                " FROM variants"):
            rel = (offset_of(r["release_week"])
                   if r["release_week"] else None)
            self.variant_meta[r["variant"]] = (
                r["part_number"], r["classification"], rel)

    def _load_prices(self):
        """Per-variant mean weekly price across retailers, forward-filled
        to the end of the window, relative to the variant's median."""
        self.rel_price = {}
        rows = self.conn.execute(
            "SELECT variant, week_label, AVG(price) AS p FROM prices"
            " GROUP BY variant, week_label").fetchall()
        by_var: dict[str, dict[int, float]] = {}
        for r in rows:
            by_var.setdefault(r["variant"], {})[offset_of(r["week_label"])] = r["p"]
        for variant, series in by_var.items():
            arr = np.full(N_WEEKS, np.nan)
            for o, p in series.items():
                arr[o] = p
            # forward-fill; weeks before the first price stay NaN
            last = np.nan
            for o in range(N_WEEKS):
                if np.isnan(arr[o]):
                    arr[o] = last
                else:
                    last = arr[o]
            med = np.nanmedian(arr[:N_ACTUAL])
            self.rel_price[variant] = arr / med
        self.no_price = np.full(N_WEEKS, np.nan)

    def _load_series(self):
        """ML series = variant x geo x channel with any nonzero ST history,
        excluding NON_ML_VARIANTS. History = clipped-at-zero weekly ST."""
        rows = self.conn.execute(
            "SELECT s.variant, s.geo, s.channel, a.week_label,"
            " SUM(a.units) AS st"
            " FROM actuals a JOIN series s USING (series_id)"
            " WHERE a.metric = 'ST'"
            " GROUP BY s.variant, s.geo, s.channel, a.week_label").fetchall()
        hist: dict[tuple, np.ndarray] = {}
        for r in rows:
            key = (r["variant"], r["geo"], r["channel"])
            if key not in hist:
                hist[key] = np.zeros(N_ACTUAL)
            hist[key][offset_of(r["week_label"])] = max(0.0, r["st"])
        self.all_history = hist                      # every active grain incl. NPI/EOL
        self.history = {k: v for k, v in hist.items()
                        if v.sum() > 0 and k[0] not in NON_ML_VARIANTS}
        self.first_sale = {k: int(np.nonzero(v)[0][0])
                           for k, v in self.history.items()}

    # ---------- row building ----------

    def make_row(self, key: tuple, o: int, hist: np.ndarray) -> list[float]:
        variant, geo, channel = key
        part, cls, rel_o = self.variant_meta[variant]
        fw, fq, wiq = self.week_meta[o]
        ev = self.event_flags[o]
        prices = self.rel_price.get(variant, self.no_price)

        def lag(k):
            return hist[o - k] if o - k >= 0 else np.nan

        def roll(n, fn):
            if o - n < 0:
                return np.nan
            return fn(hist[o - n:o])

        yo = yoy_offset(o)
        lag_yoy = hist[yo] if yo is not None and yo < len(hist) else np.nan
        fs = self.first_sale.get(key)
        wsf = (o - fs) if fs is not None else np.nan

        return ([float(part), float(geo[-1]), float(channel[-1]),
                 float(cls == "core"), float(cls == "one_time_deal"),
                 float(cls == "exclusive"),
                 float(fw), float(fq), float(wiq)]
                + list(ev)
                + [self.any_event[o + 1] if o + 1 < N_WEEKS else 0.0,
                   self.any_event[o - 1] if o - 1 >= 0 else 0.0,
                   prices[o],
                   lag(1), lag(2), lag(3), lag(4), lag(13), lag_yoy,
                   roll(4, np.mean), roll(13, np.mean), roll(4, np.max),
                   float(wsf) if wsf is not None else np.nan,
                   float(o - rel_o) if rel_o is not None else -1.0])

    def training_data(self, end_o: int) -> tuple[np.ndarray, np.ndarray]:
        """Rows for every ML series from the week after its first sale
        through offset end_o (inclusive). Target = clipped weekly ST."""
        X, y = [], []
        for key, hist in self.history.items():
            for o in range(self.first_sale[key] + 1, end_o + 1):
                X.append(self.make_row(key, o, hist))
                y.append(hist[o])
        return np.array(X, dtype=float), np.array(y, dtype=float)
