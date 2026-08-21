"""Weeks-of-supply, run-out convention (docs D11): how many future weeks the
current stock covers, walking forward through the demand curve. Robust to
holiday spikes where a fixed-window average misstates coverage."""
from __future__ import annotations

from collections.abc import Sequence


def run_out_wos(stock: float, forward_demand: Sequence[float]) -> float:
    """Weeks covered by `stock` against the coming weekly demands.
    Zero-demand weeks are covered for free; a partially covered week counts
    fractionally; result is capped at len(forward_demand)."""
    if stock < 0:
        return 0.0
    remaining = float(stock)
    cover = 0.0
    for d in forward_demand:
        if d <= 0:
            cover += 1.0
            continue
        if remaining >= d:
            remaining -= d
            cover += 1.0
        else:
            cover += remaining / d
            break
    return cover


def target_stock(forward_demand: Sequence[float], wos: int) -> float:
    """Stock level whose run-out WOS equals `wos`: the sum of the next
    `wos` weeks of demand. Linear in demand, so usable inside the MILP."""
    return float(sum(forward_demand[:wos]))
