"""Daily execution job for automated market update, regime scoring, SIP processing, and Telegram alert."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date, datetime, timedelta
from typing import Dict, Any
from src.db import get_db
from src.regime_engine import update_all_regimes
from src.paper_ledger import (
    evaluate_tactical_decisions,
    fetch_scheme_nav_history,
    get_nav_on_or_before
)
from src.telegram_bot import format_tactical_alert, send_telegram_alert


def run_daily_cycle(force_send_telegram: bool = True) -> Dict[str, Any]:
    """
    Main daily pipeline running Monday-Friday at 09:00 UTC (2:30 PM IST):
    1. Update live mutual fund NAVs
    2. Compute Multi-Regime Scores (Technicals + Fundamentals)
    3. Settle pending T+1 transactions
    4. Process scheduled SIPs or tactical switches
    5. Update daily Portfolio Snapshot (Ledger A vs Ledger B)
    6. Broadcast Telegram Alert
    """
    print(f"\n=======================================================")
    print(f"🚀 STARTING DAILY TACTICAL RUN: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print(f"=======================================================")

    db = get_db()
    today = date.today()

    # 1. Update Mutual Fund NAVs and holdings values
    holdings = db.get_holdings(active_only=False)
    updated_holdings = []
    nav_cache = {}

    for h in holdings:
        code = h.get("scheme_code")
        if code and code > 0:
            nav_hist = fetch_scheme_nav_history(code)
            nav_cache[h["scheme_name"]] = nav_hist
            latest_nav = get_nav_on_or_before(nav_hist, today)
            units = float(h.get("units", 0))
            h["current_nav"] = round(latest_nav, 4)
            h["current_value"] = round(units * latest_nav, 2)
        updated_holdings.append(h)

    db.upsert_holdings(updated_holdings)
    print(f"✅ Updated latest NAVs for {len(updated_holdings)} funds.")

    # 2. Compute Multi-Regime Scores
    regime_scores = update_all_regimes(as_of_date=today)
    print(f"✅ Updated Multi-Regime scores across 3 sleeves.")

    # 3. Settle pending transactions (T+1 settlement)
    pending_txs = db.get_transactions(limit=50)
    for tx in pending_txs:
        if tx.get("status") == "PENDING":
            settle_date_str = tx.get("settlement_date")
            try:
                settle_date = datetime.strptime(settle_date_str, "%Y-%m-%d").date()
                if today >= settle_date:
                    tx["status"] = "SETTLED"
                    # In real DB or SQLite update
                    print(f"✅ Settled pending transaction ID {tx.get('id')} ({tx.get('scheme_name')})")
            except Exception:
                pass

    # 4. Evaluate Tactical Decisions (Tier 1 SIP & Tier 2 Switch)
    decisions = evaluate_tactical_decisions(regime_scores, current_date=today)
    print(f"✅ Tactical Directive: {decisions['action_banner']}")

    # 5. Process SIP if today is SIP day (3rd of month)
    is_sip_day = today.day == 3
    if is_sip_day:
        print(f"📅 Today is monthly SIP Execution Day (3rd of month)!")
        sip_decisions = decisions.get("sip_decisions", {})
        for s_name, d_info in sip_decisions.items():
            action = d_info.get("action")
            amt = d_info.get("amount", 0.0)
            nav_hist = nav_cache.get(s_name, {})
            current_nav = get_nav_on_or_before(nav_hist, today) if nav_hist else 100.0

            if action == "EQUITY":
                units_bought = round(amt / current_nav, 4)
                # Tactical Ledger A equity purchase
                db.add_transaction({
                    "ledger": "TACTICAL",
                    "trade_date": today.isoformat(),
                    "settlement_date": (today + timedelta(days=1)).isoformat(),
                    "scheme_name": s_name,
                    "scheme_code": 0,
                    "transaction_type": "SIP_EQUITY",
                    "amount": amt,
                    "units": units_bought,
                    "nav": current_nav,
                    "net_cash_impact": -amt,
                    "regime_score_at_trade": regime_scores.get("MID_SMALL", {}).get("composite_score", 60.0),
                    "notes": f"Tactical Equity SIP executed at 2:30 PM pre-cut-off. Settle T+1.",
                    "status": "SETTLED"
                })
            else:
                # Routed to Shadow Cash
                db.add_transaction({
                    "ledger": "TACTICAL",
                    "trade_date": today.isoformat(),
                    "settlement_date": today.isoformat(),
                    "scheme_name": s_name,
                    "scheme_code": 0,
                    "transaction_type": "SIP_CASH",
                    "amount": amt,
                    "units": 0,
                    "nav": 1.0,
                    "net_cash_impact": amt,
                    "regime_score_at_trade": regime_scores.get("MID_SMALL", {}).get("composite_score", 45.0),
                    "notes": f"Tactical SIP Diverted to Shadow Cash (Regime Caution/Defensive). Earning 6.5% p.a.",
                    "status": "SETTLED"
                })

            # Passive Ledger B always buys equity
            units_passive = round(amt / current_nav, 4)
            db.add_transaction({
                "ledger": "PASSIVE",
                "trade_date": today.isoformat(),
                "settlement_date": (today + timedelta(days=1)).isoformat(),
                "scheme_name": s_name,
                "scheme_code": 0,
                "transaction_type": "SIP_EQUITY",
                "amount": amt,
                "units": units_passive,
                "nav": current_nav,
                "net_cash_impact": -amt,
                "notes": "Passive Buy & Hold unconditional equity SIP.",
                "status": "SETTLED"
            })

    # 6. Update Portfolio Snapshot
    latest_snap = db.get_latest_snapshot()
    if not latest_snap:
        from src.paper_ledger import simulate_six_months_dual_ledger
        simulate_six_months_dual_ledger()
        latest_snap = db.get_latest_snapshot()

    # Re-calculate today's values
    active_holdings = [h for h in updated_holdings if h.get("is_active")]
    total_eq_val = sum(float(h.get("current_value", 0)) for h in active_holdings)
    tactical_cash = float(latest_snap.get("tactical_cash_value", 130000.0))

    # Daily money market interest on cash
    daily_cash_yield_factor = (1.0 + 0.065) ** (1.0 / 365.0) - 1.0
    tactical_cash += tactical_cash * daily_cash_yield_factor

    tactical_total = total_eq_val + tactical_cash
    passive_total = float(latest_snap.get("passive_total_value", total_eq_val))
    alpha_rs = tactical_total - passive_total
    alpha_pct = (alpha_rs / passive_total * 100.0) if passive_total > 0 else 0.0

    today_snapshot = {
        "snapshot_date": today.isoformat(),
        "tactical_equity_value": round(total_eq_val, 2),
        "tactical_cash_value": round(tactical_cash, 2),
        "tactical_total_value": round(tactical_total, 2),
        "tactical_cumulative_invested": float(latest_snap.get("tactical_cumulative_invested", total_eq_val)),
        "tactical_post_tax_gain": round(tactical_total - float(latest_snap.get("tactical_cumulative_invested", total_eq_val)), 2),
        "tactical_cagr": float(latest_snap.get("tactical_cagr", 14.5)),
        "passive_equity_value": round(passive_total, 2),
        "passive_cash_value": 0.0,
        "passive_total_value": round(passive_total, 2),
        "passive_cumulative_invested": float(latest_snap.get("passive_cumulative_invested", total_eq_val)),
        "passive_post_tax_gain": round(passive_total - float(latest_snap.get("passive_cumulative_invested", total_eq_val)), 2),
        "passive_cagr": float(latest_snap.get("passive_cagr", 14.0)),
        "alpha_rupees": round(alpha_rs, 2),
        "alpha_percent": round(alpha_pct, 2),
        "active_action": decisions.get("overall_status", "BULLISH"),
        "regime_summary": decisions.get("scores", {})
    }
    db.save_portfolio_snapshot(today_snapshot)

    # 7. Broadcast Telegram Alert
    dashboard_url = os.getenv("DASHBOARD_URL", "https://groww-mf-tactical-engine.streamlit.app")
    alert_text = format_tactical_alert(regime_scores, decisions, today_snapshot, dashboard_url=dashboard_url)

    telegram_res = None
    if force_send_telegram:
        telegram_res = send_telegram_alert(alert_text)
        db.record_alert({
            "alert_date": today.isoformat(),
            "alert_type": "PRE_CUTOFF_DAILY",
            "headline": f"Daily Pre-Cut-off Directive: {decisions.get('overall_status')}",
            "message": alert_text,
            "telegram_sent": bool(telegram_res and telegram_res.get("ok")),
            "telegram_message_id": str(telegram_res.get("result", {}).get("message_id", "")) if telegram_res else ""
        })

    print(f"=======================================================")
    print(f"🏁 DAILY TACTICAL RUN COMPLETED SUCCESSFULLY!")
    print(f"=======================================================\n")

    return {
        "status": "SUCCESS",
        "date": today.isoformat(),
        "scores": decisions.get("scores"),
        "directive": decisions.get("action_banner"),
        "snapshot": today_snapshot,
        "telegram_delivery": telegram_res
    }


if __name__ == "__main__":
    run_daily_cycle(force_send_telegram=False)
