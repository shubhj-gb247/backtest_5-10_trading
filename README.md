# Backtesting the "5/10" weekly mean-reversion strategy on Indian equities (NSE)

This repo backtests the statistical-arbitrage strategy described by HFT trader
**Manu Narang** — applied to the **Indian (NSE) market** instead of the US.

> **The strategy, in one line:** every week, across a huge universe of stocks,
> **buy a small fixed amount (`$5`) of any stock that fell ≥ 5% last week**, and
> **short a larger fixed amount (`$10`) of any stock that rose ≥ 10% last week**;
> hold one week, then repeat. The bet is that sharp weekly moves *mean-revert*,
> and the edge — tiny per name — is harvested across thousands of nearly
> independent micro-positions. Narang says it has "nearly as many losers as
> winners" yet "never a losing week or a losing month" over eight years.

**Headline result for India (NSE, Jan 2018 – Jun 2026, ~8.4 years): the strategy
does _not_ replicate.** As literally specified it loses money, and it loses even
*before* transaction costs on a capital-normalised basis. The reasons are
specific and instructive — see [Findings](#findings).

---

## TL;DR results

Backtest window **2018-01-12 → 2026-06-05** (439 weekly rebalances), universe of
**2,884 NSE stocks** (liquidity-filtered each week), 25 bps cost per side.

| Variant | Mean weekly return\* | Weekly win % | Monthly win % | Sharpe\* | Total net P&L (units) |
|---|---:|---:|---:|---:|---:|
| **Literal 5/10** (25 bps/side) | **−62.8 bps** | 34.4% | 24.8% | −1.82 | **−3,303** |
| Literal 5/10, **gross (0 cost)** | −12.8 bps | 45.6% | 47.5% | −0.37 | +234 |
| Liquid universe only | −45.5 bps | 39.9% | 29.7% | −1.37 | −628 |
| Long leg only (buy losers) | — | 44.4% | 43.6% | −0.81 | −450 |
| Short leg only (short winners) | — | ~38% | — | — | **−2,853** |

\* *"Return" and Sharpe are on a leverage-neutral, constant-deployed-capital
basis — see [Methodology → the capital convention](#the-capital-convention).
"units" are the strategy's own cash units (`$5` per long, `$10` per short).*

**Key takeaways**

1. **It loses money in India**, the opposite of Narang's US claim. There were
   plenty of losing weeks *and* losing months (monthly win rate ≈ 25%).
2. **The short leg is the disaster.** Shorting weekly +10% winners cost ~2,850
   units; the long leg (buying −5% losers) was roughly break-even (−450).
3. **Even with zero costs the per-capital edge is negative** (−12.8 bps/week).
   The strategy only shows a small *dollar* profit gross, and only because the
   literal fixed-cash-per-name sizing accidentally levers up into market crashes
   and is bailed out by the rebound. There is no robust edge to harvest.
4. **Transaction costs are decisive.** With ~109,000 round-trips, costs alone
   came to ~3,540 units. The break-even cost is essentially **0 bps** — and even
   that only on a gross *dollar* basis, not per unit of capital.

![Equity curves](output/equity_curve.png)

---

## Why it fails — the diagnostic that matters

The acid test for mean reversion: bucket every stock by its **prior-week**
return and look at its **next-week** return.

| Prior-week bucket | # obs | Mean next-wk | **Median next-wk** | % positive |
|---|---:|---:|---:|---:|
| < −10% | 17,015 | +0.50% | **+0.45%** | 52.8% |
| −10…−5% | 59,943 | +0.35% | +0.04% | 50.2% |
| −5…−2% | 102,622 | +0.13% | −0.17% | 48.0% |
| −2…+2% | 213,767 | +0.21% | −0.05% | 48.5% |
| +2…+5% | 85,853 | +0.32% | −0.13% | 48.6% |
| +5…+10% | 55,238 | +0.29% | −0.38% | 46.5% |
| **> +10%** | 32,249 | **+0.39%** | **−0.68%** | 45.7% |

Read the **median** column and there *is* reversion: big losers bounce
(+0.45%), big winners pull back (−0.68%), and the share of names that rise falls
monotonically from 53% to 46% as you go from losers to winners. The signal's
*direction* is correct.

But the strategy trades the **mean**, and the mean tells a different story:

- **A positive market drift (~+0.2%/week) sits under everything.** It quietly
  helps the long leg and quietly fights the short leg.
- **Winners have a fat right tail.** The *typical* winner pulls back, but a
  minority keep exploding upward (momentum / short-squeezes). Shorting them is a
  **negatively-skewed** bet: many small wins, occasional huge losses. That tail,
  not the median, drives the mean to **+0.39%** — so shorting winners loses on
  average, and the `$10` (2×) size amplifies it.

So the strategy isn't betting on the wrong sign — it's that in Indian equities
the **drift + fat upside tails + transaction costs** overwhelm a real-but-thin
median reversion. The US version survives because at HFT scale you *earn* the
spread instead of paying ~50 bps round-trip, and you can manage the tail.

![Cumulative P&L by leg](output/leg_decomposition.png)

The long leg (green) actually recovers strongly after 2024 and spikes on every
crash-rebound; the short leg (red) bleeds almost monotonically. The combined
line is dominated by the short leg's losses.

---

## Methodology

### Data
- **Source:** [`BennyThadikaran/eod2_data`](https://github.com/BennyThadikaran/eod2_data)
  — split/bonus-adjusted **NSE** end-of-day OHLCV, one CSV per symbol, ~3,400
  symbols, updated weekly. Pulled via [`scripts/fetch_data.sh`](scripts/fetch_data.sh).
- We keep the `EQ`/`BE` series, resample daily closes to **weekly (W-FRI)**
  closes, and compute weekly median daily turnover (`Close × Volume`) for the
  liquidity filter. Panels are cached to Parquet (committed under `data/`).

### Signals & sizing (faithful to the description)
- `prior_week_return ≤ −5%` → **long**, size **5** units.
- `prior_week_return ≥ +10%` → **short**, size **10** units.
- Positions are entered at the week's close and held exactly **one week**;
  P&L is the next week's return × signed size, minus costs. No look-ahead: the
  signal at week *t* uses only data through *t* and earns week *t+1*'s return.

### Tradable universe (applied every week, at signal time)
- Price ≥ ₹20 (no penny stocks), and
- median daily turnover over the trailing 4 weeks ≥ ₹25 lakh (≈ ₹2.5 M), and
- `|prior-week return| ≤ 60%` to discard un-adjusted corporate-action jumps.

This yields a few hundred names per week (avg **175 longs / 73 shorts**) — large
and diversified, in the spirit of the original, while remaining tradable.

### Costs
**25 bps per side (50 bps round-trip)** charged on each position's notional —
a deliberately middle-of-the-road estimate for a weekly *delivery* strategy in
India (STT ~10 bps on the sell, plus brokerage, exchange/SEBI/stamp charges, GST
and slippage across small/mid-caps). A [cost-sensitivity sweep](output/cost_sensitivity.csv)
from 0–40 bps is included.

### The capital convention
The literal strategy deploys a *fixed cash amount per name*, so weekly gross
exposure floats wildly (6 to 1,340 names/week). Compounding P&L over a fixed
capital base would inject volatility-drag that reflects **leverage, not edge**.
The headline returns/Sharpe/drawdown therefore use a **leverage-neutral,
constant-deployed-capital** basis (`net P&L ÷ capital actually deployed that
week`), which isolates the edge. Both conventions are emitted in
`output/weekly_literal.csv` (`ret_on_exposure` vs `ret_on_capital`).

> This convention also explains the one apparent contradiction in the numbers:
> gross *dollar* P&L is slightly **positive** (+234) while the gross *per-capital*
> return is **negative** (−12.8 bps/wk). The dollar figure is dominated by a few
> extreme high-exposure crash weeks (e.g. Mar-2020) whose rebounds pay off; per
> unit of capital, the average week loses. The dollar profit is an artefact of
> accidental leverage, not a harvestable edge.

### Robustness
- **Threshold grid** over long thresholds {−3,−5,−8,−10%} × short thresholds
  {+5,+8,+10,+15%}: **every** cell is negative (−50 to −71 bps/wk). No threshold
  choice rescues it. See [`output/threshold_grid.csv`](output/threshold_grid.csv).
- **Liquid-only** universe (turnover ≥ ₹20 cr): smaller losses but still clearly
  negative.

---

## Reproduce

```bash
pip install -r requirements.txt

# Option A — use the committed weekly cache (no download needed):
python run_backtest.py --daily-dir /unused --start 2018-01-01 --end 2026-06-12
#   (the cache at data/weekly.*.parquet is used automatically)

# Option B — refresh from source, then rebuild the cache:
bash scripts/fetch_data.sh                       # ~570 MB shallow clone
python src/data_loader.py eod2_data/daily --cache data/weekly --rebuild
python run_backtest.py --daily-dir eod2_data/daily --start 2018-01-01
```

Outputs land in `output/`: `summary.json`, `weekly_literal.csv`,
`monthly_returns_literal.csv`, the sensitivity/diagnostic CSVs, and the four
PNG charts.

### Layout
```
src/data_loader.py   load NSE CSVs -> cached weekly close/turnover panels
src/strategy.py      the 5/10 strategy engine (StrategyConfig + run_backtest)
src/metrics.py       performance metrics & monthly tables
src/analysis.py      cost sensitivity, threshold grid, forward-return diagnostic
run_backtest.py      CLI: runs all variants, writes artefacts and charts
tests/test_strategy.py  unit checks on the P&L accounting
```

---

## Caveats & honest limitations

- **Survivorship bias (optimistic).** The dataset is largely *currently-listed*
  NSE names; delisted/bankrupt stocks are under-represented. A loser-buying
  strategy is exactly the one that survivorship bias *flatters* — so the real
  long-leg result is likely **worse** than shown. This strengthens, not weakens,
  the negative conclusion.
- **Shorting frictions are understated.** Many NSE stocks are hard or impossible
  to borrow/short for a week, and stock-futures financing/availability is
  ignored. The real short leg would be even harder to run than modelled.
- **Fills are idealised** at the weekly close (no market impact beyond the flat
  cost, no liquidity cap per name).
- **One regime, one market.** Results cover NSE 2018–2026. They don't claim
  anything about the US book Narang actually runs, which operates at sub-bps
  cost as a liquidity provider — a fundamentally different cost structure.

**Bottom line:** the elegant "buy the dip, fade the rip" weekly reversion that
Narang describes for US markets does not survive contact with Indian equities
once realistic costs and the asymmetric short leg are included. The median
reversion signal is real but too thin to overcome drift, fat upside tails, and
~50 bps round-trip costs. Not investment advice; for research/education only.
