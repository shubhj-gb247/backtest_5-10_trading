"""
Starter strategies for a small Indian account — real backtests on real data.

Everything here is implementable with a tiny account (₹10k) using ETFs / index
funds / spot crypto: no F&O margin, no shorting, low turnover so costs stay sane.

Data
----
* NSE index & ETF daily history from the eod2_data dataset (survivorship-bias
  free for the published indices).
* BTC / ETH daily USD prices from CoinMetrics community data.

Strategies
----------
1. Nifty 200-DMA trend timing      (NIFTYBEES, in/out of market)
2. Momentum factor                 (NIFTY ALPHA 50, buy&hold vs trend-timed)
3. Low-volatility factor           (NIFTY100 LOW VOLATILITY 30)
4. Equity/Gold dual momentum       (NIFTYBEES vs GOLDBEES, monthly)
5. Crypto trend following          (BTC & ETH, 200-DMA time-series momentum)

We report each strategy's CAGR, volatility, Sharpe, max drawdown, Calmar and
worst year, plus a passive buy & hold benchmark, all NET of realistic costs.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

EOD = Path("/tmp/eod2_data/daily")
TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #
def load_nse(symbol_file: str, start: str = "2015-01-01") -> pd.Series:
    """Load a daily close series from an eod2 CSV (e.g. 'nifty 50').

    ETF files (NIFTYBEES, GOLDBEES, ...) carry *unadjusted* stock splits — e.g.
    a 1:10 split shows up as a spurious ~-90% single-day drop. No legitimate
    index/ETF moves >40% in a day, so we neutralise any such day by zeroing its
    log-return, which back-adjusts the series to be continuous. Pure index
    series have no splits and are unaffected.
    """
    df = pd.read_csv(EOD / f"{symbol_file}.csv", usecols=["Date", "Close"], parse_dates=["Date"])
    s = df.set_index("Date")["Close"].sort_index()
    s = s[~s.index.duplicated(keep="last")].astype(float)
    s = s[s > 0]
    logret = np.log(s / s.shift(1))
    logret = logret.where(logret.abs() < 0.40, 0.0)   # drop split discontinuities
    adj = s.iloc[0] * np.exp(logret.fillna(0).cumsum())
    return adj[adj.index >= pd.Timestamp(start)]


def load_crypto(path: str, start: str = "2015-01-01") -> pd.Series:
    df = pd.read_csv(path, usecols=["time", "PriceUSD"])
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    s = df.dropna(subset=["PriceUSD"]).set_index("time")["PriceUSD"].sort_index()
    return s[s.index >= pd.Timestamp(start)].astype(float)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def metrics(equity: pd.Series, freq: int = TRADING_DAYS, name: str = "") -> dict:
    equity = equity.dropna()
    ret = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 and equity.iloc[-1] > 0 else np.nan
    vol = ret.std() * np.sqrt(freq)
    sharpe = (ret.mean() * freq) / vol if vol > 0 else np.nan
    downside = ret[ret < 0].std() * np.sqrt(freq)
    sortino = (ret.mean() * freq) / downside if downside and downside > 0 else np.nan
    dd = (equity / equity.cummax() - 1.0)
    maxdd = dd.min()
    calmar = cagr / abs(maxdd) if maxdd < 0 else np.nan
    yearly = equity.resample("YE").last().pct_change().dropna()
    return {
        "name": name,
        "years": round(years, 1),
        "CAGR_%": round(100 * cagr, 1),
        "vol_%": round(100 * vol, 1),
        "Sharpe": round(sharpe, 2),
        "Sortino": round(sortino, 2),
        "maxDD_%": round(100 * maxdd, 1),
        "Calmar": round(calmar, 2),
        "worst_yr_%": round(100 * yearly.min(), 1) if len(yearly) else np.nan,
        "best_yr_%": round(100 * yearly.max(), 1) if len(yearly) else np.nan,
        "%pos_months": round(100 * (equity.resample("ME").last().pct_change().dropna() > 0).mean(), 0),
    }


# --------------------------------------------------------------------------- #
# Backtest primitives
# --------------------------------------------------------------------------- #
def trend_timed(price: pd.Series, ma_days: int, cost: float = 0.0030,
                cash_yield: float = 0.06) -> pd.Series:
    """Hold the asset when Close > moving average, else sit in cash.

    Signal uses yesterday's close vs its MA (no look-ahead); a round-trip cost
    `cost` is charged each time the position flips. Cash earns `cash_yield` p.a.
    """
    price = price.dropna()
    ma = price.rolling(ma_days).mean()
    invested = (price > ma).shift(1).fillna(False)  # act next day on the signal
    asset_ret = price.pct_change().fillna(0.0)
    daily_cash = (1 + cash_yield) ** (1 / TRADING_DAYS) - 1
    strat_ret = np.where(invested, asset_ret, daily_cash)
    flips = invested.ne(invested.shift(1)).fillna(False)
    strat_ret = strat_ret - flips.values * cost
    return (1 + pd.Series(strat_ret, index=price.index)).cumprod()


def buy_hold(price: pd.Series) -> pd.Series:
    price = price.dropna()
    return price / price.iloc[0]


def dual_momentum(assets: dict[str, pd.Series], lookback_m: int = 6,
                  cost: float = 0.0030, cash_yield: float = 0.06) -> pd.Series:
    """Monthly: hold the asset with the highest positive `lookback_m`-month
    return; if none is positive, hold cash. Classic absolute+relative momentum.
    """
    px = pd.DataFrame(assets).dropna()
    m = px.resample("ME").last()
    mom = m.pct_change(lookback_m)
    daily_cash = (1 + cash_yield) ** (1 / 12) - 1

    equity = [1.0]
    dates = [m.index[lookback_m]]
    held = None
    for i in range(lookback_m, len(m) - 1):
        scores = mom.iloc[i]
        pick = scores.idxmax() if scores.max() > 0 else "CASH"
        nxt = m.iloc[i + 1] / m.iloc[i] - 1
        r = daily_cash if pick == "CASH" else nxt[pick]
        if pick != held:
            r -= cost
        held = pick
        equity.append(equity[-1] * (1 + r))
        dates.append(m.index[i + 1])
    return pd.Series(equity, index=dates)
