"""Fiscal calendar tests. The Strong Seasonality Weeks sheet provides ground
truth: for every event-year it lists both the quarter-week ('2023_Q1_09') and
the year-week ('2023_09'), which must agree with our quarter mapping —
including fiscal 2021's 53-week year with a 14-week Q1."""
import re

import pytest

from planz import calendar as cal
from planz import params


def test_roundtrip_and_validation():
    assert cal.parse_week("2023W40") == (2023, 40)
    assert cal.week_label(2023, 40) == "2023W40"
    with pytest.raises(ValueError):
        cal.parse_week("2023W54")
    with pytest.raises(ValueError):
        cal.parse_week("2022W53")  # only fiscal 2021 has 53 weeks
    assert cal.parse_week("2021W53") == (2021, 53)


def test_year_lengths_and_range():
    assert cal.weeks_in_year(2021) == 53
    assert cal.weeks_in_year(2022) == 52
    labels = cal.week_range("2021W41", "2024W39")
    assert len(labels) == 156                      # matches the data sheet
    assert labels[0] == "2021W41" and labels[-1] == "2024W39"
    assert "2021W53" in labels and "2022W53" not in labels


def test_add_weeks_across_boundaries():
    assert cal.add_weeks("2021W53", 1) == "2022W01"
    assert cal.add_weeks("2022W01", -1) == "2021W53"
    assert cal.add_weeks("2023W52", 1) == "2024W01"
    assert cal.add_weeks("2023W40", 51) == "2024W39"


def test_quarter_mapping_matches_seasonality_sheet(raw_xl):
    s = raw_xl.parse("Strong Seasonality Weeks", header=None)
    # The two fiscal-2024 Promo Q4 rows are internally inconsistent in the
    # sheet itself (2024_Q4_02<->W42 implies Q4 starts W41; 2024_Q4_03<->W44
    # implies W42; every other 2024 row implies the standard W40). Both lie
    # beyond the data range and the horizon — excluded here, flagged as an
    # open client question in docs.
    skip = {("2024_Q4_02", "2024_42"), ("2024_Q4_03", "2024_44")}
    checked = 0
    for col in range(1, s.shape[1], 2):
        for r in range(2, s.shape[0]):
            qtr_wk, cy_wk = s.iat[r, col], s.iat[r, col + 1]
            if not isinstance(qtr_wk, str) or (qtr_wk, cy_wk) in skip:
                continue
            year, q, wiq = re.match(r"^(\d{4})_Q(\d)_(\d{2})$", qtr_wk).groups()
            wy, wk = cy_wk.split("_")
            assert year == wy
            label = cal.week_label(int(wy), int(wk))
            assert cal.fiscal_qtr_week(label) == (int(q), int(wiq)), (
                f"{label}: sheet says Q{q} wk {wiq}")
            checked += 1
    assert checked == 50                    # 13 events x 4 years, minus 2


def test_horizon_is_four_clean_quarters():
    labels = cal.week_range(params.HORIZON_START, params.HORIZON_END)
    assert len(labels) == 52
    quarters = [cal.quarter_label(w) for w in labels]
    assert list(dict.fromkeys(quarters)) == ["2023Q4", "2024Q1", "2024Q2", "2024Q3"]
    assert all(quarters.count(q) == 13 for q in set(quarters))
    # actuals end exactly at a quarter boundary
    assert cal.fiscal_qtr_week(params.LAST_ACTUAL_WEEK) == (3, 13)


def test_scenario_window():
    start = params.HORIZON_START
    window = [cal.add_weeks(start, i) for i in range(params.SCENARIO_N_WEEKS)]
    assert window == ["2023W40", "2023W41", "2023W42",
                      "2023W43", "2023W44", "2023W45"]


def test_approx_dates_anchor():
    # Pricing sheet: fiscal 2021W43 contains Tue 2021-07-20
    assert cal.approx_monday("2021W43").isoformat() == "2021-07-19"
    assert cal.approx_monday("2021W01").isoformat() == "2020-09-28"
    # holiday sanity: fiscal Q1 W09 (Black Friday-ish) lands in late November
    assert cal.approx_monday("2023W09").month == 11
