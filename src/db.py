"""Database interface supporting Supabase PostgreSQL with seamless SQLite local fallback."""

import os
import json
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

# Check Streamlit secrets if running inside Streamlit Cloud
def _get_env_or_secret(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val.strip()
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default

SUPABASE_URL = _get_env_or_secret("SUPABASE_URL", "")
SUPABASE_KEY = _get_env_or_secret("SUPABASE_KEY", "")

# Local SQLite fallback path
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)
SQLITE_PATH = os.path.join(DB_DIR, "tactical_engine.db")


class SupabaseDB:
    def __init__(self, url: str, key: str):
        from supabase import create_client, Client
        self.client: Client = create_client(url, key)

    def is_healthy(self) -> bool:
        try:
            self.client.table("holdings").select("id").limit(1).execute()
            return True
        except Exception as e:
            print(f"[SupabaseDB] Healthcheck warning: {e}")
            return False

    def upsert_holdings(self, holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for h in holdings:
            h["updated_at"] = datetime.now().isoformat()
        res = self.client.table("holdings").upsert(holdings, on_conflict="scheme_name").execute()
        return res.data

    def get_holdings(self, active_only: bool = True) -> List[Dict[str, Any]]:
        query = self.client.table("holdings").select("*")
        if active_only:
            query = query.eq("is_active", True)
        res = query.order("invested_value", desc=True).execute()
        return res.data or []

    def record_regime_scores(self, scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for s in scores:
            if "created_at" not in s:
                s["created_at"] = datetime.now().isoformat()
        res = self.client.table("regime_scores").upsert(scores, on_conflict="score_date,sleeve").execute()
        return res.data

    def get_latest_regime_scores(self) -> Dict[str, Dict[str, Any]]:
        res = self.client.table("regime_scores").select("*").order("score_date", desc=True).limit(10).execute()
        data = res.data or []
        latest_by_sleeve = {}
        for row in data:
            sleeve = row.get("sleeve")
            if sleeve and sleeve not in latest_by_sleeve:
                latest_by_sleeve[sleeve] = row
        return latest_by_sleeve

    def add_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        if "created_at" not in tx:
            tx["created_at"] = datetime.now().isoformat()
        res = self.client.table("transactions").insert(tx).execute()
        return res.data[0] if res.data else {}

    def get_transactions(self, ledger: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        query = self.client.table("transactions").select("*")
        if ledger:
            query = query.eq("ledger", ledger)
        res = query.order("trade_date", desc=True).limit(limit).execute()
        return res.data or []

    def save_portfolio_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if "created_at" not in snapshot:
            snapshot["created_at"] = datetime.now().isoformat()
        res = self.client.table("portfolio_snapshots").upsert(snapshot, on_conflict="snapshot_date").execute()
        return res.data[0] if res.data else {}

    def get_portfolio_snapshots(self, days: int = 180) -> List[Dict[str, Any]]:
        res = self.client.table("portfolio_snapshots").select("*").order("snapshot_date", desc=False).limit(days).execute()
        return res.data or []

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        res = self.client.table("portfolio_snapshots").select("*").order("snapshot_date", desc=True).limit(1).execute()
        return res.data[0] if res.data else None

    def record_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        if "created_at" not in alert:
            alert["created_at"] = datetime.now().isoformat()
        res = self.client.table("daily_alerts").insert(alert).execute()
        return res.data[0] if res.data else {}

    def get_latest_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        res = self.client.table("daily_alerts").select("*").order("created_at", desc=True).limit(limit).execute()
        return res.data or []

    def set_app_state(self, key: str, value: Any) -> None:
        self.client.table("app_state").upsert({"key": key, "value": value, "updated_at": datetime.now().isoformat()}).execute()

    def get_app_state(self, key: str, default: Any = None) -> Any:
        res = self.client.table("app_state").select("value").eq("key", key).execute()
        if res.data:
            return res.data[0].get("value")
        return default


class SQLiteFallbackDB:
    def __init__(self, db_path: str = SQLITE_PATH):
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scheme_name TEXT UNIQUE NOT NULL,
                scheme_code INTEGER NOT NULL,
                amc TEXT,
                category TEXT,
                sub_category TEXT,
                folio_no TEXT,
                units REAL NOT NULL DEFAULT 0,
                invested_value REAL NOT NULL DEFAULT 0,
                current_nav REAL NOT NULL DEFAULT 0,
                current_value REAL NOT NULL DEFAULT 0,
                benchmark_ticker TEXT,
                sleeve TEXT NOT NULL,
                sip_amount REAL NOT NULL DEFAULT 0,
                sip_day INTEGER NOT NULL DEFAULT 3,
                exit_load_rules TEXT NOT NULL DEFAULT '{}',
                tax_category TEXT NOT NULL DEFAULT 'DOMESTIC_EQUITY',
                is_active INTEGER NOT NULL DEFAULT 1,
                is_locked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS regime_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                score_date TEXT NOT NULL,
                sleeve TEXT NOT NULL,
                composite_score REAL NOT NULL,
                technical_score REAL NOT NULL,
                fundamental_score REAL NOT NULL,
                regime_status TEXT NOT NULL,
                dma_200 REAL,
                ema_50 REAL,
                price REAL,
                rsi_weekly REAL,
                atr REAL,
                vix REAL,
                pe_ratio REAL,
                pe_zscore REAL,
                pb_ratio REAL,
                pb_percentile REAL,
                earnings_yield REAL,
                bond_yield REAL,
                yield_spread REAL,
                details TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(score_date, sleeve)
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ledger TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                settlement_date TEXT NOT NULL,
                scheme_name TEXT NOT NULL,
                scheme_code INTEGER,
                transaction_type TEXT NOT NULL,
                amount REAL NOT NULL,
                units REAL NOT NULL DEFAULT 0,
                nav REAL NOT NULL DEFAULT 0,
                exit_load_amount REAL NOT NULL DEFAULT 0,
                stcg_tax REAL NOT NULL DEFAULT 0,
                ltcg_tax REAL NOT NULL DEFAULT 0,
                net_cash_impact REAL NOT NULL DEFAULT 0,
                regime_score_at_trade REAL,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'SETTLED',
                created_at TEXT NOT NULL
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT UNIQUE NOT NULL,
                tactical_equity_value REAL NOT NULL DEFAULT 0,
                tactical_cash_value REAL NOT NULL DEFAULT 0,
                tactical_total_value REAL NOT NULL DEFAULT 0,
                tactical_cumulative_invested REAL NOT NULL DEFAULT 0,
                tactical_post_tax_gain REAL NOT NULL DEFAULT 0,
                tactical_cagr REAL DEFAULT 0,
                passive_equity_value REAL NOT NULL DEFAULT 0,
                passive_cash_value REAL NOT NULL DEFAULT 0,
                passive_total_value REAL NOT NULL DEFAULT 0,
                passive_cumulative_invested REAL NOT NULL DEFAULT 0,
                passive_post_tax_gain REAL NOT NULL DEFAULT 0,
                passive_cagr REAL DEFAULT 0,
                alpha_rupees REAL NOT NULL DEFAULT 0,
                alpha_percent REAL NOT NULL DEFAULT 0,
                active_action TEXT,
                regime_summary TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_date TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                headline TEXT NOT NULL,
                message TEXT NOT NULL,
                telegram_sent INTEGER NOT NULL DEFAULT 0,
                telegram_message_id TEXT,
                created_at TEXT NOT NULL
            );
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)
            conn.commit()

    def is_healthy(self) -> bool:
        return True

    def upsert_holdings(self, holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now_str = datetime.now().isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            for h in holdings:
                exit_load_str = json.dumps(h.get("exit_load_rules", {})) if isinstance(h.get("exit_load_rules"), dict) else str(h.get("exit_load_rules", "{}"))
                cur.execute("""
                INSERT INTO holdings (
                    scheme_name, scheme_code, amc, category, sub_category, folio_no,
                    units, invested_value, current_nav, current_value, benchmark_ticker,
                    sleeve, sip_amount, sip_day, exit_load_rules, tax_category,
                    is_active, is_locked, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scheme_name) DO UPDATE SET
                    units=excluded.units,
                    invested_value=excluded.invested_value,
                    current_nav=excluded.current_nav,
                    current_value=excluded.current_value,
                    sip_amount=excluded.sip_amount,
                    updated_at=excluded.updated_at
                """, (
                    h["scheme_name"], h.get("scheme_code", 0), h.get("amc", ""),
                    h.get("category", ""), h.get("sub_category", ""), h.get("folio_no", ""),
                    float(h.get("units", 0)), float(h.get("invested_value", 0)),
                    float(h.get("current_nav", 0)), float(h.get("current_value", 0)),
                    h.get("benchmark_ticker", ""), h.get("sleeve", ""),
                    float(h.get("sip_amount", 0)), int(h.get("sip_day", 3)),
                    exit_load_str, h.get("tax_category", "DOMESTIC_EQUITY"),
                    1 if h.get("is_active", True) else 0,
                    1 if h.get("is_locked", False) else 0,
                    now_str, now_str
                ))
            conn.commit()
        return holdings

    def get_holdings(self, active_only: bool = True) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if active_only:
                cur.execute("SELECT * FROM holdings WHERE is_active=1 ORDER BY invested_value DESC")
            else:
                cur.execute("SELECT * FROM holdings ORDER BY invested_value DESC")
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if isinstance(r.get("exit_load_rules"), str):
                    try:
                        r["exit_load_rules"] = json.loads(r["exit_load_rules"])
                    except Exception:
                        pass
                r["is_active"] = bool(r.get("is_active"))
                r["is_locked"] = bool(r.get("is_locked"))
            return rows

    def record_regime_scores(self, scores: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now_str = datetime.now().isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            for s in scores:
                details_str = json.dumps(s.get("details", {})) if isinstance(s.get("details"), dict) else str(s.get("details", "{}"))
                cur.execute("""
                INSERT INTO regime_scores (
                    score_date, sleeve, composite_score, technical_score, fundamental_score,
                    regime_status, dma_200, ema_50, price, rsi_weekly, atr, vix,
                    pe_ratio, pe_zscore, pb_ratio, pb_percentile, earnings_yield,
                    bond_yield, yield_spread, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(score_date, sleeve) DO UPDATE SET
                    composite_score=excluded.composite_score,
                    technical_score=excluded.technical_score,
                    fundamental_score=excluded.fundamental_score,
                    regime_status=excluded.regime_status,
                    dma_200=excluded.dma_200,
                    ema_50=excluded.ema_50,
                    price=excluded.price,
                    rsi_weekly=excluded.rsi_weekly,
                    atr=excluded.atr,
                    vix=excluded.vix,
                    pe_ratio=excluded.pe_ratio,
                    pe_zscore=excluded.pe_zscore,
                    pb_ratio=excluded.pb_ratio,
                    pb_percentile=excluded.pb_percentile,
                    earnings_yield=excluded.earnings_yield,
                    bond_yield=excluded.bond_yield,
                    yield_spread=excluded.yield_spread,
                    details=excluded.details
                """, (
                    str(s.get("score_date", date.today().isoformat())),
                    s["sleeve"], float(s.get("composite_score", 50)),
                    float(s.get("technical_score", 50)), float(s.get("fundamental_score", 50)),
                    s.get("regime_status", "NEUTRAL"),
                    s.get("dma_200"), s.get("ema_50"), s.get("price"),
                    s.get("rsi_weekly"), s.get("atr"), s.get("vix"),
                    s.get("pe_ratio"), s.get("pe_zscore"), s.get("pb_ratio"),
                    s.get("pb_percentile"), s.get("earnings_yield"),
                    s.get("bond_yield"), s.get("yield_spread"),
                    details_str, now_str
                ))
            conn.commit()
        return scores

    def get_latest_regime_scores(self) -> Dict[str, Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM regime_scores ORDER BY score_date DESC, id DESC LIMIT 20")
            rows = [dict(r) for r in cur.fetchall()]
            latest = {}
            for r in rows:
                sleeve = r["sleeve"]
                if sleeve not in latest:
                    if isinstance(r.get("details"), str):
                        try:
                            r["details"] = json.loads(r["details"])
                        except Exception:
                            pass
                    latest[sleeve] = r
            return latest

    def add_transaction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        now_str = datetime.now().isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO transactions (
                ledger, trade_date, settlement_date, scheme_name, scheme_code,
                transaction_type, amount, units, nav, exit_load_amount,
                stcg_tax, ltcg_tax, net_cash_impact, regime_score_at_trade,
                notes, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tx.get("ledger", "TACTICAL"),
                str(tx.get("trade_date", date.today().isoformat())),
                str(tx.get("settlement_date", date.today().isoformat())),
                tx.get("scheme_name", ""),
                tx.get("scheme_code", 0),
                tx.get("transaction_type", "SIP_EQUITY"),
                float(tx.get("amount", 0)),
                float(tx.get("units", 0)),
                float(tx.get("nav", 0)),
                float(tx.get("exit_load_amount", 0)),
                float(tx.get("stcg_tax", 0)),
                float(tx.get("ltcg_tax", 0)),
                float(tx.get("net_cash_impact", 0)),
                tx.get("regime_score_at_trade"),
                tx.get("notes", ""),
                tx.get("status", "SETTLED"),
                now_str
            ))
            tx_id = cur.lastrowid
            conn.commit()
            tx["id"] = tx_id
            return tx

    def get_transactions(self, ledger: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            if ledger:
                cur.execute("SELECT * FROM transactions WHERE ledger=? ORDER BY trade_date DESC, id DESC LIMIT ?", (ledger, limit))
            else:
                cur.execute("SELECT * FROM transactions ORDER BY trade_date DESC, id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def save_portfolio_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        now_str = datetime.now().isoformat()
        regime_str = json.dumps(snapshot.get("regime_summary", {})) if isinstance(snapshot.get("regime_summary"), dict) else str(snapshot.get("regime_summary", "{}"))
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO portfolio_snapshots (
                snapshot_date, tactical_equity_value, tactical_cash_value, tactical_total_value,
                tactical_cumulative_invested, tactical_post_tax_gain, tactical_cagr,
                passive_equity_value, passive_cash_value, passive_total_value,
                passive_cumulative_invested, passive_post_tax_gain, passive_cagr,
                alpha_rupees, alpha_percent, active_action, regime_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                tactical_equity_value=excluded.tactical_equity_value,
                tactical_cash_value=excluded.tactical_cash_value,
                tactical_total_value=excluded.tactical_total_value,
                tactical_cumulative_invested=excluded.tactical_cumulative_invested,
                tactical_post_tax_gain=excluded.tactical_post_tax_gain,
                tactical_cagr=excluded.tactical_cagr,
                passive_equity_value=excluded.passive_equity_value,
                passive_cash_value=excluded.passive_cash_value,
                passive_total_value=excluded.passive_total_value,
                passive_cumulative_invested=excluded.passive_cumulative_invested,
                passive_post_tax_gain=excluded.passive_post_tax_gain,
                passive_cagr=excluded.passive_cagr,
                alpha_rupees=excluded.alpha_rupees,
                alpha_percent=excluded.alpha_percent,
                active_action=excluded.active_action,
                regime_summary=excluded.regime_summary
            """, (
                str(snapshot.get("snapshot_date", date.today().isoformat())),
                float(snapshot.get("tactical_equity_value", 0)),
                float(snapshot.get("tactical_cash_value", 0)),
                float(snapshot.get("tactical_total_value", 0)),
                float(snapshot.get("tactical_cumulative_invested", 0)),
                float(snapshot.get("tactical_post_tax_gain", 0)),
                float(snapshot.get("tactical_cagr", 0)),
                float(snapshot.get("passive_equity_value", 0)),
                float(snapshot.get("passive_cash_value", 0)),
                float(snapshot.get("passive_total_value", 0)),
                float(snapshot.get("passive_cumulative_invested", 0)),
                float(snapshot.get("passive_post_tax_gain", 0)),
                float(snapshot.get("passive_cagr", 0)),
                float(snapshot.get("alpha_rupees", 0)),
                float(snapshot.get("alpha_percent", 0)),
                snapshot.get("active_action", ""),
                regime_str, now_str
            ))
            conn.commit()
        return snapshot

    def get_portfolio_snapshots(self, days: int = 180) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_snapshots ORDER BY snapshot_date ASC LIMIT ?", (days,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if isinstance(r.get("regime_summary"), str):
                    try:
                        r["regime_summary"] = json.loads(r["regime_summary"])
                    except Exception:
                        pass
            return rows

    def get_latest_snapshot(self) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            if isinstance(res.get("regime_summary"), str):
                try:
                    res["regime_summary"] = json.loads(res["regime_summary"])
                except Exception:
                    pass
            return res

    def record_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        now_str = datetime.now().isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO daily_alerts (
                alert_date, alert_type, headline, message, telegram_sent,
                telegram_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(alert.get("alert_date", date.today().isoformat())),
                alert.get("alert_type", "DAILY_STATUS"),
                alert.get("headline", ""),
                alert.get("message", ""),
                1 if alert.get("telegram_sent") else 0,
                alert.get("telegram_message_id", ""),
                now_str
            ))
            conn.commit()
        return alert

    def get_latest_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM daily_alerts ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                r["telegram_sent"] = bool(r.get("telegram_sent"))
            return rows

    def set_app_state(self, key: str, value: Any) -> None:
        val_str = json.dumps(value)
        now_str = datetime.now().isoformat()
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
            INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """, (key, val_str, now_str))
            conn.commit()

    def get_app_state(self, key: str, default: Any = None) -> Any:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM app_state WHERE key=?", (key,))
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]
            return default


def get_db():
    """
    Factory returning either SupabaseDB if credentials are provided and valid,
    or SQLiteFallbackDB for seamless local execution.
    """
    url = _get_env_or_secret("SUPABASE_URL", "")
    key = _get_env_or_secret("SUPABASE_KEY", "")

    if url and key and "supabase.co" in url and key != "YOUR_SUPABASE_KEY":
        try:
            db = SupabaseDB(url, key)
            if db.is_healthy():
                return db
            print("[Database] Supabase is not yet initialized with schema. Using local fallback temporarily.")
        except Exception as e:
            print(f"[Database] Could not connect to Supabase: {e}. Falling back to SQLite.")

    return SQLiteFallbackDB()
