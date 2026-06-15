#!/usr/bin/env python3
"""Run the five starter strategies and print a comparison table + charts."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.starter_strategies import (
    buy_hold,
    dual_momentum,
    load_crypto,
    load_nse,
    metrics,
    trend_timed,
)

OUT = Path("output/starter")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    rows = []
    curves = {}

    # --- Benchmarks --- (use the clean index series, not split-corrupted ETFs)
    nifty = load_nse("nifty 50", "2015-01-01")
    rows.append(metrics(buy_hold(nifty), name="Nifty 50 buy&hold (benchmark)"))
    curves["Nifty50 B&H"] = buy_hold(nifty)

    # --- 1. Nifty 200-DMA trend timing ---
    s1 = trend_timed(nifty, 200)
    rows.append(metrics(s1, name="1. Nifty 200-DMA trend timing"))
    curves["1. Nifty trend-timed"] = s1

    # --- 2. Momentum factor (Alpha 50) ---
    alpha = load_nse("nifty alpha 50", "2015-01-01")
    rows.append(metrics(buy_hold(alpha), name="2a. Nifty Alpha 50 buy&hold"))
    rows.append(metrics(trend_timed(alpha, 200), name="2b. Alpha 50 trend-timed"))
    curves["2. Alpha50 B&H"] = buy_hold(alpha)
    curves["2. Alpha50 trend-timed"] = trend_timed(alpha, 200)

    # --- 3. Low-volatility factor ---
    lowvol = load_nse("nifty100 low volatility 30", "2016-07-15")
    rows.append(metrics(buy_hold(lowvol), name="3a. Nifty Low-Vol 30 buy&hold"))
    rows.append(metrics(trend_timed(lowvol, 200), name="3b. Low-Vol 30 trend-timed"))
    curves["3. LowVol B&H"] = buy_hold(lowvol)

    # --- 4. Equity/Gold dual momentum --- (split-cleaned gold ETF)
    gold = load_nse("goldbees", "2015-01-01")
    dm = dual_momentum({"NIFTY50": nifty, "GOLD": gold}, lookback_m=6)
    rows.append(metrics(dm, freq=12, name="4. Equity/Gold dual momentum"))
    rows.append(metrics(buy_hold(gold), freq=252, name="   (Gold buy&hold, ref)"))
    curves["4. Equity/Gold dualmom"] = dm
    curves["4. Gold B&H"] = buy_hold(gold)

    # --- FLAGSHIP: multi-asset momentum rotation ---
    # Monthly, hold the single best-6-month-momentum sleeve among a growth
    # factor, a defensive factor and gold; fall to cash if none is rising.
    rot = dual_momentum({"ALPHA50": alpha, "LOWVOL": lowvol, "GOLD": gold}, lookback_m=6)
    rows.insert(1, metrics(rot, freq=12, name="0. FLAGSHIP momentum rotation (Mom/LowVol/Gold/Cash)"))
    curves["0. Momentum rotation"] = rot

    # --- 5. Crypto trend following ---
    btc = load_crypto("/tmp/btc.csv", "2017-01-01")
    eth = load_crypto("/tmp/eth.csv", "2017-01-01")
    s5b = trend_timed(btc, 200, cost=0.005, cash_yield=0.0)
    s5e = trend_timed(eth, 200, cost=0.005, cash_yield=0.0)
    rows.append(metrics(buy_hold(btc), name="5a. BTC buy&hold (ref)"))
    rows.append(metrics(s5b, name="5b. BTC 200-DMA trend (USD, pre-tax)"))
    rows.append(metrics(s5e, name="5c. ETH 200-DMA trend (USD, pre-tax)"))
    curves["5. BTC trend-timed"] = s5b
    curves["5. BTC B&H"] = buy_hold(btc)

    # --- Table ---
    df = pd.DataFrame(rows).set_index("name")
    pd.set_option("display.width", 200)
    print(df.to_string())
    df.to_csv(OUT / "summary.csv")
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2, default=str))

    # --- Charts ---
    # Equity (NSE strategies), rebased, log scale
    fig, ax = plt.subplots(figsize=(11, 6))
    for k in ["Nifty50 B&H", "0. Momentum rotation", "2. Alpha50 B&H",
              "3. LowVol B&H", "4. Equity/Gold dualmom"]:
        c = curves[k]
        ax.plot(c.index, c / c.iloc[0], label=k, lw=1.5)
    ax.set_yscale("log"); ax.set_title("Starter strategies on NSE — growth of ₹1 (net of costs, log)")
    ax.legend(); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / "nse_strategies.png", dpi=130); plt.close(fig)

    # Crypto chart (separate, much larger scale)
    fig, ax = plt.subplots(figsize=(11, 6))
    for k in ["5. BTC B&H", "5. BTC trend-timed"]:
        c = curves[k]
        ax.plot(c.index, c / c.iloc[0], label=k, lw=1.5)
    ax.set_yscale("log"); ax.set_title("Crypto: BTC buy&hold vs 200-DMA trend (growth of $1, log)")
    ax.legend(); ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout(); fig.savefig(OUT / "crypto_strategies.png", dpi=130); plt.close(fig)

    print(f"\nArtefacts -> {OUT}/")


if __name__ == "__main__":
    main()
