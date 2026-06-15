#!/usr/bin/env python3
"""
Backtest the "5/10" weekly mean-reversion strategy on NSE equities.

Strategy (per Manu Narang): across a large universe of stocks, each week buy a
small fixed amount of every stock that fell >=5% the prior week, and short a
larger fixed amount of every stock that rose >=10% the prior week; hold one week.

Usage:
    python run_backtest.py --daily-dir /path/to/eod2_data/daily
    python run_backtest.py --daily-dir ... --start 2018-01-01 --end 2026-06-12

Outputs (under --outdir, default ./output):
    summary.json / summary_*.json   headline metrics per variant
    weekly_literal.csv              full weekly P&L series for the literal run
    monthly_returns_literal.csv     year x month return table
    equity_curve.png, drawdown.png, monthly_heatmap.png, leg_decomposition.png
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.analysis import cost_sensitivity, signal_forward_returns, threshold_grid
from src.data_loader import load_or_build
from src.metrics import drawdown, monthly_table, summarize
from src.strategy import StrategyConfig, run_backtest


def _slice(panels, start, end):
    c = panels["close"]
    idx = c.index
    m = pd.Series(True, index=idx)
    if start:
        m &= idx >= pd.Timestamp(start)
    if end:
        m &= idx <= pd.Timestamp(end)
    return {"close": panels["close"][m.values], "turnover": panels["turnover"][m.values]}


def plot_equity(variants: dict, outdir: Path):
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, res in variants.items():
        ax.plot(res.weekly.index, res.weekly["equity"], label=name, linewidth=1.6)
    ax.axhline(1.0, color="black", lw=0.8, ls="--", alpha=0.6)
    ax.set_yscale("log")
    ax.set_title("5/10 weekly mean-reversion on NSE — growth of 1 (log scale)")
    ax.set_ylabel("Equity (x starting capital)")
    ax.legend()
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout()
    fig.savefig(outdir / "equity_curve.png", dpi=130)
    plt.close(fig)


def plot_drawdown(res, outdir: Path):
    dd = drawdown(res.weekly["equity"]) * 100
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(dd.index, dd.values, 0, color="firebrick", alpha=0.4)
    ax.plot(dd.index, dd.values, color="firebrick", lw=1.0)
    ax.set_title("Literal strategy — drawdown (%)")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(outdir / "drawdown.png", dpi=130)
    plt.close(fig)


def plot_monthly_heatmap(res, outdir: Path):
    table = monthly_table(res.weekly["equity"])
    fig, ax = plt.subplots(figsize=(11, 0.5 * len(table) + 2))
    vmax = np.nanmax(np.abs(table.values)) if table.size else 1
    im = ax.imshow(table.values, cmap="RdYlGn", aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(table.columns)))
    ax.set_xticklabels(table.columns)
    ax.set_yticks(range(len(table.index)))
    ax.set_yticklabels(table.index)
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            v = table.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=7)
    ax.set_title("Literal strategy — monthly returns (%)")
    fig.colorbar(im, ax=ax, shrink=0.7, label="%")
    fig.tight_layout()
    fig.savefig(outdir / "monthly_heatmap.png", dpi=130)
    plt.close(fig)


def plot_leg_decomposition(panels, cfg, outdir: Path):
    """Cumulative net P&L of the long leg vs short leg, in cash units."""
    long_only = run_backtest(panels, StrategyConfig(**{**asdict(cfg), "short_size": 0.0}))
    short_only = run_backtest(panels, StrategyConfig(**{**asdict(cfg), "long_size": 0.0}))
    full = run_backtest(panels, cfg)

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(long_only.weekly.index, long_only.weekly["net_pnl"].cumsum(),
            label="Long leg (buy −5% losers)", color="seagreen")
    ax.plot(short_only.weekly.index, short_only.weekly["net_pnl"].cumsum(),
            label="Short leg (short +10% winners)", color="firebrick")
    ax.plot(full.weekly.index, full.weekly["net_pnl"].cumsum(),
            label="Combined (literal 5/10)", color="navy", lw=1.8)
    ax.axhline(0, color="black", lw=0.8, ls="--", alpha=0.6)
    ax.set_title("Cumulative net P&L by leg (cash units)")
    ax.set_ylabel("Cumulative net P&L (units)")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(outdir / "leg_decomposition.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daily-dir", required=True, help="Path to eod2_data/daily")
    ap.add_argument("--cache", default="data/weekly", help="Weekly-panel cache prefix")
    ap.add_argument("--rebuild", action="store_true", help="Rebuild the panel cache")
    ap.add_argument("--panel-start", default="2015-01-01", help="Earliest date to load into the panel")
    ap.add_argument("--start", default="2018-01-01", help="Backtest start (8-year window)")
    ap.add_argument("--end", default=None, help="Backtest end")
    ap.add_argument("--cost-bps", type=float, default=25.0, help="Cost per side, bps")
    ap.add_argument("--outdir", default="output")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("Loading weekly panels...")
    panels_all = load_or_build(args.daily_dir, args.cache, rebuild=args.rebuild, start=args.panel_start)
    panels = _slice(panels_all, args.start, args.end)
    c = panels["close"]
    print(f"Backtest universe: {c.shape[1]} symbols, {c.shape[0]} weeks "
          f"({c.index.min().date()} -> {c.index.max().date()})")

    # --- Variants ---------------------------------------------------------
    literal = StrategyConfig(cost_bps_per_side=args.cost_bps)
    # Liquid-only: restrict to genuinely tradable large/mid caps.
    liquid = StrategyConfig(cost_bps_per_side=args.cost_bps, min_med_turnover=2e8)
    # Long-only reversion (drop the loss-making short leg).
    long_only = StrategyConfig(cost_bps_per_side=args.cost_bps, short_size=0.0)

    # Gross (zero-cost) literal run isolates the raw edge from trading costs.
    gross = StrategyConfig(cost_bps_per_side=0.0)

    variants = {
        "Literal 5/10": run_backtest(panels, literal),
        "Literal 5/10 (gross, no costs)": run_backtest(panels, gross),
        "Liquid universe only": run_backtest(panels, liquid),
        "Long leg only": run_backtest(panels, long_only),
    }

    summaries = {}
    for name, res in variants.items():
        s = summarize(res.weekly, res.capital_base)
        s["leg_long_trades"] = res.trades_long
        s["leg_short_trades"] = res.trades_short
        summaries[name] = s
        print(f"\n=== {name} ===")
        for k, v in s.items():
            print(f"  {k:>20}: {v}")

    # --- Save artefacts ---------------------------------------------------
    (outdir / "summary.json").write_text(json.dumps(summaries, indent=2, default=str))
    lit = variants["Literal 5/10"]
    lit.weekly.to_csv(outdir / "weekly_literal.csv")
    monthly_table(lit.weekly["equity"]).to_csv(outdir / "monthly_returns_literal.csv")

    plot_equity(variants, outdir)
    plot_drawdown(lit, outdir)
    plot_monthly_heatmap(lit, outdir)
    plot_leg_decomposition(panels, literal, outdir)

    # --- Robustness / diagnostics ----------------------------------------
    print("\nRunning robustness analyses...")
    cost_tbl = cost_sensitivity(panels, literal)
    thr_tbl = threshold_grid(panels, literal)
    fwd_tbl = signal_forward_returns(panels, literal)
    cost_tbl.to_csv(outdir / "cost_sensitivity.csv", index=False)
    thr_tbl.to_csv(outdir / "threshold_grid.csv", index=False)
    fwd_tbl.to_csv(outdir / "forward_return_by_bucket.csv", index=False)
    print("\n--- Cost sensitivity (literal) ---")
    print(cost_tbl.to_string(index=False))
    print("\n--- Forward-week return by prior-week bucket (tradable universe) ---")
    print(fwd_tbl.to_string(index=False))

    print(f"\nArtefacts written to {outdir}/")


if __name__ == "__main__":
    main()
