#!/usr/bin/env python3
"""
"Can crypto net 0.2-0.7%/day with high frequency?" — the previous study, re-run
on Bitcoin 1-minute data (Bitstamp, 2018-2025).

Crypto is the interesting case: 24/7, and ~4-5x more volatile per minute than NSE
large caps, so per-trade edges are bigger and *might* clear costs. They do — at
the hourly horizon. Findings:

  * Minute-level MR & momentum : lose (turnover dwarfs the edge, like equities).
  * Hourly time-series MOMENTUM : the first genuinely net-positive strategy in
        this whole project (+7 bps/day net at taker fees, Sharpe ~0.5) because
        crypto TRENDS at the hourly scale.
  * Still ~0.07%/day, short of the 0.2% floor; leverage to reach it => ruin.
  * Indian 1% TDS per sell (~0.6%/day of notional here) kills it on a domestic
        exchange entirely.

Run: python run_crypto_study.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.crypto_intraday import load_btc

OUT = Path("output/crypto_target")
OUT.mkdir(parents=True, exist_ok=True)


def feats(df, win):
    typ = (df.High + df.Low + df.Close) / 3
    pv = (typ * df.Volume).rolling(win, min_periods=win).sum()
    vv = df.Volume.rolling(win, min_periods=win).sum().replace(0, np.nan)
    z = (df.Close - pv / vv)
    z = z / z.rolling(win, min_periods=win).std()
    return z, df.Close.pct_change().fillna(0).shift(-1).fillna(0)


def strat(df, win, zi, zo, cost, direction):
    """direction +1 = momentum (ride), -1 = mean-reversion (fade)."""
    z, fwd = feats(df, win)
    des = pd.Series(np.where(z >= zi, direction, np.where(z <= -zi, -direction, 0.0)), index=z.index)
    reset = (z.abs() <= zo).fillna(True)
    pos = des.where(des != 0).groupby(reset.cumsum()).ffill().where(~reset, 0.0).fillna(0.0)
    date = df.Date.dt.normalize()
    prev = pos.shift(1).fillna(0)
    net = (pos * fwd - (pos - prev).abs() * cost).groupby(date).sum()
    gross = (pos * fwd).groupby(date).sum()
    sells = ((prev != 0) & (pos == 0)).groupby(date).sum()
    return net, gross, sells


def stats(net, label, periods=365):
    eq = (1 + net).cumprod()
    return {"strategy": label, "net_bps_per_day": round(1e4 * net.mean(), 1),
            "ann_%": round(100 * net.mean() * periods, 1),
            "sharpe": round(net.mean() / net.std() * np.sqrt(periods), 2) if net.std() > 0 else 0,
            "maxDD_%": round(100 * (eq / eq.cummax() - 1).min(), 1),
            "final_x": round(eq.iloc[-1], 2),
            "hits_0.2%/day": bool(net.mean() >= 0.002)}, eq


def hourly(btc):
    b = btc.set_index("Date")
    return pd.DataFrame({"Open": b.Open.resample("1h").first(), "High": b.High.resample("1h").max(),
                         "Low": b.Low.resample("1h").min(), "Close": b.Close.resample("1h").last(),
                         "Volume": b.Volume.resample("1h").sum()}).dropna().reset_index()


def main():
    print("Loading BTC 1-minute (Bitstamp, 2018-2025)...")
    btc = load_btc()
    h = hourly(btc)
    rows = []

    # Minute-level (both directions) — expect failure
    for d, lab in [(-1, "Minute MR (fade)"), (+1, "Minute momentum (ride)")]:
        net, _, _ = strat(btc, 120, 2.0, 0.3, 0.00075, d)
        rows.append(stats(net, f"A. {lab}, minute, taker")[0])

    # Hourly momentum — the winner — at taker and (optimistic) maker
    net_t, gross_t, sells_t = strat(h, 24, 2.0, 0.3, 0.00075, +1)
    s_t, eq_t = stats(net_t, "B. Hourly MOMENTUM, taker 7.5bps")
    rows.append(s_t)
    net_m, _, _ = strat(h, 24, 2.0, 0.3, 0.0003, +1)
    s_m, eq_m = stats(net_m, "B. Hourly MOMENTUM, maker 3bps (optimistic)")
    rows.append(s_m)
    # Hourly mean-reversion — fails
    net_mr, _, _ = strat(h, 24, 2.0, 0.3, 0.0003, -1)
    rows.append(stats(net_mr, "C. Hourly mean-reversion, maker")[0])

    df = pd.DataFrame(rows)
    print("\n" + df.to_string(index=False))
    df.to_csv(OUT / "summary.csv", index=False)

    # Robustness + leverage + Indian TDS
    base = net_t.mean()
    half1 = net_t[net_t.index < "2022-01-01"]; half2 = net_t[net_t.index >= "2022-01-01"]
    extra = {
        "winner": "Hourly BTC time-series momentum (24h VWAP z>2), taker fees",
        "net_pct_per_day": round(100 * base, 3),
        "sharpe": round(net_t.mean() / net_t.std() * np.sqrt(365), 2),
        "split_2018_2021_bps": round(1e4 * half1.mean(), 1),
        "split_2022_2025_bps": round(1e4 * half2.mean(), 1),
        "leverage_to_hit_0.2pct": round(0.002 / base, 1),
        "maxDD_at_that_leverage_pct": round(100 * (((1 + net_t).cumprod() / (1 + net_t).cumprod().cummax() - 1).min()) * (0.002 / base), 0),
        "indian_TDS_drag_pct_per_day": round(float(sells_t.mean()), 2),
        "gross_edge_pct_per_day": round(100 * gross_t.mean(), 2),
    }
    (OUT / "key_findings.json").write_text(json.dumps(extra, indent=2))
    print("\nKey findings:\n" + json.dumps(extra, indent=2))

    # Chart: hourly momentum equity vs the 0.2%/day target
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(eq_t.index, eq_t.values, label=f"Hourly momentum (taker) — {s_t['ann_%']}%/yr, Sharpe {s_t['sharpe']}", color="navy")
    ax.plot(eq_m.index, eq_m.values, label=f"Hourly momentum (maker, optimistic) — {s_m['ann_%']}%/yr", color="seagreen", alpha=0.8)
    tgt = (1 + pd.Series(0.002, index=eq_t.index)).cumprod()
    ax.plot(tgt.index, tgt.values, "r--", lw=1.2, label="0.2%/day target (the ask)")
    ax.set_yscale("log"); ax.set_title("Crypto's best survivor (hourly BTC momentum) vs the 0.2%/day target")
    ax.legend(); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / "crypto_best_vs_target.png", dpi=130); plt.close(fig)
    print(f"\nArtefacts -> {OUT}/")


if __name__ == "__main__":
    main()
