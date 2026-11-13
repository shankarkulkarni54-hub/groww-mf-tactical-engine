-- ==============================================================================
-- Supabase PostgreSQL Schema for Groww Mutual Fund Tactical Allocation Engine
-- Run this script in the Supabase SQL Editor (SQL -> New Query -> Run)
-- ==============================================================================

-- 1. HOLDINGS TABLE
CREATE TABLE IF NOT EXISTS holdings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scheme_name TEXT NOT NULL UNIQUE,
    scheme_code INTEGER NOT NULL,
    amc TEXT,
    category TEXT,
    sub_category TEXT,
    folio_no TEXT,
    units NUMERIC(16, 4) NOT NULL DEFAULT 0,
    invested_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    current_nav NUMERIC(16, 4) NOT NULL DEFAULT 0,
    current_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    benchmark_ticker TEXT,
    sleeve TEXT NOT NULL, -- 'NIFTY_500', 'MID_SMALL', 'NASDAQ_100'
    sip_amount NUMERIC(16, 2) NOT NULL DEFAULT 0,
    sip_day INTEGER NOT NULL DEFAULT 3,
    exit_load_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    tax_category TEXT NOT NULL DEFAULT 'DOMESTIC_EQUITY', -- 'DOMESTIC_EQUITY', 'FOREIGN_FOF'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. REGIME SCORES TABLE
CREATE TABLE IF NOT EXISTS regime_scores (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    score_date DATE NOT NULL DEFAULT CURRENT_DATE,
    sleeve TEXT NOT NULL, -- 'NIFTY_500', 'MID_SMALL', 'NASDAQ_100'
    composite_score NUMERIC(5, 2) NOT NULL,
    technical_score NUMERIC(5, 2) NOT NULL,
    fundamental_score NUMERIC(5, 2) NOT NULL,
    regime_status TEXT NOT NULL, -- 'BULLISH', 'CAUTION', 'DEFENSIVE'
    dma_200 NUMERIC(12, 2),
    ema_50 NUMERIC(12, 2),
    price NUMERIC(12, 2),
    rsi_weekly NUMERIC(5, 2),
    atr NUMERIC(12, 2),
    vix NUMERIC(6, 2),
    pe_ratio NUMERIC(6, 2),
    pe_zscore NUMERIC(5, 2),
    pb_ratio NUMERIC(6, 2),
    pb_percentile NUMERIC(5, 2),
    earnings_yield NUMERIC(5, 2),
    bond_yield NUMERIC(5, 2),
    yield_spread NUMERIC(5, 2),
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_regime_sleeve_date UNIQUE (score_date, sleeve)
);

-- 3. TRANSACTIONS TABLE
CREATE TABLE IF NOT EXISTS transactions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ledger TEXT NOT NULL, -- 'TACTICAL' or 'PASSIVE'
    trade_date DATE NOT NULL,
    settlement_date DATE NOT NULL,
    scheme_name TEXT NOT NULL,
    scheme_code INTEGER,
    transaction_type TEXT NOT NULL, -- 'SEED', 'SIP_EQUITY', 'SIP_CASH', 'SWITCH_TO_CASH', 'REENTRY_BUY'
    amount NUMERIC(16, 2) NOT NULL,
    units NUMERIC(16, 4) NOT NULL DEFAULT 0,
    nav NUMERIC(16, 4) NOT NULL DEFAULT 0,
    exit_load_amount NUMERIC(16, 2) NOT NULL DEFAULT 0,
    stcg_tax NUMERIC(16, 2) NOT NULL DEFAULT 0,
    ltcg_tax NUMERIC(16, 2) NOT NULL DEFAULT 0,
    net_cash_impact NUMERIC(16, 2) NOT NULL DEFAULT 0,
    regime_score_at_trade NUMERIC(5, 2),
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'SETTLED', -- 'PENDING', 'SETTLED'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. PORTFOLIO SNAPSHOTS TABLE (Ledger A vs Ledger B Daily Tracker)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    tactical_equity_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    tactical_cash_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    tactical_total_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    tactical_cumulative_invested NUMERIC(16, 2) NOT NULL DEFAULT 0,
    tactical_post_tax_gain NUMERIC(16, 2) NOT NULL DEFAULT 0,
    tactical_cagr NUMERIC(6, 2) DEFAULT 0,
    passive_equity_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    passive_cash_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    passive_total_value NUMERIC(16, 2) NOT NULL DEFAULT 0,
    passive_cumulative_invested NUMERIC(16, 2) NOT NULL DEFAULT 0,
    passive_post_tax_gain NUMERIC(16, 2) NOT NULL DEFAULT 0,
    passive_cagr NUMERIC(6, 2) DEFAULT 0,
    alpha_rupees NUMERIC(16, 2) NOT NULL DEFAULT 0,
    alpha_percent NUMERIC(6, 2) NOT NULL DEFAULT 0,
    active_action TEXT,
    regime_summary JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. DAILY ALERTS LOG TABLE
CREATE TABLE IF NOT EXISTS daily_alerts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_date DATE NOT NULL,
    alert_type TEXT NOT NULL, -- 'DAILY_STATUS', 'SIP_EXECUTION', 'SWITCH_SIGNAL', 'REENTRY_SIGNAL'
    headline TEXT NOT NULL,
    message TEXT NOT NULL,
    telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
    telegram_message_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. APP STATE TABLE (Key-Value Store for engine parameters & state)
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for lightning fast queries
CREATE INDEX IF NOT EXISTS idx_regime_scores_date ON regime_scores(score_date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_ledger ON transactions(ledger, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status, settlement_date);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_date ON portfolio_snapshots(snapshot_date DESC);

-- Enable Row Level Security (RLS) & Grant full access to authenticated + anon with key
ALTER TABLE holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE regime_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_state ENABLE ROW LEVEL SECURITY;

-- Allow anon and service_role full read/write for engine automation
DROP POLICY IF EXISTS "anon_full_access_holdings" ON holdings;
CREATE POLICY "anon_full_access_holdings" ON holdings FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_full_access_regime_scores" ON regime_scores;
CREATE POLICY "anon_full_access_regime_scores" ON regime_scores FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_full_access_transactions" ON transactions;
CREATE POLICY "anon_full_access_transactions" ON transactions FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_full_access_portfolio_snapshots" ON portfolio_snapshots;
CREATE POLICY "anon_full_access_portfolio_snapshots" ON portfolio_snapshots FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_full_access_daily_alerts" ON daily_alerts;
CREATE POLICY "anon_full_access_daily_alerts" ON daily_alerts FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon_full_access_app_state" ON app_state;
CREATE POLICY "anon_full_access_app_state" ON app_state FOR ALL USING (true) WITH CHECK (true);
