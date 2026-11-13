"""Telegram Bot notification module for daily pre-cut-off tactical alerts."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from datetime import datetime, date
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from src.db import get_db

load_dotenv()


def _get_secret(key: str, default: str = "") -> str:
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


def format_tactical_alert(
    regime_scores: Dict[str, Dict[str, Any]],
    decisions: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]] = None,
    dashboard_url: str = "https://share.streamlit.io"
) -> str:
    """Formats an executive, mobile-friendly Telegram alert with HTML tags."""
    now_ist = datetime.now().strftime("%d %b %Y | %I:%M %p IST")

    # Header
    msg = [
        "⚡ <b>GROWW TACTICAL ENGINE ALERT</b>",
        f"📅 <i>{now_ist}</i>",
        "⏰ <b>30-MIN PRE-CUT-OFF WARNING (Cut-off: 3:00 PM IST)</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🎯 <b>MARKET REGIME SCORES (0-100)</b>:"
    ]

    # Sleeve scores
    emojis = {"BULLISH": "🟢", "CAUTION": "🟡", "DEFENSIVE": "🔴"}

    for sleeve, label in [
        ("NIFTY_500", "Nifty 500 (Flexi Cap)"),
        ("MID_SMALL", "Mid & Small Cap"),
        ("NASDAQ_100", "NASDAQ 100 (US Tech)")
    ]:
        s = regime_scores.get(sleeve, {})
        comp = s.get("composite_score", 50.0)
        status = s.get("regime_status", "NEUTRAL")
        emoji = emojis.get(status, "⚪")
        rsi = s.get("rsi_weekly", 50.0)
        vix = s.get("vix", 15.0)
        dma_dist = s.get("details", {}).get("dma_dist_pct", 0.0)
        dist_sign = "+" if dma_dist >= 0 else ""

        msg.append(
            f"{emoji} <b>{label}</b>: <b>{comp:.1f}</b>/100 ({status})\n"
            f"   └ 200-DMA: {dist_sign}{dma_dist:.1f}% | RSI: {rsi:.1f} | VIX: {vix:.1f}"
        )

    msg.append("━━━━━━━━━━━━━━━━━━━━━")
    msg.append("📌 <b>TODAY'S TACTICAL DIRECTIVE</b>:")
    msg.append(f"<b>{decisions.get('action_banner', 'Normal Allocation')}</b>\n")

    # SIP Actions
    total_cash_sip = decisions.get("total_sip_cash", 0.0)
    total_eq_sip = decisions.get("total_sip_equity", 50000.0)

    if total_cash_sip > 0:
        msg.append(f"• <b>SIP Rerouting</b>: ₹{total_cash_sip:,.0f} diverted to Shadow Cash (6.5% p.a.).")
        msg.append(f"• <b>Equity SIP</b>: ₹{total_eq_sip:,.0f} continues into Core Equity.")
    else:
        msg.append("• <b>SIP Schedule</b>: Full ₹50,000 active in equity mutual funds.")

    # Corpus Switch checks
    switches = decisions.get("switch_signals", [])
    if switches:
        for sw in switches:
            if sw.get("action") == "SWITCH_TO_CASH":
                msg.append(f"🚨 <b>SWITCH TRIGGERED</b>: {sw['scheme_name']} -> Cash (Expected DD > Friction).")
            else:
                msg.append(f"🛡️ <b>HOLD CONFIRMED</b>: {sw['scheme_name']} retained (Friction drag exceeds expected drawdown).")

    # Valuation & Alpha
    if snapshot:
        tac_val = snapshot.get("tactical_total_value", 0.0)
        tac_cash = snapshot.get("tactical_cash_value", 0.0)
        pas_val = snapshot.get("passive_total_value", 0.0)
        alpha_rs = snapshot.get("alpha_rupees", 0.0)
        alpha_sign = "+" if alpha_rs >= 0 else ""

        msg.append("━━━━━━━━━━━━━━━━━━━━━")
        msg.append("📊 <b>PORTFOLIO PERFORMANCE</b>:")
        msg.append(f"• <b>Tactical Ledger A</b>: ₹{tac_val:,.2f}")
        msg.append(f"  └ Equity: ₹{tac_val - tac_cash:,.2f} | Cash: ₹{tac_cash:,.2f}")
        msg.append(f"• <b>Passive Ledger B</b>:  ₹{pas_val:,.2f}")
        msg.append(f"• <b>Tactical Alpha</b>:    <b>{alpha_sign}₹{alpha_rs:,.2f}</b> ({snapshot.get('alpha_percent', 0.0):+.2f}%)")

    msg.append("━━━━━━━━━━━━━━━━━━━━━")
    msg.append(f"📱 <a href='{dashboard_url}'>Open Mobile Web Dashboard</a>")

    return "\n".join(msg)


def send_telegram_alert(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None
) -> Dict[str, Any]:
    """Sends HTML formatted message to Telegram chat."""
    token = bot_token or _get_secret("TELEGRAM_BOT_TOKEN")
    cid = chat_id or _get_secret("TELEGRAM_CHAT_ID")

    if not token or not cid:
        print("[TelegramBot] Warning: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing.")
        return {"ok": False, "error": "Credentials missing"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        res = r.json()
        if res.get("ok"):
            print(f"✅ Telegram alert delivered successfully! Message ID: {res['result']['message_id']}")
        else:
            print(f"❌ Telegram API returned error: {res}")
        return res
    except Exception as e:
        print(f"[TelegramBot] Exception sending message: {e}")
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    from src.regime_engine import update_all_regimes
    from src.paper_ledger import evaluate_tactical_decisions

    db = get_db()
    scores = update_all_regimes()
    dec = evaluate_tactical_decisions(scores)
    snap = db.get_latest_snapshot()

    alert_text = format_tactical_alert(scores, dec, snap)
    print("\n--- SAMPLE TELEGRAM ALERT ---")
    print(alert_text)
    print("-----------------------------\n")

    # Send live alert test
    resp = send_telegram_alert(alert_text)
    print("Delivery response:", resp)
