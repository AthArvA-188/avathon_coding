"""Phase 2 tests: metrics, calendar-aware lags, cap enforcement, NPI ramps,
and an end-to-end forecast integration run on a temp DB."""
import numpy as np
import pytest

from planz import forecast as fc
from planz import features as ft
from planz import lifecycle, metrics


# ---------- metrics (hand-computed expectations) ----------

def test_metrics_known_values():
    a = np.array([10.0, 0.0, 20.0])
    f = np.array([8.0, 2.0, 25.0])
    assert metrics.wape(a, f) == pytest.approx((2 + 2 + 5) / 30)
    assert metrics.bias(a, f) == pytest.approx((-2 + 2 + 5) / 30)
    # smape terms: 2/9, 2/1, 5/22.5 -> mean
    assert metrics.smape(a, f) == pytest.approx((2 / 9 + 2 / 1 + 5 / 22.5) / 3)
    # pinball at 0.9: actual>fcst -> 0.9*diff ; actual<fcst -> 0.1*|diff|
    assert metrics.pinball(a, f, 0.9) == pytest.approx(
        (0.9 * 2 + 0.1 * 2 + 0.1 * 5) / 3)
    assert np.isnan(metrics.wape(np.zeros(3), f))


def test_yoy_offset_is_label_based():
    # 2023W05 -> 2022W05 is 52 weeks apart; 2022W05 -> 2021W05 is 53 (fiscal
    # 2021 has 53 weeks); fiscal-2021 weeks have no prior year in the data
    o_2023w05 = ft.offset_of("2023W05")
    o_2022w05 = ft.offset_of("2022W05")
    assert ft.yoy_offset(o_2023w05) == o_2022w05
    assert o_2023w05 - o_2022w05 == 52
    # crossing the 53-week fiscal 2021: 2022W45 -> 2021W45 is 53 weeks apart
    o_2022w45 = ft.offset_of("2022W45")
    assert o_2022w45 - ft.yoy_offset(o_2022w45) == 53
    # prior-year week before the data window (2021W41) has no offset
    assert ft.yoy_offset(o_2022w05) is None
    assert ft.yoy_offset(ft.offset_of("2021W45")) is None


def test_horizon_offsets():
    assert ft.offset_of("2023W40") == 104
    assert ft.offset_of("2024W39") == 155
    assert ft.label_of(104) == "2023W40"
    assert ft.offset_of("2023W49") == lifecycle.NPI_RELEASE_O


# ---------- cap enforcement on synthetic data ----------

def _mk(p50):
    arr = np.array(p50, dtype=float)
    return {"p10": arr * 0.8, "p50": arr.copy(), "p90": arr * 1.2}


def test_apply_caps_partial_and_exhaustion():
    fcst = {("V", "G1", "C3"): _mk([100] * lifecycle.H_N)}
    lifecycle.apply_caps(fcst, [("V", ("G1",), 250.0)])
    p50 = fcst[("V", "G1", "C3")]["p50"]
    assert p50[0] == 100 and p50[1] == 100
    assert p50[2] == pytest.approx(50)              # partial week
    assert p50[3:].sum() == 0                       # exhausted
    assert p50.sum() == pytest.approx(250)
    # p90 scaled by the same factor
    assert fcst[("V", "G1", "C3")]["p90"][2] == pytest.approx(50 * 1.2)


def test_apply_caps_scopes_multiple_series():
    fcst = {("V", "G1", "C1"): _mk([10] * lifecycle.H_N),
            ("V", "G1", "C3"): _mk([30] * lifecycle.H_N),
            ("V", "G2", "C3"): _mk([99] * lifecycle.H_N)}
    lifecycle.apply_caps(fcst, [("V", ("G1",), 60.0)])
    total_g1 = (fcst[("V", "G1", "C1")]["p50"] + fcst[("V", "G1", "C3")]["p50"])
    assert total_g1.sum() == pytest.approx(60)
    # both G1 series share the clip factor pro rata; G2 untouched
    assert fcst[("V", "G1", "C1")]["p50"][1] == pytest.approx(5)
    assert fcst[("V", "G2", "C3")]["p50"].sum() == pytest.approx(99 * lifecycle.H_N)


def test_apply_caps_untouched_when_room():
    fcst = {("V", "G1", "C3"): _mk([1.0] * lifecycle.H_N)}
    lifecycle.apply_caps(fcst, [("V", (), 1e9)])
    assert fcst[("V", "G1", "C3")]["p50"].sum() == pytest.approx(lifecycle.H_N)


# ---------- lifecycle on the real (temp) DB ----------

@pytest.fixture(scope="module")
def fb(conn):
    return ft.FeatureBuilder(conn)


def test_npi_ramps_hit_deal_volumes(conn, fb):
    npi = lifecycle.npi_forecasts(conn, fb)
    v10 = sum(v["p50"].sum() for k, v in npi.items() if k[0] == "Variant V10")
    v11 = sum(v["p50"].sum() for k, v in npi.items() if k[0] == "Variant V11")
    assert v10 == pytest.approx(57_407, rel=1e-6)
    assert v11 == pytest.approx(23_689, rel=1e-6)
    for k, v in npi.items():
        # nothing before release week; Ch3 carries the volume
        assert v["p50"][:lifecycle.NPI_RELEASE_O - lifecycle.H_START].sum() == 0
        if k[2] != "Channel 3":
            assert v["p50"].sum() == 0
        assert np.all(v["p10"] <= v["p50"]) and np.all(v["p50"] <= v["p90"])


def test_npi_ramp_shape(conn, fb):
    # the normalization makes totals blind to shape — a flat ramp passes the
    # volume test — so pin the shape itself (mutation-proven gap)
    npi = lifecycle.npi_forecasts(conn, fb)
    ramp = npi[("Variant V10", "Geo G1", "Channel 3")]["p50"]
    rel_i = lifecycle.NPI_RELEASE_O - lifecycle.H_START      # 2023W49
    assert ramp[rel_i] > 0                                   # launches on time
    # peak lands in the Black Friday / XMAS cluster (2024W08..2024W13),
    # not at release and not on a flat plateau
    peak = int(np.argmax(ramp))
    lo = ft.offset_of("2024W08") - lifecycle.H_START
    hi = ft.offset_of("2024W13") - lifecycle.H_START
    assert lo <= peak <= hi, f"peak at horizon week {peak}"
    assert ramp[peak] > 3 * ramp[rel_i]                      # real ramp-up
    # launch is not front-loaded: first 4 weeks carry a small share
    assert ramp[rel_i:rel_i + 4].sum() < 0.15 * ramp.sum()


def test_seasonal_index_peaks_in_holiday_quarter(fb):
    idx = lifecycle.seasonal_index(fb)
    bf = idx[ft.offset_of("2024W09")]               # Black Friday
    lull = idx[ft.offset_of("2024W20")]             # mid Q2
    assert bf > 2.0 > lull


def test_cap_specs_remaining_volumes(conn):
    specs = {(v, g): r for v, g, r in lifecycle.cap_specs(conn)}
    # OTD remaining = lifetime total - net sold (D23)
    assert specs[("Variant V5", ())] == pytest.approx(38_000 - 35_516)
    assert specs[("Variant V7", ())] == pytest.approx(22_000 - 20_983)
    # exclusives: stated per-geo numbers are forward volumes
    assert specs[("Variant V8", ("Geo G1",))] == 13_832
    assert specs[("Variant V10", ("Geo G1",))] == 55_332


# ---------- end-to-end forecast integration ----------
# (forecast_db fixture lives in conftest.py, shared with the MPS tests)

def test_forecast_integration(forecast_db):
    info, db_path = forecast_db
    import sqlite3
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        n = c.execute("SELECT COUNT(*) FROM forecast").fetchone()[0]
        # pin the series universe: 124 active grains x 52 weeks
        assert n == info["forecast_rows"] == 124 * 52
        assert c.execute("SELECT COUNT(*) FROM forecast WHERE p10 > p50"
                         " OR p50 > p90 OR p10 < 0").fetchone()[0] == 0
        assert c.execute("SELECT SUM(ABS(p50)) FROM forecast"
                         " WHERE variant = 'Variant V12'").fetchone()[0] == 0
        # absolute accuracy bands, not just ordering (mutation-proven gap:
        # dropping the sample weights kept the ordering while bias went -30%)
        scores = {r[0]: r for r in c.execute(
            "SELECT model, wape, bias, pinball10, pinball90"
            " FROM forecast_scores WHERE scope_type = 'overall'")}
        assert scores["xgb"][1] < 0.42                       # baseline 0.376
        assert abs(scores["xgb"][2]) < 0.10                  # baseline +0.033
        # canary: baseline model pins data/feature alignment
        assert scores["seasonal_naive"][1] == pytest.approx(0.507, abs=0.02)
        assert scores["xgb"][1] < scores["seasonal_naive"][1] < scores["naive"][1]
        # quantile bands exist and are not collapsed
        assert 0 < scores["xgb"][3] and 0 < scores["xgb"][4]
        band = c.execute("SELECT AVG(p90 - p10) FROM forecast"
                         " WHERE p50 > 0").fetchone()[0]
        assert band > 1.0
        # horizon level sanity: catches recursion feedback bugs
        total = c.execute("SELECT SUM(p50) FROM forecast").fetchone()[0]
        assert 800_000 < total < 1_150_000                   # baseline 952,860
        # cap compliance: horizon totals within remaining volumes
        v5 = c.execute("SELECT SUM(p50) FROM forecast"
                       " WHERE variant = 'Variant V5'").fetchone()[0]
        assert v5 <= (38_000 - 35_516) + 1e-6
        v10 = c.execute("SELECT SUM(p50) FROM forecast"
                        " WHERE variant = 'Variant V10'").fetchone()[0]
        assert v10 == pytest.approx(57_407, rel=1e-6)
    finally:
        c.close()
