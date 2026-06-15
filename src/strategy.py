"""
The "5/10" weekly mean-reversion strategy.

Described by HFT trader Manu Narang: across a very large universe of stocks,
each week,

    * BUY  a small fixed amount of any stock that FELL >= 5% last week
      (betting the drop mean-reverts up), and
    * SELL (short) a larger fixed amount of any stock that ROSE >= 10% last week
      (betting the spike mean-reverts down).

Positions are held for the following week and then re-evaluated. The asymmetry
(buy 5 on a -5% move, sell 10 on a +10% move) reflects that sharp up-spikes tend
to revert harder than down-moves. Profit comes from a small statistical edge
repeated across thousands of near-uncorrelated micro-positions, which is why the
P&L is steady even though winners barely outnumber losers.

This module is pure: it takes weekly panels in and returns a tidy weekly results
frame. All economic assumptions live in `StrategyConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class StrategyConfig:
    # --- signal thresholds (prior-week return) ---
    long_drop: float = -0.05      # buy if last week's return <= -5%
    short_rise: float = 0.10      # short if last week's return >= +10%

    # --- position sizing (relative cash units per qualifying name) ---
    long_size: float = 5.0        # "$5" long per long signal
    short_size: float = 10.0      # "$10" short per short signal

    # --- tradable-universe (liquidity) filters, applied at signal time ---
    min_price: float = 20.0           # rupee price floor (avoid penny stocks)
    min_med_turnover: float = 2.5e6   # min median daily turnover, INR (~25 lakh)
    turnover_lookback: int = 4        # weeks used to measure typical turnover

    # --- sanity clamp on the prior-week return used as a signal ---
    # Guards against un-adjusted corporate-action jumps masquerading as signals.
    max_abs_signal_ret: float = 0.60

    # --- costs ---
    cost_bps_per_side: float = 25.0   # round-trip = 2x this, charged on notional

    # --- capital convention for the equity curve ---
    # Weekly return = weekly P&L / capital_base. If None, capital_base is set to
    # the average weekly gross exposure (=> ~1x average gross leverage).
    capital_base: float | None = None


@dataclass
class BacktestResult:
    weekly: pd.DataFrame          # per-week P&L, exposure, counts, returns
    config: StrategyConfig
    capital_base: float
    trades_long: int
    trades_short: int


def _weekly_returns(close: pd.DataFrame) -> pd.DataFrame:
    """Simple weekly returns, with obviously-bad prices removed."""
    px = close.where(close > 0)
    return px.pct_change()


def run_backtest(panels: dict[str, pd.DataFrame], cfg: StrategyConfig) -> BacktestResult:
    close = panels["close"]
    turnover = panels["turnover"]

    ret = _weekly_returns(close)                 # ret[t] = return realised over week t
    fwd = ret.shift(-1)                          # fwd[t] = return realised over week t+1

    # Typical recent liquidity, known as of week t (no look-ahead).
    med_turn = turnover.rolling(cfg.turnover_lookback, min_periods=1).median()

    # Universe mask at signal time t: priced, liquid, and with a valid signal.
    priced = close >= cfg.min_price
    liquid = med_turn >= cfg.min_med_turnover
    valid_sig = ret.abs() <= cfg.max_abs_signal_ret
    has_fwd = fwd.notna()

    eligible = priced & liquid & valid_sig & has_fwd & ret.notna()

    long_mask = eligible & (ret <= cfg.long_drop)
    short_mask = eligible & (ret >= cfg.short_rise)

    # Per-name P&L realised next week, in cash units (costs handled below).
    roundtrip = 2.0 * cfg.cost_bps_per_side / 1e4
    long_cost = cfg.long_size * roundtrip
    short_cost = cfg.short_size * roundtrip

    long_pnl = (long_mask * (cfg.long_size * fwd - long_cost)).sum(axis=1)
    short_pnl = (short_mask * (cfg.short_size * (-fwd) - short_cost)).sum(axis=1)

    n_long = long_mask.sum(axis=1)
    n_short = short_mask.sum(axis=1)

    gross_pnl = (long_mask * (cfg.long_size * fwd)).sum(axis=1) + (
        short_mask * (cfg.short_size * (-fwd))
    ).sum(axis=1)
    costs = n_long * long_cost + n_short * short_cost
    net_pnl = gross_pnl - costs

    gross_exposure = n_long * cfg.long_size + n_short * cfg.short_size

    weekly = pd.DataFrame(
        {
            "n_long": n_long,
            "n_short": n_short,
            "gross_exposure": gross_exposure,
            "gross_pnl": gross_pnl,
            "costs": costs,
            "net_pnl": net_pnl,
        }
    )

    # The last row has no forward return; drop weeks with no positions/forward.
    weekly = weekly[weekly["gross_exposure"] > 0].copy()

    capital_base = cfg.capital_base
    if capital_base is None:
        capital_base = float(weekly["gross_exposure"].mean())

    # Two return conventions:
    #   ret_on_exposure -- net P&L / capital actually deployed that week. This is
    #     the leverage-neutral "constant fully-invested capital" curve and is the
    #     fair basis for Sharpe / drawdown (it isolates edge from leverage).
    #   ret_on_capital  -- net P&L / a fixed capital base, i.e. the *literal*
    #     fixed-cash-per-name sizing where weekly gross exposure floats freely.
    #     Reported for reference; its volatility largely reflects that floating
    #     leverage rather than the strategy's edge.
    weekly["ret_on_exposure"] = weekly["net_pnl"] / weekly["gross_exposure"]
    weekly["ret_on_capital"] = weekly["net_pnl"] / capital_base
    weekly["equity"] = (1.0 + weekly["ret_on_exposure"]).cumprod()

    return BacktestResult(
        weekly=weekly,
        config=cfg,
        capital_base=capital_base,
        trades_long=int(n_long.sum()),
        trades_short=int(n_short.sum()),
    )
