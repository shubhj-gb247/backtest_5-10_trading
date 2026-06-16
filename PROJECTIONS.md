# 1-year earning projections by starting capital

Forward, **haircut** scenarios for a blended portfolio of the backtested
strategies in `STARTER_STRATEGIES.md` (momentum rotation + low-volatility +
gold/dual-momentum + a small crypto sleeve). Net of costs. **Projections, not
promises** — a single year realistically ranges from roughly −25% to +25%.

Key fact: the **% return is ~the same at all three capital levels** (same ETFs,
same strategies); only the rupees scale. Larger accounts keep slightly more
because the fixed-cost drag (~₹200/yr of DP/transaction charges) is a smaller %.

| Capital | Fixed-cost drag | Bad year (−) | Conservative | **Base case** | Good year |
|---|---:|---:|---:|---:|---:|
| ₹10,000 | 2.0%/yr | ₹7,300 (−₹2,700) | ₹10,600 (+₹600) | **₹11,100 (+₹1,100)** | ₹11,800 (+₹1,800) |
| ₹50,000 | 0.4%/yr | ₹37,300 (−₹12,700) | ₹53,800 (+₹3,800) | **₹56,300 (+₹6,300)** | ₹59,800 (+₹9,800) |
| ₹1,00,000 | 0.2%/yr | ₹74,800 (−₹25,200) | ₹1,07,800 (+₹7,800) | **₹1,12,800 (+₹12,800)** | ₹1,19,800 (+₹19,800) |

Net CAGR assumptions (gross of fixed drag): bad −25%, conservative +8%, base
+13%, good +20%. The base case ~11–13% net is a *multi-year average* expectation,
not a guarantee for year 1; a losing first year happens ~1 in 4–5 years.

**Takeaways**
- At ₹10k the absolute profit is small (~₹1,100 base year) — it's a learning
  budget; the skill is the asset, capital is the multiplier.
- Capital size barely changes the % here; the biggest growth lever at small size
  is **adding capital** (a monthly SIP dwarfs trading gains) + compounding ~12%.
- These use the realistic low-turnover strategies, **not** the 0.2–0.7%/day
  target shown to be unachievable in `DAILY_TARGET_STUDY.md` / `CRYPTO_DAILY_TARGET.md`.

Numbers: `output/projections_1yr.csv`. *Not investment advice.*
