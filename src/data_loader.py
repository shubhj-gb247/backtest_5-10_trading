"""
Data loader for NSE end-of-day data.

The backtest is built on the open `BennyThadikaran/eod2_data` dataset, which
publishes split/bonus-adjusted end-of-day OHLCV history for ~3,400 NSE-listed
equities as one CSV per symbol under a `daily/` folder.

    https://github.com/BennyThadikaran/eod2_data

This module reads those per-symbol CSVs and builds three aligned weekly panels
(indexed by week-ending Friday, one column per symbol):

    * close     -- weekly close  (last traded close of the week)
    * turnover  -- weekly median daily turnover  (Close * Volume), used for the
                   liquidity filter that defines the tradable universe
    * price     -- weekly close again, kept separately for the price floor filter

Panels are cached to Parquet so repeated backtests are fast.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Columns we actually need from each per-symbol CSV.
_USECOLS = ["Date", "Close", "Volume", "Series"]


def _read_one(path: Path, start: str | None) -> pd.DataFrame | None:
    """Read a single symbol CSV, keep EQ series, return daily Close/Turnover."""
    try:
        df = pd.read_csv(
            path,
            usecols=lambda c: c in _USECOLS,
            parse_dates=["Date"],
        )
    except Exception:
        return None

    if df.empty or "Close" not in df.columns:
        return None

    # Keep only the regular equity series (EQ / BE). Older rows may lack Series.
    if "Series" in df.columns:
        ser = df["Series"].fillna("EQ")
        df = df[ser.isin(["EQ", "BE"])]

    if start is not None:
        df = df[df["Date"] >= pd.Timestamp(start)]

    if df.empty:
        return None

    df = df.set_index("Date").sort_index()
    close = pd.to_numeric(df["Close"], errors="coerce")
    vol = pd.to_numeric(df.get("Volume", np.nan), errors="coerce")
    turnover = close * vol

    out = pd.DataFrame({"close": close, "turnover": turnover})
    out = out[~out.index.duplicated(keep="last")]
    return out


def build_weekly_panels(
    daily_dir: str | Path,
    start: str | None = "2015-01-01",
    end: str | None = None,
    week_rule: str = "W-FRI",
    max_symbols: int | None = None,
    verbose: bool = True,
) -> dict[str, pd.DataFrame]:
    """Build weekly close + median-daily-turnover panels from the daily CSVs.

    Returns a dict with keys ``close`` and ``turnover`` -- both wide DataFrames
    indexed by week-ending date with one column per symbol.
    """
    daily_dir = Path(daily_dir)
    files = sorted(daily_dir.glob("*.csv"))
    if max_symbols is not None:
        files = files[:max_symbols]
    if not files:
        raise FileNotFoundError(f"No CSV files found under {daily_dir}")

    close_cols: dict[str, pd.Series] = {}
    turn_cols: dict[str, pd.Series] = {}

    n = len(files)
    for i, path in enumerate(files):
        sym = path.stem.upper()
        daily = _read_one(path, start)
        if daily is None or len(daily) < 30:
            continue

        # Weekly close = last close of the week; weekly turnover = median daily
        # turnover within the week (robust to one-off volume spikes).
        wk_close = daily["close"].resample(week_rule).last()
        wk_turn = daily["turnover"].resample(week_rule).median()

        close_cols[sym] = wk_close
        turn_cols[sym] = wk_turn

        if verbose and (i % 250 == 0 or i == n - 1):
            print(f"  loaded {i + 1}/{n} files...", file=sys.stderr)

    if not close_cols:
        raise RuntimeError("No usable symbols loaded.")

    close = pd.DataFrame(close_cols).sort_index()
    turnover = pd.DataFrame(turn_cols).sort_index()

    if end is not None:
        close = close[close.index <= pd.Timestamp(end)]
        turnover = turnover[turnover.index <= pd.Timestamp(end)]

    # Align columns.
    turnover = turnover.reindex(columns=close.columns)
    return {"close": close, "turnover": turnover}


def load_or_build(
    daily_dir: str | Path,
    cache_path: str | Path,
    rebuild: bool = False,
    **kwargs,
) -> dict[str, pd.DataFrame]:
    """Load weekly panels from a Parquet cache, building them once if needed."""
    cache_path = Path(cache_path)
    close_cache = cache_path.with_suffix(".close.parquet")
    turn_cache = cache_path.with_suffix(".turnover.parquet")

    if not rebuild and close_cache.exists() and turn_cache.exists():
        close = pd.read_parquet(close_cache)
        turnover = pd.read_parquet(turn_cache)
        return {"close": close, "turnover": turnover}

    panels = build_weekly_panels(daily_dir, **kwargs)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    panels["close"].to_parquet(close_cache)
    panels["turnover"].to_parquet(turn_cache)
    return panels


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build weekly NSE panels from eod2_data.")
    ap.add_argument("daily_dir", help="Path to eod2_data/daily")
    ap.add_argument("--cache", default="data/weekly", help="Cache path prefix")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=None)
    args = ap.parse_args()

    panels = load_or_build(
        args.daily_dir,
        args.cache,
        rebuild=args.rebuild,
        start=args.start,
        max_symbols=args.max_symbols,
    )
    c = panels["close"]
    print(f"close panel: {c.shape[0]} weeks x {c.shape[1]} symbols")
    print(f"date range : {c.index.min().date()} -> {c.index.max().date()}")
