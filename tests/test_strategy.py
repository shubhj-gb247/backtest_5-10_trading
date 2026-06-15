"""Unit checks on the 5/10 strategy P&L accounting.

Run with:  python -m pytest tests/ -q   (or)   python tests/test_strategy.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.strategy import StrategyConfig, run_backtest


def _panels(closes, turns=None):
    idx = pd.date_range("2020-01-03", periods=len(next(iter(closes.values()))), freq="W-FRI")
    close = pd.DataFrame(closes, index=idx)
    if turns is None:
        turns = {k: [1e9] * len(close) for k in closes}
    turn = pd.DataFrame(turns, index=idx)
    return {"close": close, "turnover": turn}


def test_long_pnl_no_cost():
    # -10% week -> long size 5 -> next week +20% -> pnl = 5 * 0.20 = 1.0
    panels = _panels({"AAA": [100.0, 90.0, 108.0]})
    res = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=0, cost_bps_per_side=0))
    assert res.weekly["n_long"].iloc[0] == 1
    assert abs(res.weekly["net_pnl"].iloc[0] - 1.0) < 1e-9


def test_short_pnl_no_cost():
    # +15% week -> short size 10 -> next week +5% -> pnl = 10 * (-0.05) = -0.5
    panels = _panels({"AAA": [100.0, 115.0, 120.75]})
    res = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=0, cost_bps_per_side=0))
    assert res.weekly["n_short"].iloc[0] == 1
    assert abs(res.weekly["net_pnl"].iloc[0] - (-0.5)) < 1e-9


def test_costs_reduce_pnl():
    panels = _panels({"AAA": [100.0, 90.0, 108.0]})
    no_cost = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=0, cost_bps_per_side=0))
    with_cost = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=0, cost_bps_per_side=25))
    # round-trip cost on a size-5 long = 5 * 2 * 0.0025 = 0.025
    diff = no_cost.weekly["net_pnl"].iloc[0] - with_cost.weekly["net_pnl"].iloc[0]
    assert abs(diff - 0.025) < 1e-9


def test_no_lookahead_last_week_dropped():
    # The final week has no forward return and must not produce a position row.
    panels = _panels({"AAA": [100.0, 90.0, 80.0]})
    res = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=0, cost_bps_per_side=0))
    assert res.weekly.index.max() < panels["close"].index.max()


def test_liquidity_filter_excludes_illiquid():
    panels = _panels({"AAA": [100.0, 90.0, 108.0]}, turns={"AAA": [1.0, 1.0, 1.0]})
    res = run_backtest(panels, StrategyConfig(min_price=0, min_med_turnover=1e6, cost_bps_per_side=0))
    assert res.weekly.empty or res.weekly["gross_exposure"].sum() == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
