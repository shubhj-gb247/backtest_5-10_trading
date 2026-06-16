"""
Intraday backtest testbed on real 1-minute NSE data.

Purpose: let you test any intraday rule against the *real* cost of trading in
India, and see the honest distribution of daily returns — specifically, how
often (if ever) a strategy clears +1% net on the day.

Data: 1-minute OHLCV parquet per symbol (Date, Open, High, Low, Close, Volume),
2018-2025, from the ganeshbiyer/Nse_Historical_Data dataset.

The worked example is Opening-Range Breakout (ORB), the single most common
"make 1% a day intraday" retail strategy: define the high/low of the first N
minutes, go long on a break above / short on a break below, exit at a target,
a stop, or the close. Swap in your own `signal_*` to test other ideas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

MIN_DIR = Path("/tmp/nsemin")


# --------------------------------------------------------------------------- #
# Realistic Indian intraday cost model (fraction of traded notional)
# --------------------------------------------------------------------------- #
def roundtrip_cost_frac(notional: float, slippage_bps_per_side: float = 3.0) -> float:
    """All-in round-trip cost as a fraction of notional for an intraday equity
    trade on a discount broker (Zerodha-style), including slippage.
    """
    brokerage = min(0.0003 * notional, 20.0) * 2        # 0.03% or Rs20 cap, both legs
    stt = 0.00025 * notional                            # 0.025%, sell side only
    txn = 0.0000297 * notional * 2                      # NSE exchange txn, both legs
    sebi = 0.000001 * notional * 2                      # SEBI turnover fee
    stamp = 0.00003 * notional                          # 0.003%, buy side
    gst = 0.18 * (brokerage + txn + sebi)               # 18% GST on charges
    slippage = (slippage_bps_per_side / 1e4) * notional * 2
    return (brokerage + stt + txn + sebi + stamp + gst + slippage) / notional


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_minute(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    df = pd.read_parquet(MIN_DIR / f"{symbol}.parquet",
                         columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["day"] = df["Date"].dt.normalize()
    df["t"] = df["Date"].dt.strftime("%H:%M")
    if start:
        df = df[df["Date"] >= pd.Timestamp(start)]
    if end:
        df = df[df["Date"] <= pd.Timestamp(end)]
    return df


# --------------------------------------------------------------------------- #
# Strategy: Opening-Range Breakout
# --------------------------------------------------------------------------- #
@dataclass
class ORBConfig:
    or_minutes: int = 15          # opening range = first N minutes (09:15..)
    target_R: float = 1.0         # take-profit = R x (opening-range width)
    stop_R: float = 1.0           # stop-loss   = R x (opening-range width)
    allow_long: bool = True
    allow_short: bool = True
    entry_cutoff: str = "14:30"   # no new entries after this
    square_off: str = "15:15"     # force exit time
    slippage_bps_per_side: float = 3.0
    notional: float = 50000.0     # per-trade notional (e.g. 10k capital x5 MIS)


def backtest_orb(df: pd.DataFrame, cfg: ORBConfig) -> pd.DataFrame:
    """Run ORB day by day. Returns one row per trade with gross/net returns."""
    cost = roundtrip_cost_frac(cfg.notional, cfg.slippage_bps_per_side)
    trades = []

    for day, g in df.groupby("day", sort=True):
        g = g.reset_index(drop=True)
        opening = g[g["Date"] < g["Date"].iloc[0] + pd.Timedelta(minutes=cfg.or_minutes)]
        if len(opening) < cfg.or_minutes:
            continue
        or_high = opening["High"].max()
        or_low = opening["Low"].min()
        width = or_high - or_low
        if width <= 0:
            continue

        post = g[g["Date"] >= g["Date"].iloc[0] + pd.Timedelta(minutes=cfg.or_minutes)]
        side = None
        entry_px = stop_px = tgt_px = None

        for _, bar in post.iterrows():
            tm = bar["t"]
            if side is None:
                if tm > cfg.entry_cutoff:
                    break
                # Breakout entry at the bar that breaches the range.
                if cfg.allow_long and bar["High"] > or_high:
                    side, entry_px = 1, or_high
                    tgt_px = or_high + cfg.target_R * width
                    stop_px = or_high - cfg.stop_R * width
                elif cfg.allow_short and bar["Low"] < or_low:
                    side, entry_px = -1, or_low
                    tgt_px = or_low - cfg.target_R * width
                    stop_px = or_low + cfg.stop_R * width
                if side is not None:
                    exit_px, reason = None, None
                    continue
            else:
                # In a position: check stop/target within the bar (stop first = conservative).
                if side == 1:
                    if bar["Low"] <= stop_px:
                        exit_px, reason = stop_px, "stop"
                    elif bar["High"] >= tgt_px:
                        exit_px, reason = tgt_px, "target"
                else:
                    if bar["High"] >= stop_px:
                        exit_px, reason = stop_px, "stop"
                    elif bar["Low"] <= tgt_px:
                        exit_px, reason = tgt_px, "target"
                if exit_px is not None:
                    pass
                else:
                    if tm >= cfg.square_off:
                        exit_px, reason = bar["Close"], "eod"
                if exit_px is not None:
                    gross = side * (exit_px / entry_px - 1.0)
                    trades.append({"day": day, "side": side, "reason": reason,
                                   "gross_ret": gross, "net_ret": gross - cost})
                    side = None
                    break

        # Open position never exited (no square-off bar matched): close at last bar.
        if side is not None:
            last = post.iloc[-1]
            gross = side * (last["Close"] / entry_px - 1.0)
            trades.append({"day": day, "side": side, "reason": "eod_last",
                           "gross_ret": gross, "net_ret": gross - cost})

    return pd.DataFrame(trades)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def per_trade_stats(tr: pd.DataFrame, cfg: ORBConfig) -> dict:
    cost = roundtrip_cost_frac(cfg.notional, cfg.slippage_bps_per_side)
    n = len(tr)
    if n == 0:
        return {"trades": 0}
    return {
        "trades": n,
        "win_rate_%": round(100 * (tr["net_ret"] > 0).mean(), 1),
        "gross_avg_bps": round(1e4 * tr["gross_ret"].mean(), 2),
        "cost_bps": round(1e4 * cost, 2),
        "net_avg_bps": round(1e4 * tr["net_ret"].mean(), 2),
        "net_med_bps": round(1e4 * tr["net_ret"].median(), 2),
        "expectancy_Rs_per_trade": round(tr["net_ret"].mean() * cfg.notional, 1),
    }


def daily_stats(tr: pd.DataFrame, leverage: float = 5.0) -> dict:
    """Aggregate trades to daily account returns (net_ret is on notional;
    account return = leverage x notional return since notional = leverage x capital)."""
    if len(tr) == 0:
        return {"days": 0}
    daily = tr.groupby("day")["net_ret"].sum() * leverage
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "days": int(daily.shape[0]),
        "mean_daily_%": round(100 * daily.mean(), 3),
        "median_daily_%": round(100 * daily.median(), 3),
        "std_daily_%": round(100 * daily.std(), 2),
        "pos_days_%": round(100 * (daily > 0).mean(), 1),
        "days_ge_+1%": round(100 * (daily >= 0.01).mean(), 1),
        "best_day_%": round(100 * daily.max(), 2),
        "worst_day_%": round(100 * daily.min(), 2),
        "final_equity_x": round(eq.iloc[-1], 3),
        "max_drawdown_%": round(100 * dd, 1),
    }
