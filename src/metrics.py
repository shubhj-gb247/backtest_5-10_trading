"""Performance metrics and reporting helpers for the weekly backtest."""

from __future__ import annotations

import numpy as np
import pandas as pd

WEEKS_PER_YEAR = 52.0


def drawdown(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return equity / peak - 1.0


def summarize(weekly: pd.DataFrame, capital_base: float) -> dict:
    """Compute headline performance metrics from a weekly results frame."""
    r = weekly["ret_on_exposure"]
    eq = weekly["equity"]
    dd = drawdown(eq)

    n_weeks = len(r)
    years = n_weeks / WEEKS_PER_YEAR
    total_return = eq.iloc[-1] - 1.0
    cagr = eq.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 and eq.iloc[-1] > 0 else np.nan

    ann_vol = r.std(ddof=0) * np.sqrt(WEEKS_PER_YEAR)
    sharpe = (r.mean() * WEEKS_PER_YEAR) / ann_vol if ann_vol > 0 else np.nan

    downside = r[r < 0].std(ddof=0) * np.sqrt(WEEKS_PER_YEAR)
    sortino = (r.mean() * WEEKS_PER_YEAR) / downside if downside and downside > 0 else np.nan

    # Monthly returns from the weekly equity curve.
    monthly = eq.resample("ME").last().pct_change().dropna()

    return {
        "start": weekly.index.min().date().isoformat(),
        "end": weekly.index.max().date().isoformat(),
        "weeks": n_weeks,
        "years": round(years, 2),
        "capital_base": round(capital_base, 1),
        "total_return_pct": round(100 * total_return, 1),
        "cagr_pct": round(100 * cagr, 2),
        "ann_vol_pct": round(100 * ann_vol, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(100 * dd.min(), 1),
        "weekly_win_pct": round(100 * (r > 0).mean(), 1),
        "monthly_win_pct": round(100 * (monthly > 0).mean(), 1) if len(monthly) else np.nan,
        "best_week_pct": round(100 * r.max(), 2),
        "worst_week_pct": round(100 * r.min(), 2),
        "best_month_pct": round(100 * monthly.max(), 2) if len(monthly) else np.nan,
        "worst_month_pct": round(100 * monthly.min(), 2) if len(monthly) else np.nan,
        "avg_n_long": round(weekly["n_long"].mean(), 0),
        "avg_n_short": round(weekly["n_short"].mean(), 0),
        "total_gross_pnl": round(weekly["gross_pnl"].sum(), 1),
        "total_costs": round(weekly["costs"].sum(), 1),
        "total_net_pnl": round(weekly["net_pnl"].sum(), 1),
    }


def monthly_table(equity: pd.Series) -> pd.DataFrame:
    """Year x Month table of returns (%) from a weekly equity curve."""
    monthly = equity.resample("ME").last().pct_change().dropna() * 100
    df = monthly.to_frame("ret")
    df["year"] = df.index.year
    df["month"] = df.index.month
    table = df.pivot_table(index="year", columns="month", values="ret")
    table.columns = [pd.Timestamp(2000, m, 1).strftime("%b") for m in table.columns]
    return table.round(2)
