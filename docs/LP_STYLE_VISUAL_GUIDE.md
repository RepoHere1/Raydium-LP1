# LP order styles — what you see on Raydium (visual reference)

Use this when reading our dashboard labels (`lp_style_label`) next to what Raydium’s portfolio UI shows. This is **not** HTML layout advice — it is how the **position card** should look conceptually.

---

## 1. Centered tight range

**Raydium card picture**

- Current price sits **in the middle** of a **narrow** green band.
- Band labels: something like `0.168 – 0.182 USDC per TOKEN` with only a few % between lower and upper.
- Badge: **In range** most of the time in calm markets; slips **Out of range** quickly if price runs.

**Meaning**

- You are market-making right on spot; max fee rate per dollar when price chops inside the band.
- Highest maintenance: recenters often when spot drifts.

**Our UI one-liner**

`CLMM · centered · ~12–15% · pay SOL only`

---

## 2. Asymmetric / single-sided (range order)

**Raydium card picture**

- Band is **only above or only below** current price (not wrapped around it).
- Example (bullish): current price near the **bottom** of the card; range `spot → spot+5%` — empty below, liquidity above.
- Behaves like a **limit ladder**: as price rises through the band, inventory converts + earns fees.

**Meaning**

- Bullish = band above spot (sell into strength). Bearish = band below (buy dips).
- Often **Out of range** until price moves into your side.

**Our UI one-liner**

`CLMM · single above · 20% · pay SOL only`

---

## 3. Volatility / ATR width

**Raydium card picture**

- Green band **wider** than centered tight — often **20–35%** total width from the day’s min/max swing.
- Current price usually **In range** on choppy alts; band looks like a fat corridor around spot.

**Meaning**

- Width scales with recent daily volatility; fewer OOR events than tight, less fee intensity per dollar.

**Our UI one-liner**

`CLMM · centered · 30% · ATR width · pay USDC only`

---

## 4. Trailing / dynamic skew

**Raydium card picture**

- Band is **shifted** toward momentum: on uptrends the interval sits **above** spot (not symmetric).
- Card still shows lower/upper prices but the midpoint is **biased** up or down vs spot.

**Meaning**

- Keeps liquidity nearer where price is **moving**, not where it was yesterday.

**Our UI one-liner**

`CLMM · centered (skewed) · 20% · Trailing skew · pay SOL only`

---

## 5. Standard wide band (`standard_full_range`)

**Raydium card picture**

- **Wide centered** interval — up to **80% total width** around spot (±40% each side). **Not** literal pool min/max ticks.
- Spot can show **Out of range** after large moves; much lower SOL rent than true full range.

**Meaning**

- Passive-ish exposure without ~0.15 SOL tick-array escrow on small deposits.

**Our UI one-liner**

`CLMM · wide band · 80% · Wide band · pay USDC only`

---

## HTML dashboard vs Raydium UI

- **Raydium** = authoritative for range, In/Out of range, APR, position USD.
- **Our 8844 dashboard** = settings, scan funnel, detective experiment, and **style labels** that map to the five pictures above.
- HTML is fine for **controls and tables**; the **position truth** always comes from chain + Raydium portfolio. If we later simplify visuals, prefer **plain text + status pills** (In range / Out of range / Style id) over heavy custom graphics.
