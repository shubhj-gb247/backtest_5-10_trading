#!/usr/bin/env python3
"""
"Can a strategy make 0.2-0.7% NET per day?" — an exhaustive, honest study.

Targets ~0.2-0.7% net/day (= ~65% to ~490% per year). We hunt across four
short-horizon strategy families on real data and measure the net-of-cost daily
return. The recurring result: the predictable per-trade edge in liquid NSE names
is a *fraction* of the round-trip cost, so anything that trades often loses; only
low-frequency strategies clear costs, and they deliver ~0.06-0.08%/day, not 0.2%+.

Families tested:
  A. Intraday single-name mean-reversion to VWAP   (1-min data)
  B. Intraday single-name momentum (VWAP breakout)  (1-min data)
  C. Intraday market-neutral pairs (stat-arb)       (1-min data)
  D. Overnight (daily) market-neutral pairs         (EOD data)  <- the best shot

Run: python run_daily_target_study.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.intraday_vec import (
    ONEWAY_COST, add_intraday_features, load_min,
    mean_reversion_pos, momentum_pos, run_position,
)

EOD = Path("/tmp/eod2_data/daily")
OUT = Path("output/daily_target")
OUT.mkdir(parents=True, exist_ok=True)

SINGLE = ["RELIANCE", "HDFCBANK", "SBIN", "ICICIBANK", "TCS", "MARUTI"]
IPAIRS = [("BANKBARODA", "PNB"), ("SBIN", "BANKBARODA"), ("HCLTECH", "WIPRO"), ("TCS", "INFY")]
DPAIRS = [("BANKBARODA", "PNB"), ("SBIN", "BANKBARODA"), ("HCLTECH", "WIPRO"), ("TCS", "INFY"),
          ("HDFCBANK", "ICICIBANK"), ("AXISBANK", "ICICIBANK"), ("KOTAKBANK", "HDFCBANK"), ("INFY", "WIPRO")]


# ---- intraday helpers -----------------------------------------------------
def intraday_single(kind: str) -> float:
    """Mean net bps/day pooled across SINGLE names for MR or momentum."""
    daily = []
    for s in SINGLE:
        df = add_intraday_features(load_min(s))
        pos = mean_reversion_pos(df, 2.0, 1.0) if kind == "mr" else momentum_pos(df, 2.0, 1.0)
        daily.append(run_position(df, pos))
    book = pd.concat(daily, axis=1).mean(axis=1).dropna()
    return round(1e4 * book.mean(), 2)


def _load_close_min(sym):
    s = load_min(sym).set_index("Date")["Close"]
    return s[~s.index.duplicated(keep="last")]


def intraday_pair(a, b, z_in=3.0, z_out=0.0, win=90, skip=30):
    df = pd.concat({"a": _load_close_min(a), "b": _load_close_min(b)}, axis=1, sort=True).dropna()
    df["day"] = df.index.normalize()
    sp = np.log(df["a"]) - np.log(df["b"])
    g = sp.groupby(df["day"])
    z = (sp - g.transform(lambda s: s.rolling(win, min_periods=win).mean())) / \
        g.transform(lambda s: s.rolling(win, min_periods=win).std())
    mind = df.groupby("day").cumcount(); tradable = mind >= skip
    last = df["day"].ne(df["day"].shift(-1))
    des = pd.Series(np.where(z >= z_in, -1.0, np.where(z <= -z_in, 1.0, 0.0)), index=df.index)
    reset = ((z.abs() <= z_out) | (~tradable) | last).fillna(True)
    pos = des.where(des != 0).groupby(reset.cumsum()).ffill().where(~reset, 0.0).fillna(0.0)
    pos = pos.where(tradable, 0.0).where(~last, 0.0)
    fwd = sp.diff().groupby(df["day"]).shift(-1).fillna(0.0)
    prev = pos.groupby(df["day"]).shift(1).fillna(0.0)
    net = pos * fwd - (pos - prev).abs() * ONEWAY_COST * 2
    return net.groupby(df["day"]).sum()


# ---- daily (overnight) stat-arb ------------------------------------------
def _dclose(sym):
    df = pd.read_csv(EOD / f"{sym.lower()}.csv", usecols=["Date", "Close", "Series"], parse_dates=["Date"])
    df = df[df["Series"].fillna("EQ").isin(["EQ", "BE"])]
    s = df.set_index("Date")["Close"].sort_index()
    return s[~s.index.duplicated(keep="last")]


def daily_pair(a, b, z_in=2.0, z_out=0.5, win=20, cost_leg_rt=0.0020, start="2018-01-01"):
    df = pd.concat({"a": _dclose(a), "b": _dclose(b)}, axis=1, sort=True).dropna()
    df = df[df.index >= start]
    sp = np.log(df["a"]) - np.log(df["b"])
    z = ((sp - sp.rolling(win).mean()) / sp.rolling(win).std()).values
    pos = np.zeros(len(z)); cur = 0.0
    for i in range(len(z)):
        if np.isnan(z[i]): cur = 0.0
        elif cur == 0:
            cur = -1.0 if z[i] >= z_in else (1.0 if z[i] <= -z_in else 0.0)
        elif abs(z[i]) <= z_out:
            cur = 0.0
        pos[i] = cur
    pos = pd.Series(pos, index=df.index)
    fwd = sp.diff().shift(-1).fillna(0.0)
    turn = (pos - pos.shift(1).fillna(0)).abs()
    return pos * fwd - turn * cost_leg_rt * 2


def daily_book(cost_leg_rt):
    cols = {f"{a}/{b}": daily_pair(a, b, cost_leg_rt=cost_leg_rt) for a, b in DPAIRS}
    return pd.DataFrame(cols).mean(axis=1).dropna()


def stats(daily, label):
    d = daily.dropna()
    eq = (1 + d).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sh = d.mean() / d.std() * np.sqrt(252) if d.std() > 0 else 0
    return {"strategy": label, "net_bps_per_day": round(1e4 * d.mean(), 2),
            "ann_return_%": round(100 * d.mean() * 252, 1), "sharpe": round(sh, 2),
            "maxDD_%": round(100 * dd, 1), "hits_0.2%/day_target": (d.mean() >= 0.002)}


def main():
    rows = []
    print("A/B. Intraday single-name (pooled 6 names)...")
    rows.append({"strategy": "A. Intraday VWAP mean-reversion", "net_bps_per_day": intraday_single("mr"),
                 "ann_return_%": None, "sharpe": None, "maxDD_%": None, "hits_0.2%/day_target": False})
    rows.append({"strategy": "B. Intraday VWAP momentum", "net_bps_per_day": intraday_single("mom"),
                 "ann_return_%": None, "sharpe": None, "maxDD_%": None, "hits_0.2%/day_target": False})

    print("C. Intraday pairs (4 pairs)...")
    ip = pd.DataFrame({f"{a}/{b}": intraday_pair(a, b) for a, b in IPAIRS}).mean(axis=1)
    rows.append(stats(ip, "C. Intraday stat-arb pairs"))

    print("D. Overnight daily stat-arb (8 pairs)...")
    book20 = daily_book(0.0020)
    book10 = daily_book(0.0010)
    rows.append(stats(book20, "D1. Overnight stat-arb (20 bps/leg cost)"))
    rows.append(stats(book10, "D2. Overnight stat-arb (10 bps/leg, futures)"))

    df = pd.DataFrame(rows)
    print("\n" + df.to_string(index=False))
    df.to_csv(OUT / "summary.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2, default=str))

    # Chart: the best family (overnight stat-arb) equity vs the 0.2%/day target line
    fig, ax = plt.subplots(figsize=(11, 6))
    for bk, lab in [(book10, "Overnight stat-arb book (10 bps/leg)"),
                    (book20, "Overnight stat-arb book (20 bps/leg)")]:
        eq = (1 + bk).cumprod()
        ax.plot(eq.index, eq.values, label=lab, lw=1.6)
    target = (1 + pd.Series(0.002, index=book20.index)).cumprod()
    ax.plot(target.index, target.values, "r--", lw=1.2, label="0.2%/day target (the ask)")
    ax.set_yscale("log"); ax.set_title("Best survivor (overnight stat-arb) vs the 0.2%/day target")
    ax.legend(); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / "best_vs_target.png", dpi=130); plt.close(fig)
    print(f"\nArtefacts -> {OUT}/")


if __name__ == "__main__":
    main()
