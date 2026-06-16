#!/usr/bin/env python3
"""Run the intraday Opening-Range-Breakout testbed across liquid NSE names and
report whether a '1% a day' intraday strategy survives real costs.

Usage: python run_intraday.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.intraday import (
    ORBConfig,
    backtest_orb,
    daily_stats,
    load_minute,
    per_trade_stats,
    roundtrip_cost_frac,
)

SYMBOLS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "TATASTEEL"]
OUT = Path("output/intraday")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    cfg = ORBConfig()  # 15-min OR, 1R target / 1R stop, both sides, Rs50k notional (10k x5)
    print(f"Round-trip cost on Rs{cfg.notional:,.0f} notional: "
          f"{1e4*roundtrip_cost_frac(cfg.notional, cfg.slippage_bps_per_side):.1f} bps "
          f"(= {100*roundtrip_cost_frac(cfg.notional)*5:.2f}% of a Rs10k account at 5x)\n")

    all_trades = []
    rows = []
    for sym in SYMBOLS:
        df = load_minute(sym, start="2018-01-01")
        tr = backtest_orb(df, cfg)
        tr["symbol"] = sym
        all_trades.append(tr)
        s = {"symbol": sym, **per_trade_stats(tr, cfg)}
        rows.append(s)
        print(f"{sym:>10}: {s['trades']:>5} trades | win {s['win_rate_%']}% | "
              f"gross {s['gross_avg_bps']:>6} bps | cost {s['cost_bps']} bps | "
              f"NET {s['net_avg_bps']:>6} bps/trade | Rs{s['expectancy_Rs_per_trade']}/trade")

    trades = pd.concat(all_trades, ignore_index=True)
    pd.DataFrame(rows).to_csv(OUT / "per_symbol.csv", index=False)

    # Pooled portfolio: average across the 6 names each day (diversified intraday book).
    print("\n=== Pooled book (equal-weight across the 6 symbols) ===")
    pooled = trades.groupby(["day", "symbol"])["net_ret"].sum().groupby("day").mean().to_frame("net_ret")
    pooled_tr = pooled.reset_index()

    overall_trade = per_trade_stats(trades, cfg)
    print("Per-trade (all symbols pooled):")
    print(json.dumps(overall_trade, indent=2))

    for lev in [1.0, 5.0]:
        ds = daily_stats(pooled_tr, leverage=lev)
        print(f"\nDaily account stats @ {lev:.0f}x leverage:")
        print(json.dumps(ds, indent=2))
        (OUT / f"daily_stats_{int(lev)}x.json").write_text(json.dumps(ds, indent=2))

    # --- Chart: daily net return distribution + equity curve (5x) ---
    daily5 = pooled_tr.groupby("day")["net_ret"].sum() * 5.0
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].hist(100 * daily5, bins=80, color="steelblue", alpha=0.8)
    axes[0].axvline(1.0, color="green", ls="--", label="+1% target")
    axes[0].axvline(0.0, color="black", ls="-", lw=0.8)
    axes[0].axvline(100 * daily5.mean(), color="red", ls=":", label=f"mean {100*daily5.mean():.3f}%")
    axes[0].set_title("Daily net return distribution (ORB, 6 names, 5x)")
    axes[0].set_xlabel("Daily return (%)"); axes[0].legend()

    eq = (1 + daily5).cumprod()
    axes[1].plot(eq.index, eq.values, color="darkred")
    axes[1].axhline(1.0, color="black", ls="--", lw=0.8)
    axes[1].set_title(f"Equity curve (5x) — ends at {eq.iloc[-1]:.2f}x"); axes[1].set_yscale("log")
    fig.tight_layout(); fig.savefig(OUT / "orb_results.png", dpi=130); plt.close(fig)
    print(f"\nArtefacts -> {OUT}/")


if __name__ == "__main__":
    main()
