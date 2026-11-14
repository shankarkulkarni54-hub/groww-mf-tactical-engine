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

try:
    from src.regime_engine import score_unrestricted_universe
except Exception:
    score_unrestricted_universe = None

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
    now = datetime.now()
    now_ist = now.strftime("%d %b %Y | %I:%M %p IST")
    day_of_month = now.day

    has_emergency_switch = any(s.get("action") == "SWITCH_TO_CASH" for s in decisions.get("switch_signals", []))
    is_action_window = day_of_month in [1, 2]
    is_execution_day = day_of_month == 3

    # Header category banner
    if has_emergency_switch:
        header_banner = "🚨 <b>[EMERGENCY ACTION REQUIRED - Crash Alert]</b>"
    elif is_action_window:
        header_banner = "⚡ <b>[ACTIONABLE SIP DIRECTIVE - Window Open]</b>"
    elif is_execution_day:
        header_banner = "📅 <b>[SIP EXECUTION DAY - 3rd of Month]</b>"
    else:
        header_banner = "ℹ️ <b>[INFO ONLY - No Action Today]</b>"

    msg = [
        "🛡️ <b>GROWW TACTICAL ENGINE</b>",
        header_banner,
        f"📅 <i>{now_ist}</i>",
        "⏰ <b>30-MIN PRE-CUT-OFF (Cut-off: 3:00 PM IST)</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🎯 <b>REGIME SCORES (Spot vs 30-Day Avg)</b>:"
    ]

    emojis = {"BULLISH": "🟢", "CAUTION": "🟡", "DEFENSIVE": "🔴"}

    for sleeve, label in [
        ("NIFTY_500", "Nifty 500 (Flexi Cap)"),
        ("MID_SMALL", "Mid & Small Cap"),
        ("NASDAQ_100", "NASDAQ 100 (US Tech)")
    ]:
        s = regime_scores.get(sleeve, {})
        spot = float(s.get("spot_score", s.get("composite_score", 50.0)))
        rolling = float(s.get("rolling_avg_score", s.get("composite_score", 50.0)))
        status = s.get("regime_status", "NEUTRAL")
        rolling_status = s.get("rolling_status", "NEUTRAL")
        emoji = emojis.get(status, "⚪")
        rsi = s.get("rsi_weekly", 50.0)
        vix = s.get("vix", 15.0)
        dma_dist = s.get("details", {}).get("dma_dist_pct", 0.0)
        dist_sign = "+" if dma_dist >= 0 else ""

        msg.append(
            f"{emoji} <b>{label}</b>:\n"
            f"   • <b>Spot Score: {spot:.1f}</b>/100 ({status})\n"
            f"   • <b>30-Day Avg: {rolling:.1f}</b>/100 ({rolling_status}) [Governs 3rd SIP]\n"
            f"   └ 200-DMA: {dist_sign}{dma_dist:.1f}% | RSI: {rsi:.1f} | VIX: {vix:.1f}"
        )

    # Fetch AI Advisor recommendations if available
    ai_picks = []
    ai_thesis = ""
    if score_unrestricted_universe:
        try:
            ai_rep = score_unrestricted_universe(now.date())
            ai_picks = ai_rep.get("top_picks", [])
            ai_thesis = ai_rep.get("thesis_summary", "")
        except Exception as e:
            print(f"[TelegramBot] Warning: Could not score unrestricted universe: {e}")

    msg.append("━━━━━━━━━━━━━━━━━━━━━")
    msg.append("📌 <b>ACTION DIRECTIVE & GUIDANCE</b>:")
    msg.append(f"<b>{decisions.get('action_badge', 'No Action Required Today')}</b>\n")

    total_cash_sip = decisions.get("total_sip_cash", 0.0)
    total_eq_sip = decisions.get("total_sip_equity", 50000.0)

    if is_action_window:
        msg.append(f"⚡ <b>ACTION REQUIRED ON GROWW (For 3rd SIP)</b>:")
        msg.append(f"📦 <b>1. Passive Groww SIP Plan:</b>")
        msg.append(f"• Equity: ₹{total_eq_sip:,.0f} | Shadow Cash: ₹{total_cash_sip:,.0f}")
        for f_name, d_info in decisions.get("sip_decisions", {}).items():
            short_name = f_name.replace(" Direct Growth", "")
            msg.append(f"  └ {short_name}: <b>{d_info['action']}</b> (₹{d_info['amount']:,.0f})")

        if ai_picks:
            msg.append(f"\n🏆 <b>2. Unrestricted AI Advisor Directive:</b>")
            for p in ai_picks:
                msg.append(f"  • <b>₹{p['allocation_amount']:,.0f}</b> in <b>{p['short_name']}</b> (Score {p['score']:.0f})")
                msg.append(f"    └ <i>{p['thesis']}</i>")
            msg.append("  └ <i>Smart Switching: 0.005% stamp duty, 0% exit load on fresh SIPs.</i>")

    elif is_execution_day:
        msg.append(f"• Auto-debit executing today: ₹{total_eq_sip:,.0f} Equity | ₹{total_cash_sip:,.0f} Shadow Cash.")
        if ai_picks:
            msg.append(f"• <b>AI Top Picks Today:</b> {ai_picks[0]['short_name']} + {ai_picks[1]['short_name']}")
    else:
        msg.append(f"• <b>Daily Status:</b> Outside the monthly SIP window. All active units held.")
        msg.append(f"• <b>Next Action Window:</b> {decisions.get('window_status_label')}")
        msg.append(f"• <i>Groww SIP Preview:</i> ₹{total_eq_sip:,.0f} Equity | ₹{total_cash_sip:,.0f} Cash")
        if ai_picks and len(ai_picks) >= 2:
            msg.append(f"• <i>AI Advisor Preview:</i> ₹25k {ai_picks[0]['short_name']} + ₹25k {ai_picks[1]['short_name']}")

    # Emergency switches
    switches = decisions.get("switch_signals", [])
    if switches:
        for sw in switches:
            if sw.get("action") == "SWITCH_TO_CASH":
                msg.append(f"\n🚨 <b>EMERGENCY SWITCH TRIGGERED:</b> {sw['scheme_name']} -> Cash (Expected DD > Friction).")
            else:
                msg.append(f"\n🛡️ <b>HOLD CONFIRMED:</b> {sw['scheme_name']} retained (Friction drag exceeds expected drawdown).")

    # Valuation & Alpha
    if snapshot:
        tac_val = snapshot.get("tactical_total_value", 0.0)
        tac_cash = snapshot.get("tactical_cash_value", 0.0)
        pas_val = snapshot.get("passive_total_value", 0.0)
        alpha_rs = snapshot.get("alpha_rupees", 0.0)
        alpha_sign = "+" if alpha_rs >= 0 else ""

        msg.append("━━━━━━━━━━━━━━━━━━━━━")
        msg.append("📊 <b>PORTFOLIO PERFORMANCE</b>:")
        msg.append(f"• <b>Tactical Ledger A:</b> ₹{tac_val:,.2f}")
        msg.append(f"  └ Equity: ₹{tac_val - tac_cash:,.2f} | Cash: ₹{tac_cash:,.2f}")
        msg.append(f"• <b>Passive Ledger B:</b>  ₹{pas_val:,.2f}")
        msg.append(f"• <b>Tactical Alpha:</b>    <b>{alpha_sign}₹{alpha_rs:,.2f}</b> ({snapshot.get('alpha_percent', 0.0):+.2f}%)")

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
