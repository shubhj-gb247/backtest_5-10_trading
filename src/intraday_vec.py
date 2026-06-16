"""
Fast, vectorized intraday backtester (position-based) for real 1-minute NSE data.

Instead of looping trade-by-trade, a strategy is expressed as a *target
position* series p_t in [-1, +1] known at bar t; it earns the next bar's return
r_{t+1}, and every change |p_t - p_{t-1}| pays a one-way cost. Positions are
forced flat at the end of each day (intraday only). This makes it cheap to sweep
signals/parameters and to measure the honest net-of-cost daily return.

Cost: one-way 8.3 bps (half of the 16.6 bps round-trip from src/intraday.py,
which already bakes in brokerage, STT, exchange/SEBI/stamp, GST and 3 bps/side
slippage). Turnover is charged per unit of position change.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MIN_DIR = Path("/tmp/nsemin")
ONEWAY_COST = 0.00083   # 8.3 bps per unit turnover (one side)


def load_min(symbol: str, start: str = "2018-01-01") -> pd.DataFrame:
    df = pd.read_parquet(MIN_DIR / f"{symbol}.parquet",
                         columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[df["Date"] >= pd.Timestamp(start)].sort_values("Date").reset_index(drop=True)
    df["day"] = df["Date"].dt.normalize()
    df["minute"] = df["Date"].dt.hour * 60 + df["Date"].dt.minute
    return df


def add_intraday_features(df: pd.DataFrame, vwap_win: int = 20, skip_open: int = 15) -> pd.DataFrame:
    """Per-day VWAP z-score and within-day forward return. No look-ahead."""
    g = df.groupby("day", sort=False)
    typ = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = (typ * df["Volume"]).groupby(df["day"]).cumsum()
    vv = df["Volume"].groupby(df["day"]).cumsum().replace(0, np.nan)
    df["vwap"] = pv / vv
    dev = df["Close"] - df["vwap"]
    # rolling std of the deviation, within day
    df["dev"] = dev
    df["dev_std"] = (
        dev.groupby(df["day"]).transform(lambda s: s.rolling(vwap_win, min_periods=vwap_win).std())
    )
    df["z"] = df["dev"] / df["dev_std"]
    # within-day next-bar return (the position entered at t earns this)
    ret = df["Close"].pct_change()
    # zero out the cross-day boundary (first bar of each day has no valid prev)
    first_of_day = df["day"].ne(df["day"].shift(1))
    ret[first_of_day] = 0.0
    df["ret"] = ret
    df["fwd_ret"] = df.groupby("day", sort=False)["ret"].shift(-1).fillna(0.0)
    # mask: no trading in the first `skip_open` minutes (let VWAP/std stabilise)
    minute_in_day = df.groupby("day", sort=False).cumcount()
    df["tradable"] = minute_in_day >= skip_open
    df["last_bar"] = df["day"].ne(df["day"].shift(-1))
    return df


def run_position(df: pd.DataFrame, pos: pd.Series, cost: float = ONEWAY_COST) -> pd.Series:
    """Given a target-position series, return per-DAY net return (sum of bar
    P&L minus turnover cost), flattening at each day's last bar."""
    pos = pos.where(df["tradable"], 0.0).fillna(0.0)
    pos = pos.where(~df["last_bar"], 0.0)          # flat into the close
    pnl = pos * df["fwd_ret"]
    prev = pos.groupby(df["day"], sort=False).shift(1).fillna(0.0)
    turnover = (pos - prev).abs()
    net = pnl - turnover * cost
    return net.groupby(df["day"], sort=False).sum()


def mean_reversion_pos(df: pd.DataFrame, z_enter: float = 1.5, scale: float = 1.0) -> pd.Series:
    """Fade deviations from VWAP: short when rich (z>0), long when cheap (z<0).
    Position magnitude ramps with |z| up to 1, only past the entry threshold."""
    z = df["z"]
    mag = np.clip((z.abs() - z_enter) / max(scale, 1e-9), 0, 1)
    return (-np.sign(z) * mag).fillna(0.0)


def momentum_pos(df: pd.DataFrame, z_enter: float = 1.5, scale: float = 1.0) -> pd.Series:
    """Ride deviations from VWAP (the opposite of mean reversion)."""
    z = df["z"]
    mag = np.clip((z.abs() - z_enter) / max(scale, 1e-9), 0, 1)
    return (np.sign(z) * mag).fillna(0.0)


def mr_hysteresis_pos(df: pd.DataFrame, z_enter: float = 2.0, z_exit: float = 0.3) -> pd.Series:
    """Low-turnover mean reversion: ENTER (fade) when |z| >= z_enter, HOLD until
    |z| <= z_exit (reverted to VWAP) or end of day, then go flat. Within a hold
    block the side is fixed at the first entry, so it trades only a couple of
    times a day instead of every minute.
    """
    z = df["z"]
    desired = np.where(z >= z_enter, -1.0, np.where(z <= -z_enter, 1.0, 0.0))
    desired = pd.Series(desired, index=df.index)

    # Blocks reset whenever the position should be flat: reverted, or day boundary.
    reset = (z.abs() <= z_exit) | (~df["tradable"]) | df["last_bar"]
    reset = reset.fillna(True)
    grp = reset.cumsum()

    # Within each block, hold the FIRST non-zero entry side, forward-filled.
    entry_side = desired.where(desired != 0.0)
    pos = entry_side.groupby(grp).ffill()
    # Zero out bars at/under the reset (flat) and before the first entry.
    pos = pos.where(~reset, 0.0).fillna(0.0)
    return pos


def run_position_full(df: pd.DataFrame, pos: pd.Series, cost: float = ONEWAY_COST):
    """Like run_position but also returns per-day turnover and gross, plus the
    total number of round-trip trades (entries)."""
    pos = pos.where(df["tradable"], 0.0).fillna(0.0)
    pos = pos.where(~df["last_bar"], 0.0)
    prev = pos.groupby(df["day"], sort=False).shift(1).fillna(0.0)
    turnover = (pos - prev).abs()
    gross = pos * df["fwd_ret"]
    net = gross - turnover * cost
    by_day = pd.DataFrame({
        "net": net.groupby(df["day"], sort=False).sum(),
        "gross": gross.groupby(df["day"], sort=False).sum(),
        "turnover": turnover.groupby(df["day"], sort=False).sum(),
    })
    # an entry = a transition from flat to non-flat
    entries = ((prev == 0) & (pos != 0)).sum()
    return by_day, int(entries)


def daily_report(daily: pd.Series, label: str = "") -> dict:
    daily = daily.dropna()
    if len(daily) == 0 or daily.std() == 0:
        return {"label": label, "days": int(len(daily)), "mean_bps": 0.0}
    ann = daily.mean() * 252
    sharpe = daily.mean() / daily.std() * np.sqrt(252)
    eq = (1 + daily).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "label": label,
        "days": int(len(daily)),
        "mean_bps": round(1e4 * daily.mean(), 2),
        "median_bps": round(1e4 * daily.median(), 2),
        "pos_days_%": round(100 * (daily > 0).mean(), 1),
        "sharpe_ann": round(sharpe, 2),
        "ann_ret_%": round(100 * ann, 1),
        "maxDD_%": round(100 * dd, 1),
        "final_x": round(eq.iloc[-1], 3),
    }
