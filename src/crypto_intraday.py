"""
24/7 crypto intraday backtest engine (position-based, vectorized).

Adapted from src/intraday_vec.py for crypto: markets run continuously, so there
is no daily session reset — VWAP and z-scores use trailing rolling windows, and
positions are not force-flattened at any "close". Costs are crypto-exchange fees.

Cost note: `oneway_cost` defaults to 7.5 bps/side (15 bps round-trip) — a realistic
blended maker/taker fee on a global exchange for an active trader with volume
discounts. Pure taker is ~10 bps/side. (Indian exchanges add a 1% TDS on every
sell + 30% tax — see the report; that alone makes HF crypto hopeless in India.)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ONEWAY_COST = 0.00075   # 7.5 bps per side


def load_btc(parquet="/tmp/btc_min.parquet", start="2018-01-01") -> pd.DataFrame:
    df = pd.read_parquet(parquet)
    df = df[df["Date"] >= pd.Timestamp(start)].sort_values("Date").reset_index(drop=True)
    df = df[df["Close"] > 0]
    return df


def add_features(df: pd.DataFrame, win: int = 120) -> pd.DataFrame:
    """Trailing rolling VWAP z-score + next-bar return. No look-ahead, no day reset."""
    typ = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv = (typ * df["Volume"]).rolling(win, min_periods=win).sum()
    vv = df["Volume"].rolling(win, min_periods=win).sum().replace(0, np.nan)
    df["vwap"] = pv / vv
    dev = df["Close"] - df["vwap"]
    df["z"] = dev / dev.rolling(win, min_periods=win).std()
    df["ret"] = df["Close"].pct_change().fillna(0.0)
    df["fwd_ret"] = df["ret"].shift(-1).fillna(0.0)
    df["date"] = df["Date"].dt.normalize()
    return df


def run_position(df: pd.DataFrame, pos: pd.Series, cost: float = ONEWAY_COST):
    """Net per-DAY return from a target-position series; also returns entries."""
    pos = pos.fillna(0.0)
    prev = pos.shift(1).fillna(0.0)
    turnover = (pos - prev).abs()
    gross = pos * df["fwd_ret"]
    net = gross - turnover * cost
    by_day = pd.DataFrame({
        "net": net.groupby(df["date"]).sum(),
        "gross": gross.groupby(df["date"]).sum(),
        "turnover": turnover.groupby(df["date"]).sum(),
    })
    entries = int(((prev == 0) & (pos != 0)).sum())
    return by_day, entries


def mr_hysteresis(df: pd.DataFrame, z_in=2.0, z_out=0.3) -> pd.Series:
    """Low-turnover mean reversion: fade when |z|>=z_in, hold until |z|<=z_out."""
    z = df["z"]
    desired = pd.Series(np.where(z >= z_in, -1.0, np.where(z <= -z_in, 1.0, 0.0)), index=df.index)
    reset = (z.abs() <= z_out).fillna(True)
    pos = desired.where(desired != 0).groupby(reset.cumsum()).ffill().where(~reset, 0.0).fillna(0.0)
    return pos


def momentum_hysteresis(df: pd.DataFrame, z_in=2.0, z_out=0.3) -> pd.Series:
    """Ride breakouts: go with the move when |z|>=z_in, hold until it fades."""
    z = df["z"]
    desired = pd.Series(np.where(z >= z_in, 1.0, np.where(z <= -z_in, -1.0, 0.0)), index=df.index)
    reset = (z.abs() <= z_out).fillna(True)
    pos = desired.where(desired != 0).groupby(reset.cumsum()).ffill().where(~reset, 0.0).fillna(0.0)
    return pos


def report(by_day: pd.DataFrame, label="", entries=0) -> dict:
    d = by_day["net"].dropna()
    if len(d) == 0 or d.std() == 0:
        return {"strategy": label, "net_bps_per_day": 0.0}
    eq = (1 + d).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "strategy": label,
        "entries": entries,
        "gross_bps_per_day": round(1e4 * by_day["gross"].mean(), 1),
        "net_bps_per_day": round(1e4 * d.mean(), 1),
        "pos_days_%": round(100 * (d > 0).mean(), 1),
        "sharpe": round(d.mean() / d.std() * np.sqrt(365), 2),   # crypto: 365 days
        "ann_return_%": round(100 * d.mean() * 365, 1),
        "maxDD_%": round(100 * dd, 1),
        "hits_0.2%/day": bool(d.mean() >= 0.002),
    }
