"""Run-out WOS calculator tests (docs D11) — correctness matters most here:
the MPS targets and all reporting derive from these two functions."""
import pytest

from planz import wos


def test_exact_cover():
    assert wos.run_out_wos(30, [10, 10, 10, 10]) == 3.0


def test_fractional_cover():
    assert wos.run_out_wos(25, [10, 10, 10]) == 2.5


def test_zero_demand_weeks_are_free():
    # 5 units cover the zero week for free, then half of the 10-unit week
    assert wos.run_out_wos(5, [0, 10, 10]) == pytest.approx(1.5)
    # all-zero forward demand: capped at the window length
    assert wos.run_out_wos(5, [0, 0, 0]) == 3.0


def test_spiky_demand_vs_average_window():
    # 100 units, flat 10/wk -> 10 weeks; same 100 before a 90-unit spike -> ~2
    assert wos.run_out_wos(100, [10] * 12) == 10.0
    assert wos.run_out_wos(100, [10, 90, 10, 10]) == pytest.approx(2.0)


def test_edge_cases():
    assert wos.run_out_wos(0, [10, 10]) == 0.0
    assert wos.run_out_wos(-5, [10]) == 0.0
    assert wos.run_out_wos(1000, [10, 10]) == 2.0        # capped at window
    assert wos.run_out_wos(5, []) == 0.0


def test_target_stock_is_inverse_of_run_out():
    fwd = [5, 0, 20, 10, 10, 30, 10]
    for n in (1, 3, 5, 7):
        t = wos.target_stock(fwd, n)
        assert t == sum(fwd[:n])
        assert wos.run_out_wos(t, fwd) >= n              # covers >= n weeks
