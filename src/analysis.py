"""Robustness analyses: cost sensitivity, threshold grid, and the core
forward-return diagnostic that explains *why* the strategy behaves as it does."""

from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from src.strategy import StrategyConfig, run_backtest


def cost_sensitivity(panels, base: StrategyConfig, costs_bps=(0, 5, 10, 15, 25, 40)) -> pd.DataFrame:
    rows = []
    for cb in costs_bps:
        cfg = StrategyConfig(**{**asdict(base), "cost_bps_per_side": float(cb)})
        w = run_backtest(panels, cfg).weekly
        rows.append({
            "cost_bps_per_side": cb,
            "mean_weekly_ret_bps": round(1e4 * w["ret_on_exposure"].mean(), 2),
            "weekly_win_pct": round(100 * (w["net_pnl"] > 0).mean(), 1),
            "total_net_pnl": round(w["net_pnl"].sum(), 1),
            "final_equity": round(w["equity"].iloc[-1], 4),
        })
    return pd.DataFrame(rows)


def threshold_grid(panels, base: StrategyConfig,
                   drops=(-0.03, -0.05, -0.08, -0.10),
                   rises=(0.05, 0.08, 0.10, 0.15)) -> pd.DataFrame:
    """Grid of mean weekly return-on-exposure (bps) over signal thresholds."""
    rows = []
    for d in drops:
        for r in rises:
            cfg = StrategyConfig(**{**asdict(base), "long_drop": d, "short_rise": r})
            w = run_backtest(panels, cfg).weekly
            rows.append({
                "long_drop": d, "short_rise": r,
                "mean_weekly_ret_bps": round(1e4 * w["ret_on_exposure"].mean(), 2),
                "weekly_win_pct": round(100 * (w["net_pnl"] > 0).mean(), 1),
            })
    return pd.DataFrame(rows)


def signal_forward_returns(panels, base: StrategyConfig) -> pd.DataFrame:
    """Average *next-week* return of stocks bucketed by *prior-week* return,
    inside the tradable universe. This is the acid test for mean reversion:
    reversion would make big losers' forward returns positive and big winners'
    forward returns negative. Momentum/continuation does the opposite.
    """
    close = panels["close"]
    turnover = panels["turnover"]
    ret = close.where(close > 0).pct_change()
    fwd = ret.shift(-1)
    med_turn = turnover.rolling(base.turnover_lookback, min_periods=1).median()

    elig = (close >= base.min_price) & (med_turn >= base.min_med_turnover) \
        & (ret.abs() <= base.max_abs_signal_ret) & fwd.notna() & ret.notna()

    edges = [-np.inf, -0.10, -0.05, -0.02, 0.02, 0.05, 0.10, np.inf]
    labels = ["< -10%", "-10..-5%", "-5..-2%", "-2..+2%", "+2..+5%", "+5..+10%", "> +10%"]

    r_flat = ret.where(elig).stack()
    f_flat = fwd.where(elig).stack()
    df = pd.DataFrame({"prior": r_flat, "fwd": f_flat}).dropna()
    df["bucket"] = pd.cut(df["prior"], bins=edges, labels=labels)

    g = df.groupby("bucket", observed=True)["fwd"]
    out = pd.DataFrame({
        "n_obs": g.size(),
        "mean_fwd_ret_pct": (g.mean() * 100).round(3),
        "median_fwd_ret_pct": (g.median() * 100).round(3),
        "pct_positive": (g.apply(lambda s: (s > 0).mean()) * 100).round(1),
    }).reset_index()
    return out
