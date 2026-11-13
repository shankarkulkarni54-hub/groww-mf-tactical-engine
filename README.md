# 🛡️ Groww Mutual Fund Tactical Allocation Engine

A cloud-native paper-trading system that executes an intelligent tactical cash-vs-equity allocation strategy on mutual fund holdings (`data/groww_holdings.xlsx`) and an automated ₹50,000/month SIP schedule.

Designed to run **100% in the cloud** without needing a laptop open, accessible anytime via a mobile-friendly web dashboard and automated Telegram alerts.

---

## 🏛️ Cloud Architecture Overview

```
                      +------------------------------------------+
                      |   GitHub Actions Cron Scheduler           |
                      |   (Mon-Fri at 09:00 UTC / 2:30 PM IST)    |
                      +--------------------+---------------------+
                                           |
                    30 mins prior to 3:00 PM MF Cut-off
                                           v
       +-------------------------------------------------------------------+
       |                       src/daily_job.py                            |
       |  1. Fetch AMFI daily NAVs & update holdings                       |
       |  2. Calculate 3-Sleeve Regime Scores (50% Tech + 50% Fund)        |
       |  3. Settle pending T+1 orders                                     |
       |  4. Evaluate Tier 1 SIP Rerouting & Tier 2 Corpus De-risking      |
       |  5. Update Ledger A (Tactical) vs Ledger B (Passive)              |
       |  6. Dispatch mobile alert to Telegram                             |
       +--------------------+------------------------------+-------------+
                            |                              |
                            v                              v
            +-------------------------------+    +--------------------+
            | Supabase PostgreSQL Database  |    |  Telegram Channel  |
            | (holdings, regimes, ledgers)  |    |  (@shankar_bot)    |
            +---------------+---------------+    +--------------------+
                            ^
                            | Real-time Read / Sync
                            v
            +-------------------------------+
            |  Streamlit Community Cloud    |
            |  Mobile Web Dashboard (app.py)|
            +-------------------------------+
```

---

## 💼 Active Tradable Universe (4 Funds)

Parsed directly from `data/groww_holdings.xlsx`:

| Scheme Name | AMFI Code | Sleeve | Monthly SIP | Exit Load Rule | Tax Category |
|---|---|---|---|---|---|
| **Motilal Oswal Midcap Fund Direct Growth** | `127042` | `MID_SMALL` | ₹20,000 (3rd) | 1% < 365d, Nil > 365d | Domestic Equity (12.5% LTCG / 20% STCG) |
| **Nippon India Small Cap Fund Direct Growth** | `118778` | `MID_SMALL` | ₹20,000 (3rd) | 1% < 365d, Nil > 365d | Domestic Equity (12.5% LTCG / 20% STCG) |
| **Parag Parikh Flexi Cap Fund Direct Growth** | `122639` | `NIFTY_500` | ₹10,000 (3rd) | 2% < 365d, 1% 365-730d, Nil > 730d | Domestic Equity (12.5% LTCG / 20% STCG) |
| **Edelweiss US Technology Equity FoF Direct Growth** | `148063` | `NASDAQ_100` | ₹0 (Hold Only) | 1% < 30d, Nil > 30d | Foreign FoF (24-Month LTCG Rule) |

### 🔒 Excluded Locked Holdings:
- **Mirae Asset ELSS Tax Saver Fund Direct Growth** (`₹2,95,188.91`)
- **Quant ELSS Tax Saver Fund Direct Growth** (`₹73,157.91`)
*These 3-year locked tax-saver funds are strictly excluded from tactical switches and corpus de-risking logic.*

---

## 🎯 Multi-Regime Scoring Engine (0-100)

Every trading day, each of the 3 sleeves (`NIFTY_500`, `MID_SMALL`, `NASDAQ_100`) receives a Composite Score combining:

1. **Technicals (50% Weight)**:
   - **200-DMA (30%)**: Price distance to 200-DMA & 200-DMA slope.
   - **50-EMA (25%)**: Price vs 50-EMA & Golden Cross/Death Cross status.
   - **Weekly RSI (20%)**: 14-period RSI (55-68 momentum sweet spot vs >78 froth / <35 breakdown).
   - **ATR % (10%)**: Volatility expansion / turbulence indicator.
   - **India VIX (15%)**: Market volatility index (`^INDIAVIX` for India, `^VIX` for US).

2. **Fundamentals (50% Weight)**:
   - **Index P/E Z-Score (45%)**: Historical standard deviation distance.
   - **P/B Percentile (25%)**: Historical valuation rank.
   - **Earnings Yield vs 10Y Bond Yield Spread (30%)**: $1/\text{PE} - \text{G-Sec Yield}$ (equity risk premium).

*Robust fallback mechanism: `^CRSLDX` -> `^NSEI`, `^NSEMDCP50` -> `MID150BEES.NS` -> `^NSEI`, `^NDX` -> `QQQ`, ensuring pipeline never crashes on missing tickers.*

---

## 🛡️ Tactical Rules & Friction-Aware Execution

### Tier 1: SIP Rerouting (Evaluated before 3rd of month)
- **Score $\ge$ 60**: Normal ₹50,000 monthly equity SIPs.
- **Score 40 – 59**: Divert ₹20k Mid/Small SIPs to **Shadow Cash** (~6.5% p.a. liquid yield); Parag Parikh Flexi Cap continues into equity.
- **Score < 40**: Divert **ALL ₹50,000** SIPs to Shadow Cash.

### Tier 2: Corpus Switch & Re-entry
- **De-risking Switch**: Switch existing equity units to Cash **ONLY** if:
  1. Sleeve Score < 30 (severe panic/bear breakdown) **AND**
  2. $\text{Expected Drawdown} > \text{Exit Load} + \text{Tax Drag}$ (STCG 20% / LTCG 12.5%).
  *If friction exceeds expected drawdown, units are held to protect against tax/load churn.*
- **Re-entry in 3 Tranches**:
  - **Tranche 1 (33%)**: Price reclaims 50-EMA.
  - **Tranche 2 (33%)**: Price reclaims 200-DMA.
  - **Tranche 3 (34%)**: Regime Score reclaims $\ge$ 60.

### T+1 Settlement
Orders placed at 2:30 PM IST (pre-cut-off) lock in day T closing NAV and settle on T+1.

---

## 🚀 100% Cloud Setup in 3 Steps

### Step 1: Supabase Database Setup
1. Create a free PostgreSQL project at [supabase.com](https://supabase.com).
2. Go to **SQL Editor** -> **New Query**.
3. Copy and paste the entire contents of `schema.sql` and click **Run**.
4. Retrieve your **Project URL** and **API Key** (anon or service_role) from Project Settings -> API.

### Step 2: Streamlit Community Cloud (Web Dashboard)
1. Fork or push this repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io).
3. Click **New app**, select your repo, branch `main`, and main file `app.py`.
4. In **App settings** -> **Secrets**, add:
   ```toml
   SUPABASE_URL = "https://your-project.supabase.co"
   SUPABASE_KEY = "your-supabase-key"
   TELEGRAM_BOT_TOKEN = "9278988198:AAHTaYraUL7vC8lTSCwNQwVn0KhROBIKUXg"
   TELEGRAM_CHAT_ID = "8950347796"
   ```
5. Click **Deploy**. Your dashboard is now live on a public mobile-friendly URL!

### Step 3: GitHub Actions Scheduler Setup
1. In your GitHub repository, navigate to **Settings** -> **Secrets and variables** -> **Actions**.
2. Add the following repository secrets:
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `DASHBOARD_URL` (your Streamlit app link)
3. The workflow `.github/workflows/daily_run.yml` will automatically run every Monday to Friday at **09:00 UTC (2:30 PM IST)**, 30 minutes before cut-off!

---

## 💻 Local Testing Commands

```bash
# 1. Ingest Excel file and seed active universe
python src/ingest_groww.py

# 2. Run multi-regime scoring
python src/regime_engine.py

# 3. Simulate 6-month dual ledger
python src/paper_ledger.py

# 4. Test Telegram alert dispatch
python src/telegram_bot.py

# 5. Run full daily cycle
python src/daily_job.py

# 6. Launch local Streamlit dashboard
streamlit run app.py
```
