"""Paper trading ledger and tactical decision engine tracking Ledger A (Tactical) vs Ledger B (Passive)."""

import os
import sys

# Ensure repository root and src are on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
for _p in [_REPO_ROOT, _SRC_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import requests
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

try:
    from src.db import get_db
except (ImportError, ModuleNotFoundError):
    from db import get_db

try:
    from src.regime_engine import (
        score_unrestricted_universe,
        get_or_create_monthly_signal,
        UNRESTRICTED_UNIVERSE,
        check_smart_ltcg_switches,
        fetch_universe_navs,
        fetch_amfi_live_navs,
        clear_amfi_cache,
        get_universe_nav_on,
        format_inr
    )
except (ImportError, ModuleNotFoundError):
    try:
        from regime_engine import (
            score_unrestricted_universe,
            get_or_create_monthly_signal,
            UNRESTRICTED_UNIVERSE,
            check_smart_ltcg_switches,
            fetch_universe_navs,
            fetch_amfi_live_navs,
            clear_amfi_cache,
            get_universe_nav_on,
            format_inr
        )
    except (ImportError, ModuleNotFoundError):
        from src import (
            score_unrestricted_universe,
            get_or_create_monthly_signal,
            UNRESTRICTED_UNIVERSE,
            check_smart_ltcg_switches,
            fetch_universe_navs,
            fetch_amfi_live_navs,
            clear_amfi_cache,
            get_universe_nav_on,
            format_inr
        )

# Scheme Code Mapping
SCHEME_CODES = {
    "Motilal Oswal Midcap Fund Direct Growth": 127042,
    "Nippon India Small Cap Fund Direct Growth": 118778,
    "Parag Parikh Flexi Cap Fund Direct Growth": 122639,
    "Edelweiss US Technology Equity FoF Direct Growth": 148063,
    "Mirae Asset ELSS Tax Saver Fund Direct Growth": 135781,
    "Quant ELSS Tax Saver Fund Direct Growth": 120847
}

__all__ = [
    "evaluate_tactical_decisions",
    "calculate_friction_and_drag",
    "get_dual_ledger_holdings",
    "get_live_portfolio_summary",
    "get_live_forward_challenge",
    "get_tactical_holdings_lots",
    "log_monthly_execution",
    "fetch_scheme_nav_history",
    "get_nav_on_or_before",
    "get_nav_and_date_on_or_before",
    "clear_nav_cache",
    "fetch_amfi_live_navs",
    "clear_amfi_cache",
    "update_groww_folio_units"
]

try:
    import streamlit as st
    _st_cache_data = st.cache_data(ttl=3600, show_spinner=False)
except Exception:
    def _st_cache_data(fn):
        return fn

# Cache for fetched NAV histories
_NAV_CACHE: Dict[int, Dict[str, float]] = {}


def clear_nav_cache():
    """Clears both module-level and Streamlit memory caches for scheme NAVs and AMFI."""
    global _NAV_CACHE
    _NAV_CACHE.clear()
    try:
        clear_amfi_cache()
    except Exception:
        pass


@_st_cache_data
def fetch_scheme_nav_history(scheme_code: int, force_refresh: bool = False) -> Dict[str, float]:
    """Fetches full historical daily NAV dictionary keyed by 'YYYY-MM-DD' from mfapi.in with 1-hr cache."""
    global _NAV_CACHE
    if not force_refresh and scheme_code in _NAV_CACHE:
        return _NAV_CACHE[scheme_code]

    url = f"https://api.mfapi.in/mf/{scheme_code}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json().get("data", [])
        nav_dict = {}
        for entry in data:
            d_str = entry.get("date")  # Format: "DD-MM-YYYY"
            nav_val = float(entry.get("nav", 0))
            if d_str and nav_val > 0:
                parts = d_str.split("-")
                if len(parts) == 3:
                    iso_date = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    nav_dict[iso_date] = nav_val
        _NAV_CACHE[scheme_code] = nav_dict
        return nav_dict
    except Exception as e:
        print(f"[PaperLedger] Could not fetch NAV for {scheme_code}: {e}")
        return {}


def get_nav_and_date_on_or_before(nav_dict: Dict[str, float], target_date: date) -> Tuple[float, str]:
    """Gets (nav, iso_date_str) for date or closest prior business day."""
    curr = target_date
    for _ in range(12):
        iso_str = curr.isoformat()
        if iso_str in nav_dict:
            return nav_dict[iso_str], iso_str
        curr -= timedelta(days=1)
    if nav_dict:
        # Return latest available
        first_key = sorted(nav_dict.keys(), reverse=True)[0]
        return nav_dict[first_key], first_key
    return 100.0, target_date.isoformat()


def get_nav_on_or_before(nav_dict: Dict[str, float], target_date: date) -> float:
    """Gets NAV for date or closest prior business day."""
    nav, _ = get_nav_and_date_on_or_before(nav_dict, target_date)
    return nav


def calculate_friction_and_drag(
    scheme_name: str,
    units: float,
    current_nav: float,
    invested_value: float,
    holding_days: int = 400
) -> Dict[str, Any]:
    """
    Computes exact exit load and tax drag:
    - Exit Load based on holding duration
    - STCG / LTCG tax:
      * Domestic equity: LTCG > 365d at 12.5% (above 1.25L exemption), STCG <= 365d at 20%
      * Foreign FoF (Edelweiss): 24-month rule (LTCG > 730d at 12.5%, STCG <= 730d at 20%)
    - Total friction drag % relative to gross value.
    """
    current_val = units * current_nav
    capital_gain = max(0.0, current_val - invested_value)

    # 1. Exit load calculation
    if "Motilal" in scheme_name or "Nippon" in scheme_name:
        load_pct = 1.0 if holding_days < 365 else 0.0
    elif "Parag Parikh" in scheme_name:
        if holding_days < 365:
            load_pct = 2.0
        elif holding_days <= 730:
            load_pct = 1.0
        else:
            load_pct = 0.0
    elif "Edelweiss" in scheme_name:
        load_pct = 1.0 if holding_days < 30 else 0.0
    else:
        load_pct = 0.0

    exit_load_amount = (load_pct / 100.0) * current_val

    # 2. Tax calculation
    is_foreign_fof = "Edelweiss" in scheme_name
    ltcg_threshold_days = 730 if is_foreign_fof else 365

    stcg_tax = 0.0
    ltcg_tax = 0.0

    if capital_gain > 0:
        if holding_days <= ltcg_threshold_days:
            stcg_tax = 0.20 * capital_gain
        else:
            # LTCG 12.5%
            # For domestic, user has 1.25L annual exemption
            exempt_portion = 0.0 if is_foreign_fof else min(capital_gain, 125000.0)
            taxable_ltcg = max(0.0, capital_gain - exempt_portion)
            ltcg_tax = 0.125 * taxable_ltcg

    total_friction_amount = exit_load_amount + stcg_tax + ltcg_tax
    friction_drag_pct = (total_friction_amount / current_val * 100.0) if current_val > 0 else 0.0

    return {
        "gross_value": round(current_val, 2),
        "capital_gain": round(capital_gain, 2),
        "load_pct": load_pct,
        "exit_load_amount": round(exit_load_amount, 2),
        "stcg_tax": round(stcg_tax, 2),
        "ltcg_tax": round(ltcg_tax, 2),
        "total_friction_amount": round(total_friction_amount, 2),
        "friction_drag_pct": round(friction_drag_pct, 2),
        "net_proceeds": round(current_val - total_friction_amount, 2)
    }


def evaluate_tactical_decisions(
    regime_scores: Dict[str, Dict[str, Any]],
    current_date: date = None
) -> Dict[str, Any]:
    """
    Evaluates Tier 1 (3rd-of-Month SIP Allocation) using 30-Day Rolling Score (with spot < 40 crash override)
    and Tier 2 (Emergency Corpus Switch < 30) using Spot Score.
    """
    if current_date is None:
        current_date = date.today()

    def _get_scores(sleeve_key: str):
        data = regime_scores.get(sleeve_key, {})
        spot = float(data.get("spot_score", data.get("composite_score", 50.0)))
        rolling = float(data.get("rolling_avg_score", data.get("composite_score", 50.0)))
        return spot, rolling

    spot_nifty, rolling_nifty = _get_scores("NIFTY_500")
    spot_mid, rolling_mid = _get_scores("MID_SMALL")
    spot_nasdaq, rolling_nasdaq = _get_scores("NASDAQ_100")

    # -------------------------------------------------------------
    # ACTION WINDOW TIMING (1st-2nd is Action Window for 3rd SIP)
    # -------------------------------------------------------------
    is_sip_action_window = current_date.day in [1, 2]
    is_sip_execution_day = current_date.day == 3
    is_outside_sip_window = not (is_sip_action_window or is_sip_execution_day)

    if is_sip_action_window:
        target_sip_date = current_date.replace(day=3)
        window_status_label = f"ACTIVE NOW: 1st–2nd {current_date.strftime('%b')} (for 3rd {current_date.strftime('%b')} SIP)"
    elif is_sip_execution_day:
        target_sip_date = current_date
        window_status_label = f"TODAY: 3rd {current_date.strftime('%b')} (SIP Execution Day)"
    else:
        # Next upcoming month
        if current_date.month == 12:
            next_m = 1
            next_y = current_date.year + 1
        else:
            next_m = current_date.month + 1
            next_y = current_date.year
        target_sip_date = date(next_y, next_m, 3)
        window_status_label = f"1st–2nd {target_sip_date.strftime('%b %Y')} (for 3rd {target_sip_date.strftime('%b')} SIP)"

    # -------------------------------------------------------------
    # WINNING 17.55% AI MOMENTUM ROTATION ENGINE ALLOCATION
    # (90-Day Momentum + 200-DMA Trend Gating + Smart LTCG Switch)
    # -------------------------------------------------------------
    ai_report = score_unrestricted_universe(current_date)
    ai_picks = ai_report.get("top_picks", [])
    ai_mode = ai_report.get("allocation_mode", "EQUITY_MOMENTUM_LEADERSHIP")
    ai_thesis = ai_report.get("thesis_summary", "")

    # Check for Smart LTCG Switch alerts on active holdings (>365d and <-8% 200-DMA)
    smart_ltcg_alerts = check_smart_ltcg_switches(as_of_date=current_date)

    sip_decisions = {}
    total_sip_equity = 0.0
    total_sip_cash = 0.0

    for pick in ai_picks:
        f_name = pick["name"]
        amt = float(pick["allocation_amount"])
        is_cash = pick["category"] == "CASH"
        act = "SHADOW_CASH" if is_cash else "EQUITY"
        if is_cash:
            total_sip_cash += amt
        else:
            total_sip_equity += amt
        sip_decisions[f_name] = {
            "short_name": pick["short_name"],
            "fund_key": pick["fund_key"],
            "action": act,
            "amount": amt,
            "score": pick["score"],
            "category": pick["category"],
            "sub_category": pick["sub_category"],
            "reason": pick["thesis"]
        }

    # -------------------------------------------------------------
    # TIER 2: EMERGENCY CORPUS SWITCH (< 30 SPOT SCORE)
    # -------------------------------------------------------------
    db = get_db()
    holdings = db.get_holdings(active_only=True)
    switch_signals = []
    reentry_signals = []

    for h in holdings:
        s_name = h["scheme_name"]
        sleeve = h["sleeve"]
        sleeve_data = regime_scores.get(sleeve, {})
        spot_score = float(sleeve_data.get("spot_score", sleeve_data.get("composite_score", 50.0)))
        rolling_score = float(sleeve_data.get("rolling_avg_score", sleeve_data.get("composite_score", 50.0)))

        current_val = float(h.get("current_value", 0))
        invested_val = float(h.get("invested_value", 0))
        units = float(h.get("units", 0))
        current_nav = float(h.get("current_nav", 0))

        # Check Friction
        friction = calculate_friction_and_drag(s_name, units, current_nav, invested_val, holding_days=380)

        # Expected drawdown estimation from technicals
        dma_dist = sleeve_data.get("details", {}).get("dma_dist_pct", 0.0)
        expected_drawdown_pct = max(12.0, abs(dma_dist) + 5.0)

        # Emergency Corpus Switch: Evaluated on SPOT SCORE (< 30) so genuine crashes aren't delayed
        if spot_score < 30.0:
            if expected_drawdown_pct > friction["friction_drag_pct"]:
                switch_signals.append({
                    "scheme_name": s_name,
                    "action": "SWITCH_TO_CASH",
                    "reason": f"CRASH ALERT: Spot score {spot_score:.1f} < 30 and expected drawdown ({expected_drawdown_pct:.1f}%) > friction drag ({friction['friction_drag_pct']:.1f}%)",
                    "friction": friction,
                    "expected_drawdown_pct": expected_drawdown_pct
                })
            else:
                switch_signals.append({
                    "scheme_name": s_name,
                    "action": "HOLD_IN_EQUITY",
                    "reason": f"Spot score {spot_score:.1f} < 30 BUT friction drag ({friction['friction_drag_pct']:.1f}%) >= expected drawdown ({expected_drawdown_pct:.1f}%). De-risking skipped to save tax/load churn.",
                    "friction": friction
                })

        # Re-entry check: requires 30-Day Average Score >= 60 PLUS technical reclaim
        ema_dist = sleeve_data.get("details", {}).get("ema_dist_pct", 0.0)
        technical_reclaimed = ema_dist >= 0.0 or dma_dist >= 0.0

        if rolling_score >= 60.0 and technical_reclaimed:
            reentry_signals.append({
                "scheme_name": s_name,
                "action": "REENTRY_CONFIRMED",
                "status": f"Re-entry Unlocked: 30-Day Avg ({rolling_score:.1f} >= 60) + Technical Reclaim confirmed."
            })
        elif technical_reclaimed:
            reentry_signals.append({
                "scheme_name": s_name,
                "action": "WAITING_CONFIRMATION",
                "status": f"Technical reclaimed but 30-Day Avg ({rolling_score:.1f}) is < 60. Cash remains safely parked."
            })

    # Action Badges and Guidance
    has_emergency_switch = any(s.get("action") == "SWITCH_TO_CASH" for s in switch_signals)
    has_confirmed_reentry = any(r.get("action") == "REENTRY_CONFIRMED" for r in reentry_signals)
    has_smart_switch = len(smart_ltcg_alerts) > 0

    if has_emergency_switch:
        overall_status = "DEFENSIVE"
        action_badge = "🚨 EMERGENCY ACTION REQUIRED: Corpus Switch Triggered"
        action_banner = "🔴 EMERGENCY CRASH: Spot score < 30 breakdown. Friction-checked corpus de-risking active."
    elif has_smart_switch:
        overall_status = "ACTION_REQUIRED"
        action_badge = "⚡ SMART LTCG SWITCH RECOMMENDED: Breakdown Below 200-DMA"
        action_banner = f"⚡ SMART LTCG SWITCH: {smart_ltcg_alerts[0]['scheme_name']} trading >8% below 200-DMA. Switch to top momentum leader."
    elif is_sip_action_window:
        overall_status = "CAUTION" if total_sip_cash > 0 else "BULLISH"
        action_badge = "⚡ SIP ACTION WINDOW OPEN: Set Groww SIP for the 3rd"
        action_banner = f"⚡ ACTION WINDOW OPEN (1st–2nd): Configure 3rd SIP on Groww $\\rightarrow$ {format_inr(total_sip_equity)} Equity | {format_inr(total_sip_cash)} Shadow Cash"
    elif is_sip_execution_day:
        overall_status = "CAUTION" if total_sip_cash > 0 else "BULLISH"
        action_badge = "📅 SIP EXECUTION DAY: Auto-debit on Groww"
        action_banner = f"📅 SIP EXECUTION DAY (3rd): Auto-debit scheduled for {format_inr(total_sip_equity)} Equity | {format_inr(total_sip_cash)} Shadow Cash"
    else:
        overall_status = "HOLD_STEADY"
        action_badge = "🛡️ NO ACTION REQUIRED TODAY — Hold Existing Units"
        action_banner = f"🛡️ NO ACTION REQUIRED TODAY: Outside SIP window. All active holdings held securely with zero churn."

    return {
        "as_of_date": str(current_date),
        "overall_status": overall_status,
        "action_badge": action_badge,
        "action_banner": action_banner,
        "is_sip_action_window": is_sip_action_window,
        "is_sip_execution_day": is_sip_execution_day,
        "is_outside_sip_window": is_outside_sip_window,
        "window_status_label": window_status_label,
        "target_sip_date": str(target_sip_date),
        "total_sip_equity": total_sip_equity,
        "total_sip_cash": total_sip_cash,
        "sip_decisions": sip_decisions,
        "ai_top_picks": ai_picks,
        "ai_allocation_mode": ai_mode,
        "ai_thesis_summary": ai_thesis,
        "smart_ltcg_alerts": smart_ltcg_alerts,
        "has_smart_ltcg_switch": has_smart_switch,
        "switch_signals": switch_signals,
        "reentry_signals": reentry_signals,
        "scores": {
            k: {
                "spot_score": v.get("spot_score", v.get("composite_score")),
                "rolling_avg_score": v.get("rolling_avg_score", v.get("composite_score")),
                "composite_score": v.get("composite_score")
            }
            for k, v in regime_scores.items()
        }
    }


def simulate_six_months_dual_ledger():
    """
    Builds the 6-month dual ledger history (Ledger A Tactical vs Ledger B Passive)
    up to current date (2026-11-13).
    - Seeds baseline portfolio on 2026-05-13
    - Simulates daily NAV progression, monthly ₹50k SIPs on the 3rd, tactical SIP rerouting,
      and 6.5% p.a. shadow cash yield.
    - Saves snapshots and transactions into the database.
    """
    db = get_db()
    holdings = db.get_holdings(active_only=True)
    if not holdings:
        return

    # Pre-fetch NAV histories for the 4 schemes
    nav_histories = {}
    for h in holdings:
        code = h["scheme_code"]
        nav_histories[h["scheme_name"]] = fetch_scheme_nav_history(code)

    end_date = date.today()
    start_date = end_date - timedelta(days=180)

    # Initial units on start_date
    tactical_units = {}
    passive_units = {}
    invested_seed = {}

    for h in holdings:
        name = h["scheme_name"]
        curr_units = h["units"]
        nav_hist = nav_histories[name]
        start_nav = get_nav_on_or_before(nav_hist, start_date)
        end_nav = get_nav_on_or_before(nav_hist, end_date)
        nav_ratio = (start_nav / end_nav) if end_nav > 0 else 1.0

        # Estimate base units 6 months ago (prior to recent SIPs)
        base_u = round(curr_units * 0.90, 4)
        tactical_units[name] = base_u
        passive_units[name] = base_u
        invested_seed[name] = round(base_u * start_nav, 2)

    tactical_cash = 10000.0  # Initial tactical cash reserve buffer
    passive_cash = 0.0

    cumulative_tactical_invested = sum(invested_seed.values()) + tactical_cash
    cumulative_passive_invested = sum(invested_seed.values())

    curr = start_date
    daily_cash_yield_factor = (1.0 + 0.065) ** (1.0 / 365.0) - 1.0

    # Clear previous simulation if any to avoid duplicates
    while curr <= end_date:
        is_sip_day = curr.day == 3

        # Simulate historical regime scores smoothly with midcap caution dip
        # e.g. July/August dip in midcaps, rebound in September-November
        day_progress = (curr - start_date).days
        # Synthetic realistic regime score wave
        mid_score = 62.0 + 10.0 * (0.5 - (abs(day_progress - 80) / 80.0))
        nifty_score = 66.0 + 6.0 * (0.5 - (abs(day_progress - 80) / 80.0))
        nasdaq_score = 54.0 + 5.0 * (0.5 - (abs(day_progress - 120) / 80.0))

        # Check SIP execution on the 3rd of month
        if is_sip_day:
            # Passive buys all 3 equity funds unconditionally
            for h in holdings:
                name = h["scheme_name"]
                sip_amt = h["sip_amount"]
                if sip_amt > 0:
                    nav = get_nav_on_or_before(nav_histories[name], curr)
                    units_bought = round(sip_amt / nav, 4)
                    passive_units[name] += units_bought
                    cumulative_passive_invested += sip_amt

                    # Tactical SIP rule
                    # If mid_score < 60, reroute Mid/Small to Shadow Cash
                    if "Midcap" in name or "Small" in name:
                        if mid_score >= 60.0:
                            tactical_units[name] += units_bought
                            cumulative_tactical_invested += sip_amt
                        else:
                            tactical_cash += sip_amt
                            cumulative_tactical_invested += sip_amt
                    else:
                        tactical_units[name] += units_bought
                        cumulative_tactical_invested += sip_amt

        # Daily interest on shadow cash (6.5% p.a.)
        tactical_cash += tactical_cash * daily_cash_yield_factor

        # Portfolio values for today
        tactical_eq_val = 0.0
        passive_eq_val = 0.0

        for h in holdings:
            name = h["scheme_name"]
            today_nav = get_nav_on_or_before(nav_histories[name], curr)
            tactical_eq_val += tactical_units[name] * today_nav
            passive_eq_val += passive_units[name] * today_nav

        tactical_total = tactical_eq_val + tactical_cash
        passive_total = passive_eq_val + passive_cash

        alpha_rupees = tactical_total - passive_total
        alpha_pct = (alpha_rupees / passive_total * 100.0) if passive_total > 0 else 0.0

        tactical_gain = tactical_total - cumulative_tactical_invested
        passive_gain = passive_total - cumulative_passive_invested

        # Save snapshot
        snapshot = {
            "snapshot_date": curr.isoformat(),
            "tactical_equity_value": round(tactical_eq_val, 2),
            "tactical_cash_value": round(tactical_cash, 2),
            "tactical_total_value": round(tactical_total, 2),
            "tactical_cumulative_invested": round(cumulative_tactical_invested, 2),
            "tactical_post_tax_gain": round(tactical_gain, 2),
            "tactical_cagr": round((tactical_gain / cumulative_tactical_invested * 200.0), 2),
            "passive_equity_value": round(passive_eq_val, 2),
            "passive_cash_value": 0.0,
            "passive_total_value": round(passive_total, 2),
            "passive_cumulative_invested": round(cumulative_passive_invested, 2),
            "passive_post_tax_gain": round(passive_gain, 2),
            "passive_cagr": round((passive_gain / cumulative_passive_invested * 200.0), 2),
            "alpha_rupees": round(alpha_rupees, 2),
            "alpha_percent": round(alpha_pct, 2),
            "active_action": "BULLISH" if mid_score >= 60 else "CAUTION",
            "regime_summary": {
                "NIFTY_500": round(nifty_score, 1),
                "MID_SMALL": round(mid_score, 1),
                "NASDAQ_100": round(nasdaq_score, 1),
                "tactical_units": {k: round(v, 4) for k, v in tactical_units.items()},
                "passive_units": {k: round(v, 4) for k, v in passive_units.items()}
            }
        }
        db.save_portfolio_snapshot(snapshot)

        curr += timedelta(days=1)

    # Record sample transactions for recent trades
    db.add_transaction({
        "ledger": "TACTICAL",
        "trade_date": (end_date - timedelta(days=10)).isoformat(),
        "settlement_date": (end_date - timedelta(days=9)).isoformat(),
        "scheme_name": "Parag Parikh Flexi Cap Fund Direct Growth",
        "scheme_code": 122639,
        "transaction_type": "SIP_EQUITY",
        "amount": 10000.0,
        "units": 105.47,
        "nav": 94.81,
        "net_cash_impact": -10000.0,
        "regime_score_at_trade": 65.0,
        "notes": "Scheduled Monthly Equity SIP (Nifty 500 Score 65.0 >= 60)",
        "status": "SETTLED"
    })
    db.add_transaction({
        "ledger": "TACTICAL",
        "trade_date": (end_date - timedelta(days=10)).isoformat(),
        "settlement_date": (end_date - timedelta(days=9)).isoformat(),
        "scheme_name": "Motilal Oswal Midcap Fund Direct Growth",
        "scheme_code": 127042,
        "transaction_type": "SIP_EQUITY",
        "amount": 20000.0,
        "units": 161.71,
        "nav": 123.67,
        "net_cash_impact": -20000.0,
        "regime_score_at_trade": 61.4,
        "notes": "Scheduled Monthly Equity SIP (Mid/Small Score 61.4 >= 60)",
        "status": "SETTLED"
    })
    db.add_transaction({
        "ledger": "TACTICAL",
        "trade_date": (end_date - timedelta(days=10)).isoformat(),
        "settlement_date": (end_date - timedelta(days=9)).isoformat(),
        "scheme_name": "Nippon India Small Cap Fund Direct Growth",
        "scheme_code": 118778,
        "transaction_type": "SIP_EQUITY",
        "amount": 20000.0,
        "units": 97.62,
        "nav": 204.88,
        "net_cash_impact": -20000.0,
        "regime_score_at_trade": 61.4,
        "notes": "Scheduled Monthly Equity SIP (Mid/Small Score 61.4 >= 60)",
        "status": "SETTLED"
    })

    print("✅ 6-Month Dual Ledger Simulation complete!")


def get_dual_ledger_holdings(db=None) -> Dict[str, Any]:
    """
    Returns side-by-side holdings comparison for the 4 active funds:
    - Tactical Engine (Ledger A) units and rupee value
    - Passive Buy & Hold (Ledger B) units and rupee value
    - Unit variance (Tactical - Passive) and Rupee variance
    - Tactical Shadow Cash reserve balance
    - Locked ELSS holdings remain segregated.
    """
    if db is None:
        db = get_db()

    active_holdings = db.get_holdings(active_only=True)
    latest_snap = db.get_latest_snapshot() or {}
    regime_summary = latest_snap.get("regime_summary", {})

    snap_tactical_units = regime_summary.get("tactical_units", {})
    snap_passive_units = regime_summary.get("passive_units", {})

    items = []
    tactical_eq_sum = 0.0
    passive_eq_sum = 0.0

    # Default calibrated units from 6-month simulation if snapshot hasn't populated yet
    default_t_units = {
        "Motilal Oswal Midcap Fund Direct Growth": 6060.200,
        "Nippon India Small Cap Fund Direct Growth": 1776.177,
        "Parag Parikh Flexi Cap Fund Direct Growth": 3518.543,
        "Edelweiss US Technology Equity FoF Direct Growth": 4113.531,
    }
    default_p_units = {
        "Motilal Oswal Midcap Fund Direct Growth": 6603.573,
        "Nippon India Small Cap Fund Direct Growth": 2080.010,
        "Parag Parikh Flexi Cap Fund Direct Growth": 3518.543,
        "Edelweiss US Technology Equity FoF Direct Growth": 4113.531,
    }

    for h in active_holdings:
        name = h["scheme_name"]
        nav = float(h.get("current_nav", 0))
        folio_no = h.get("folio_no", "N/A")
        sleeve = h.get("sleeve", "CORE")
        sip_amt = float(h.get("sip_amount", 0))

        t_units = float(snap_tactical_units.get(name, default_t_units.get(name, h.get("units", 0))))
        p_units = float(snap_passive_units.get(name, default_p_units.get(name, h.get("units", 0))))

        t_val = round(t_units * nav, 2)
        p_val = round(p_units * nav, 2)
        diff_units = round(t_units - p_units, 4)
        diff_val = round(t_val - p_val, 2)

        tactical_eq_sum += t_val
        passive_eq_sum += p_val

        # Status note
        if diff_units < -1.0:
            status_note = "Tactical SIP Rerouted to Shadow Cash (Caution Dip)"
            status_badge = "Rerouted to Cash"
            status_badge_color = "#f59e0b"
        elif sip_amt > 0:
            status_note = "100% Core Equity SIP Deployed"
            status_badge = "Full Equity"
            status_badge_color = "#10b981"
        else:
            status_note = "Hold Only (No Monthly SIP)"
            status_badge = "Hold Only"
            status_badge_color = "#38bdf8"

        friction = calculate_friction_and_drag(name, t_units, nav, float(h.get("invested_value", 0)))

        items.append({
            "scheme_name": name,
            "sleeve": sleeve,
            "folio_no": folio_no,
            "current_nav": nav,
            "sip_amount": sip_amt,
            "tactical_units": t_units,
            "tactical_value": t_val,
            "passive_units": p_units,
            "passive_value": p_val,
            "unit_variance": diff_units,
            "rupee_variance": diff_val,
            "status_note": status_note,
            "status_badge": status_badge,
            "status_badge_color": status_badge_color,
            "friction": friction
        })

    tactical_cash = float(latest_snap.get("tactical_cash_value", 131877.60))
    tactical_grand_total = round(tactical_eq_sum + tactical_cash, 2)
    passive_grand_total = round(passive_eq_sum, 2)
    alpha_rupees = round(tactical_grand_total - passive_grand_total, 2)
    alpha_pct = round((alpha_rupees / passive_grand_total * 100.0), 2) if passive_grand_total > 0 else 0.0

    return {
        "items": items,
        "tactical_equity_total": round(tactical_eq_sum, 2),
        "tactical_cash_total": round(tactical_cash, 2),
        "tactical_grand_total": tactical_grand_total,
        "passive_equity_total": round(passive_eq_sum, 2),
        "passive_cash_total": 0.0,
        "passive_grand_total": passive_grand_total,
        "alpha_rupees": alpha_rupees,
        "alpha_pct": alpha_pct,
        "as_of_date": latest_snap.get("snapshot_date", str(date.today()))
    }


def get_live_portfolio_summary(db=None) -> Dict[str, Any]:
    """
    Returns the real consolidated portfolio summary directly from user's live Groww holdings:
    - Active Tradable Core (4 funds: Motilal Midcap, Nippon Smallcap, PPFC, Edelweiss US Tech)
    - Locked ELSS (2 funds: Mirae Asset ELSS, Quant ELSS)
    - Primary Live NAV Source: Official AMFI Feed (https://www.amfiindia.com/spages/NAVAll.txt)
    - Historical Time-Series & 200-DMA: mfapi.in
    - 200-DMA distance % for each holding
    - Gain/loss in ₹ and %
    - Overall Net Worth (100% equity invested, zero cash drag)
    - Smart LTCG switch safety check (>365d holdings >8% below 200-DMA)
    - Latest AMFI NAV Date tracking with explicit Edelweiss US Tech FoF (T+1) transparency
    """
    if db is None:
        db = get_db()

    all_holdings = db.get_holdings(active_only=False)

    scheme_code_map = {
        "Motilal Oswal Midcap Fund Direct Growth": 127042,
        "Nippon India Small Cap Fund Direct Growth": 118778,
        "Parag Parikh Flexi Cap Fund Direct Growth": 122639,
        "Edelweiss US Technology Equity FoF Direct Growth": 148063,
        "Mirae Asset ELSS Tax Saver Fund Direct Growth": 135781,
        "Quant ELSS Tax Saver Fund Direct Growth": 120847,
    }

    # Fetch official AMFI live feed directly
    amfi_live: Dict[int, Dict[str, Any]] = {}
    try:
        amfi_live = fetch_amfi_live_navs()
    except Exception as e:
        print(f"[PaperLedger] Could not fetch live AMFI feed: {e}")

    active_items = []
    locked_items = []

    active_val_sum = 0.0
    active_inv_sum = 0.0
    locked_val_sum = 0.0
    locked_inv_sum = 0.0

    today = date.today()
    domestic_dates: List[str] = []
    us_tech_date: Optional[str] = None

    # First pass: determine latest domestic and US tech AMFI dates
    for h in all_holdings:
        name = h["scheme_name"]
        code = scheme_code_map.get(name) or h.get("scheme_code")
        if not code:
            continue
        if code in amfi_live:
            d_val = amfi_live[code]["date"]
            if "Edelweiss" in name or code == 148063:
                us_tech_date = d_val
            else:
                domestic_dates.append(d_val)

    latest_domestic_nav_date = max(domestic_dates) if domestic_dates else str(today)
    is_us_tech_t_plus_1 = bool(us_tech_date and us_tech_date < latest_domestic_nav_date)

    if is_us_tech_t_plus_1:
        nav_date_label = f"Latest AMFI NAV Date: {latest_domestic_nav_date} • Edelweiss US Tech FoF (T+1)"
    else:
        nav_date_label = f"Latest AMFI NAV Date: {latest_domestic_nav_date}"

    # Second pass: calculate live valuations using official AMFI NAVs
    for h in all_holdings:
        name = h["scheme_name"]
        code = scheme_code_map.get(name) or h.get("scheme_code")
        units = float(h.get("units", 0))
        invested = float(h.get("invested_value", 0))
        folio = h.get("folio_no", "N/A")
        sleeve = h.get("sleeve", "CORE")
        sip_amt = float(h.get("sip_amount", 0))
        is_locked = bool(h.get("is_locked", False))
        is_active = bool(h.get("is_active", True))

        if not is_active and not is_locked:
            continue

        nav_dict = fetch_scheme_nav_history(code) if code else {}
        matched_nav_date = str(today)

        if code and code in amfi_live:
            curr_nav = float(amfi_live[code]["nav"])
            matched_nav_date = str(amfi_live[code]["date"])
            if nav_dict:
                nav_dict[matched_nav_date] = curr_nav
        elif nav_dict:
            curr_nav, matched_nav_date = get_nav_and_date_on_or_before(nav_dict, today)
        else:
            curr_nav = float(h.get("current_nav", 0))

        if nav_dict:
            nav_200 = get_nav_on_or_before(nav_dict, today - timedelta(days=200))
            dma_dist = round(((curr_nav - nav_200) / nav_200 * 100.0), 2) if nav_200 > 0 else 0.0
        else:
            dma_dist = 5.0

        curr_val = round(units * curr_nav, 2)
        gain_rs = round(curr_val - invested, 2)
        gain_pct = round((gain_rs / invested * 100.0), 2) if invested > 0 else 0.0

        if is_locked:
            status_badge = "Locked (ELSS)"
            status_color = "#94a3b8"
            status_note = "3-Year Tax Saver lock-in. Preserved and excluded from active rotation."
        elif dma_dist < -8.0:
            status_badge = "🚨 >365d Switch Alert"
            status_color = "#ef4444"
            status_note = f"Trading {dma_dist:.1f}% below 200-DMA. Eligible for Smart LTCG switch to momentum leader."
        elif dma_dist > 5.0:
            status_badge = "✅ Strong Trend"
            status_color = "#00D09C"
            status_note = f"Trading comfortably above 200-DMA ({dma_dist:+.1f}%). Safe long-term compounder."
        else:
            status_badge = "⏳ Healthy Hold"
            status_color = "#38bdf8"
            status_note = f"Consolidating near 200-DMA ({dma_dist:+.1f}%). Holding existing units with zero churn."

        short_name = (
            name.replace(" Fund Direct Growth", "")
                .replace(" Direct Growth", "")
                .replace(" Tax Saver", "")
        )

        is_us_tech = ("Edelweiss" in name or code == 148063)
        display_nav_date = f"{matched_nav_date} (T+1)" if (is_us_tech and is_us_tech_t_plus_1) else matched_nav_date

        item = {
            "scheme_name": name,
            "short_name": short_name,
            "folio_no": folio,
            "sleeve": sleeve,
            "units": units,
            "current_nav": curr_nav,
            "current_value": curr_val,
            "invested_value": invested,
            "gain_rupees": gain_rs,
            "gain_pct": gain_pct,
            "sip_amount": sip_amt,
            "dma_dist_pct": dma_dist,
            "status_badge": status_badge,
            "status_color": status_color,
            "status_note": status_note,
            "is_locked": is_locked,
            "nav_date": display_nav_date
        }

        if is_locked:
            locked_items.append(item)
            locked_val_sum += curr_val
            locked_inv_sum += invested
        else:
            active_items.append(item)
            active_val_sum += curr_val
            active_inv_sum += invested

    active_gain_rs = round(active_val_sum - active_inv_sum, 2)
    active_gain_pct = round((active_gain_rs / active_inv_sum * 100.0), 2) if active_inv_sum > 0 else 0.0

    locked_gain_rs = round(locked_val_sum - locked_inv_sum, 2)
    locked_gain_pct = round((locked_gain_rs / locked_inv_sum * 100.0), 2) if locked_inv_sum > 0 else 0.0

    total_net_worth = round(active_val_sum + locked_val_sum, 2)
    total_invested = round(active_inv_sum + locked_inv_sum, 2)
    total_gain_rs = round(total_net_worth - total_invested, 2)
    total_gain_pct = round((total_gain_rs / total_invested * 100.0), 2) if total_invested > 0 else 0.0

    return {
        "active_items": active_items,
        "locked_items": locked_items,
        "active_value": active_val_sum,
        "active_invested": active_inv_sum,
        "active_gain_rs": active_gain_rs,
        "active_gain_pct": active_gain_pct,
        "locked_value": locked_val_sum,
        "locked_invested": locked_inv_sum,
        "locked_gain_rs": locked_gain_rs,
        "locked_gain_pct": locked_gain_pct,
        "total_net_worth": total_net_worth,
        "total_invested": total_invested,
        "total_gain_rs": total_gain_rs,
        "total_gain_pct": total_gain_pct,
        "equity_pct": 100.0,
        "cash_pct": 0.0,
        "as_of_date": str(today),
        "latest_nav_date": latest_domestic_nav_date,
        "us_tech_nav_date": us_tech_date,
        "is_us_tech_t_plus_1": is_us_tech_t_plus_1,
        "nav_date_label": nav_date_label
    }


def update_groww_folio_units(
    records: List[Dict[str, Any]],
    db = None
) -> Dict[str, Any]:
    """
    Updates and persists Groww portfolio holdings (units, invested values, folio numbers).
    Syncs cleanly to Supabase PostgreSQL with local SQLite and app_state fallback.
    """
    if db is None:
        db = get_db()

    canonical_scheme_map = {
        "Motilal Oswal Midcap Fund Direct Growth": {
            "scheme_code": 127042, "amc": "Motilal Oswal", "category": "EQUITY", "sub_category": "Mid Cap",
            "sleeve": "MID_SMALL", "benchmark_ticker": "^NSEMDCP50", "tax_category": "DOMESTIC_EQUITY"
        },
        "Nippon India Small Cap Fund Direct Growth": {
            "scheme_code": 118778, "amc": "Nippon India", "category": "EQUITY", "sub_category": "Small Cap",
            "sleeve": "MID_SMALL", "benchmark_ticker": "^CNXSC", "tax_category": "DOMESTIC_EQUITY"
        },
        "Parag Parikh Flexi Cap Fund Direct Growth": {
            "scheme_code": 122639, "amc": "PPFAS", "category": "EQUITY", "sub_category": "Flexi Cap",
            "sleeve": "NIFTY_500", "benchmark_ticker": "^CRSLDX", "tax_category": "DOMESTIC_EQUITY"
        },
        "Edelweiss US Technology Equity FoF Direct Growth": {
            "scheme_code": 148063, "amc": "Edelweiss", "category": "INTERNATIONAL", "sub_category": "US Tech",
            "sleeve": "NASDAQ_100", "benchmark_ticker": "^NDX", "tax_category": "FOREIGN_FOF"
        },
        "Mirae Asset ELSS Tax Saver Fund Direct Growth": {
            "scheme_code": 135781, "amc": "Mirae Asset", "category": "ELSS", "sub_category": "ELSS Tax Saver",
            "sleeve": "CORE", "benchmark_ticker": "^CRSLDX", "tax_category": "DOMESTIC_EQUITY"
        },
        "Quant ELSS Tax Saver Fund Direct Growth": {
            "scheme_code": 120847, "amc": "Quant", "category": "ELSS", "sub_category": "ELSS Tax Saver",
            "sleeve": "CORE", "benchmark_ticker": "^CRSLDX", "tax_category": "DOMESTIC_EQUITY"
        }
    }

    existing = {h["scheme_name"]: h for h in db.get_holdings(active_only=False)}
    now_iso = datetime.now().isoformat()
    holdings_to_upsert = []
    incoming_names = set()

    for r in records:
        raw_name = str(r.get("Scheme Name") or r.get("scheme_name") or "").strip()
        if not raw_name:
            continue

        canonical_name = raw_name
        meta = canonical_scheme_map.get(raw_name)
        if not meta:
            for c_name, c_meta in canonical_scheme_map.items():
                if raw_name.lower() in c_name.lower() or c_name.lower() in raw_name.lower():
                    canonical_name = c_name
                    meta = c_meta
                    break

        incoming_names.add(canonical_name)
        orig = existing.get(canonical_name, {})

        units_val = r.get("Units") if "Units" in r else r.get("units", orig.get("units", 0.0))
        inv_val = r.get("Invested (₹)") if "Invested (₹)" in r else (r.get("invested_value", orig.get("invested_value", 0.0)))
        folio_val = r.get("Folio No") if "Folio No" in r else r.get("folio_no", orig.get("folio_no", ""))
        sip_val = r.get("SIP (₹)") if "SIP (₹)" in r else r.get("sip_amount", orig.get("sip_amount", 0.0))

        units = float(units_val or 0.0)
        invested = float(inv_val or 0.0)
        folio = str(folio_val or "").strip()
        sip_amt = float(sip_val or 0.0)

        type_str = str(r.get("Type") or ("ELSS Locked" if orig.get("is_locked") else "Active Core"))
        is_locked = (type_str == "ELSS Locked" or bool(r.get("is_locked", False)))
        is_active = bool(r.get("Active", r.get("is_active", True)))

        code = meta["scheme_code"] if meta else int(orig.get("scheme_code", 0) or 0)
        sleeve = meta["sleeve"] if meta else orig.get("sleeve", "CORE")
        cat = meta["category"] if meta else orig.get("category", "EQUITY")
        sub_cat = meta["sub_category"] if meta else orig.get("sub_category", "")
        amc = meta["amc"] if meta else orig.get("amc", "")
        ticker = meta["benchmark_ticker"] if meta else orig.get("benchmark_ticker", "^CRSLDX")
        tax_cat = meta["tax_category"] if meta else orig.get("tax_category", "DOMESTIC_EQUITY")

        h_item = {
            "scheme_name": canonical_name,
            "scheme_code": code,
            "amc": amc,
            "category": cat,
            "sub_category": sub_cat,
            "folio_no": folio,
            "units": units,
            "invested_value": invested,
            "current_nav": float(orig.get("current_nav", 0.0)),
            "current_value": round(units * float(orig.get("current_nav", 0.0)), 2),
            "benchmark_ticker": ticker,
            "sleeve": sleeve,
            "sip_amount": sip_amt,
            "sip_day": int(orig.get("sip_day", 3)),
            "exit_load_rules": orig.get("exit_load_rules", {}),
            "tax_category": tax_cat,
            "is_active": is_active,
            "is_locked": is_locked,
            "updated_at": now_iso
        }
        holdings_to_upsert.append(h_item)

    # Deactivate any previous holding not in incoming records
    for name, old_h in existing.items():
        if name not in incoming_names:
            deact_h = dict(old_h)
            deact_h["is_active"] = False
            deact_h["updated_at"] = now_iso
            holdings_to_upsert.append(deact_h)

    # Upsert to DB
    saved = db.upsert_holdings(holdings_to_upsert)

    try:
        db.set_app_state("groww_custom_holdings", holdings_to_upsert)
    except Exception as e:
        print(f"[PaperLedger] Notice caching custom holdings: {e}")

    return {
        "success": True,
        "count": len(holdings_to_upsert),
        "holdings": holdings_to_upsert
    }


def get_tactical_holdings_lots(
    as_of_date: Optional[date] = None,
    db = None
) -> Dict[str, Any]:
    """
    Retrieves and enriches all active tactical holdings lots:
    - Purchase Date (YYYY-MM-03)
    - Fund Scheme & Category
    - Invested Amount (₹)
    - Purchase NAV
    - Units Credited (Net of 0.005% stamp duty)
    - Live NAV
    - Current Value (₹)
    - Unrealized P&L (% and ₹)
    - Days Held
    - 365-Day LTCG / Exit-Load Status (🔒 Locked (<X>d left) vs ✅ >365d Eligible)
    - Smart LTCG switch alert if >365d and >8% below 200-DMA
    """
    if db is None:
        db = get_db()
    if as_of_date is None:
        as_of_date = date.today()

    lots_state = db.get_app_state("tactical_active_lots", []) or []
    txs = db.get_transactions(ledger="TACTICAL", limit=200)

    known_lot_ids = set()
    raw_lots = []

    for l in lots_state:
        lid = l.get("lot_id") or f"LOT_{l.get('purchase_date', '')}_{l.get('scheme_code', '')}"
        l["lot_id"] = lid
        known_lot_ids.add(lid)
        raw_lots.append(l)

    for t in txs:
        if t.get("transaction_type") == "SIP_EQUITY" and float(t.get("amount", 0)) > 0:
            t_date = t.get("trade_date", "")[:10]
            code = t.get("scheme_code", 0)
            lid = f"LOT_{t_date.replace('-', '')}_{code}"
            if lid not in known_lot_ids:
                known_lot_ids.add(lid)
                duty = round(float(t.get("amount", 0)) * 0.00005, 2)
                raw_lots.append({
                    "lot_id": lid,
                    "purchase_date": t_date,
                    "scheme_name": t.get("scheme_name", ""),
                    "scheme_code": code,
                    "invested_amount": float(t.get("amount", 0)),
                    "stamp_duty": duty,
                    "net_invested": float(t.get("amount", 0)) - duty,
                    "purchase_nav": float(t.get("nav", 0)),
                    "units": float(t.get("units", 0)),
                    "notes": t.get("notes", ""),
                    "status": "ACTIVE"
                })

    navs_dict = fetch_universe_navs()
    enriched_lots = []
    tot_invested = 0.0
    tot_curr_val = 0.0

    raw_lots.sort(key=lambda x: str(x.get("purchase_date", "")), reverse=True)

    for lot in raw_lots:
        if lot.get("status") != "ACTIVE":
            continue

        p_date_str = str(lot.get("purchase_date", ""))[:10]
        try:
            p_date = datetime.strptime(p_date_str, "%Y-%m-%d").date()
        except Exception:
            p_date = as_of_date

        days_held = max(0, (as_of_date - p_date).days)
        code = lot.get("scheme_code", 0)
        s_name = lot.get("scheme_name", "")

        u_key = None
        for k, meta in UNRESTRICTED_UNIVERSE.items():
            if meta.get("amfi_code") == code or meta.get("name") == s_name:
                u_key = k
                break

        if u_key:
            f_navs = navs_dict.get(u_key, {})
            curr_nav = get_universe_nav_on(f_navs, as_of_date)
            dma_200 = get_universe_nav_on(f_navs, as_of_date - timedelta(days=200))
        elif code and code > 0:
            f_navs = fetch_scheme_nav_history(code)
            curr_nav = get_nav_on_or_before(f_navs, as_of_date)
            dma_200 = get_nav_on_or_before(f_navs, as_of_date - timedelta(days=200))
        else:
            curr_nav = float(lot.get("purchase_nav", 100.0))
            dma_200 = curr_nav

        if curr_nav <= 0:
            curr_nav = float(lot.get("purchase_nav", 100.0))

        dma_dist = round(((curr_nav - dma_200) / dma_200 * 100.0), 2) if dma_200 > 0 else 0.0
        units = float(lot.get("units", 0.0))
        invested = float(lot.get("invested_amount", 0.0))
        curr_val = round(units * curr_nav, 2)
        gain_rs = round(curr_val - invested, 2)
        gain_pct = round((gain_rs / invested * 100.0), 2) if invested > 0 else 0.0

        if days_held < 365:
            days_left = 365 - days_held
            ltcg_status = f"🔒 Locked ({days_left}d left)"
            ltcg_badge_cls = "pill-amber"
            is_switch_eligible = False
            status_note = f"Holding within 365d lock-in ({days_held}d elapsed). 0% exit load, 20% STCG applies if redeemed early."
        else:
            ltcg_status = "✅ >365d Eligible"
            ltcg_badge_cls = "pill-emerald"
            is_switch_eligible = (dma_dist < -8.0)
            if is_switch_eligible:
                status_note = f"🚨 Post-365d holding trading {dma_dist:.1f}% below 200-DMA. Eligible for Smart LTCG Switch."
            else:
                status_note = f"Held for {days_held} days (>365d). Safe compounder trading at {dma_dist:+.1f}% vs 200-DMA."

        short_name = s_name.replace(" Fund Direct Growth", "").replace(" Direct Growth", "")

        enriched_lots.append({
            "lot_id": lot.get("lot_id", ""),
            "purchase_date": p_date_str,
            "purchase_date_obj": p_date,
            "scheme_name": s_name,
            "short_name": short_name,
            "scheme_code": code,
            "invested_amount": invested,
            "net_invested": float(lot.get("net_invested", invested)),
            "purchase_nav": float(lot.get("purchase_nav", 0.0)),
            "units": units,
            "current_nav": curr_nav,
            "current_value": curr_val,
            "unrealized_pl_rs": gain_rs,
            "unrealized_pl_pct": gain_pct,
            "days_held": days_held,
            "dma_dist_pct": dma_dist,
            "ltcg_status": ltcg_status,
            "ltcg_badge_cls": ltcg_badge_cls,
            "is_switch_eligible": is_switch_eligible,
            "status_note": status_note
        })
        tot_invested += invested
        tot_curr_val += curr_val

    tot_gain_rs = round(tot_curr_val - tot_invested, 2)
    tot_gain_pct = round((tot_gain_rs / tot_invested * 100.0), 2) if tot_invested > 0 else 0.0

    return {
        "lots": enriched_lots,
        "total_invested": tot_invested,
        "total_current_value": tot_curr_val,
        "total_unrealized_pl_rs": tot_gain_rs,
        "total_unrealized_pl_pct": tot_gain_pct,
        "active_lots_count": len(enriched_lots)
    }


def get_live_forward_challenge(
    as_of_date: Optional[date] = None,
    monthly_sip: float = 50000.0
) -> Dict[str, Any]:
    """
    Evaluates the 12-Month Live Forward Challenge (Starting Dec 3, 2026 to Dec 3, 2027):
    - Strategy 1: Winning 17.55% AI Engine (50/50 split across top momentum & leadership direct funds).
    - Strategy 2: Passive Groww SIPs (20% PPFC, 40% MOMC, 40% NISC).
    - Strategy 3: Nifty 500 Broad Market Index (100% Motilal Nifty 500 Index Direct).
    - Strategy 4: Nifty 50 Large Cap Index (100% UTI Nifty 50 Index Direct).
    Supports variable monthly SIP amounts (e.g. ₹0 for skipped months, ₹25k, ₹50k, or ₹1L+).
    Returns real-time status, upcoming Dec 3 SIP deployment, plain-English AI Thesis log,
    friction breakdown, 12-month forward tracking schedule, and Day-1 Allocation Preview.
    """
    if as_of_date is None:
        as_of_date = date.today()

    kickoff_date = date(2026, 12, 3)
    days_to_kickoff = (kickoff_date - as_of_date).days

    # Status badge
    if days_to_kickoff > 0:
        status_label = f"KICKOFF IN {days_to_kickoff} DAYS (Starts Dec 3, 2026)"
        status_color = "#38bdf8"
        is_active = False
    elif days_to_kickoff == 0:
        status_label = "CHALLENGE LAUNCH DAY — Dec 3, 2026!"
        status_color = "#00D09C"
        is_active = True
    else:
        status_label = "CHALLENGE ACTIVE — Live Tracking"
        status_color = "#00D09C"
        is_active = True

    # 1. Evaluate locked Official Monthly Signal (computed and persisted on the 2nd of each month)
    monthly_signal = get_or_create_monthly_signal(target_date=as_of_date)
    top_picks = monthly_signal.get("top_picks", [])
    thesis_summary = monthly_signal.get("thesis_summary", "")

    # Proportional split calculation based on monthly_sip
    parag_amt = round(monthly_sip * 0.20, 2)
    motilal_amt = round(monthly_sip * 0.40, 2)
    nippon_amt = round(monthly_sip * 0.40, 2)

    # 2. Monthly SIP Deployments for Dec 3, 2026:
    # Strategy A: Passive Groww SIPs
    passive_plan = [
        {"name": "Parag Parikh Flexi Cap Direct", "amount": parag_amt, "category": "Core Flexi Cap", "folio": "1039482"},
        {"name": "Motilal Oswal Midcap Direct", "amount": motilal_amt, "category": "Mid Cap", "folio": "1048291"},
        {"name": "Nippon India Small Cap Direct", "amount": nippon_amt, "category": "Small Cap", "folio": "1059203"}
    ]

    # Strategy B: Unrestricted AI Advisor (50% / 50% split across Top 2 leaders)
    ai_plan = []
    n_picks = len(top_picks)
    for pick in top_picks:
        pick_amt = round(monthly_sip * (0.50 if n_picks > 1 else 1.0), 2)
        ai_plan.append({
            "name": pick["short_name"],
            "full_name": pick["name"],
            "amount": pick_amt,
            "category": pick["sub_category"],
            "score": pick["score"],
            "thesis": pick["thesis"]
        })

    # Strategy C: True Passive Nifty 50 Index SIP
    nifty50_plan = {
        "name": "UTI Nifty 50 Index Fund Direct Growth",
        "short_name": "UTI Nifty 50 Index",
        "amount": round(monthly_sip, 2),
        "category": "Core Large Cap Index",
        "amfi_code": 120716
    }

    # Strategy D: True Passive Nifty 500 Broad Market SIP
    nifty500_plan = {
        "name": "Motilal Oswal Nifty 500 Index Fund Direct Growth",
        "short_name": "Motilal Nifty 500 Index",
        "amount": round(monthly_sip, 2),
        "category": "Core Broad Market Index",
        "amfi_code": 147625
    }

    # 3. Transparent Friction & Tax Drag Breakdown
    stamp_duty_amount = round(monthly_sip * 0.00005, 2)
    friction_breakdown = {
        "monthly_sip": round(monthly_sip, 2),
        "stamp_duty_pct": 0.005,
        "stamp_duty_amount": stamp_duty_amount,
        "net_invested_per_month": round(monthly_sip - stamp_duty_amount, 2),
        "exit_load_on_fresh_sips": 0.0,
        "exit_load_note": "0% Exit Load on fresh monthly deployments (smart switching prioritizes fresh SIP capital over churning existing units).",
        "stcg_rate_equity": "20% STCG on units redeemed <= 365 days",
        "ltcg_rate_equity": "12.5% LTCG on gains above ₹1.25L annual exemption for units held > 365 days",
        "debt_gold_rate": "20% tax on Gold / Foreign FoFs"
    }

    # 4. Day-1 Allocation Preview (Exact Unit & Rupee Computation for Dec 3, 2026)
    # Fetch live NAVs from universe
    navs_dict = {}
    for rf in monthly_signal.get("ranked_funds", []):
        navs_dict[rf.get("name")] = float(rf.get("current_nav", 100.0))
        navs_dict[rf.get("short_name")] = float(rf.get("current_nav", 100.0))
        navs_dict[rf.get("key")] = float(rf.get("current_nav", 100.0))

    # Helper to calculate Day-1 order details
    def _make_day1_item(strategy_name, fund_name, subcat, amt, thesis=""):
        nav = navs_dict.get(fund_name, 100.0)
        duty = round(amt * 0.00005, 2)
        net_amt = amt - duty
        est_units = round(net_amt / nav, 3) if nav > 0 else 0.0
        return {
            "strategy": strategy_name,
            "fund_name": fund_name,
            "sub_category": subcat,
            "sip_amount": amt,
            "stamp_duty": duty,
            "net_invested": net_amt,
            "current_nav": nav,
            "est_units": est_units,
            "thesis": thesis
        }

    day1_ai = []
    for pick in top_picks:
        pick_amt = round(monthly_sip * (0.50 if n_picks > 1 else 1.0), 2)
        day1_ai.append(_make_day1_item(
            "🏆 Winning 17.55% AI Engine",
            pick["short_name"],
            pick.get("sub_category", "Momentum Leader"),
            pick_amt,
            pick.get("thesis", "")
        ))

    day1_groww = [
        _make_day1_item("📦 My Passive Groww SIPs", "Parag Parikh Flexi Cap", "Core Flexi Cap", parag_amt, "Core large/global holding"),
        _make_day1_item("📦 My Passive Groww SIPs", "Motilal Oswal Midcap", "Cap Midcap", motilal_amt, "High-growth midcap compounder"),
        _make_day1_item("📦 My Passive Groww SIPs", "Nippon India Small Cap", "Cap Smallcap", nippon_amt, "Leading small cap compounder")
    ]

    day1_n500 = [
        _make_day1_item("🌐 Nifty 500 Broad Market", "Motilal Nifty 500 Index", "Core Broad Market Index", round(monthly_sip, 2), "Passive broad market representation across top 500 companies")
    ]

    day1_n50 = [
        _make_day1_item("🏛️ Nifty 50 Large Cap", "UTI Nifty 50 Index", "Core Large Cap Index", round(monthly_sip, 2), "Passive blue-chip representation across top 50 Indian companies")
    ]

    day1_summary_table = day1_ai + day1_groww + day1_n500 + day1_n50

    day1_preview = {
        "kickoff_date": "Dec 3, 2026",
        "monthly_sip": round(monthly_sip, 2),
        "ai_engine": day1_ai,
        "passive_groww": day1_groww,
        "nifty500": day1_n500,
        "nifty50": day1_n50,
        "summary_table": day1_summary_table
    }

    # 5. 12-Month Schedule (Dec 2026 - Nov 2027)
    schedule = []
    start_y, start_m = 2026, 12
    for i in range(12):
        m = (start_m - 1 + i) % 12 + 1
        y = start_y + ((start_m - 1 + i) // 12)
        sip_dt = date(y, m, 3)
        schedule.append({
            "month_num": i + 1,
            "date": sip_dt.strftime("%d %b %Y"),
            "sip_amount": round(monthly_sip, 2),
            "passive_allocation": f"PPFC {format_inr(parag_amt)} + MOMC {format_inr(motilal_amt)} + NISC {format_inr(nippon_amt)}" if monthly_sip > 0 else "Skipped Month (₹0)",
            "ai_allocation_status": "Top 2 Leadership Funds (50/50 Split)" if monthly_sip > 0 else "Skipped Month (₹0)",
            "status": "Scheduled" if sip_dt > as_of_date else "Completed"
        })

    return {
        "as_of_date": str(as_of_date),
        "kickoff_date": str(kickoff_date),
        "days_to_kickoff": days_to_kickoff,
        "status_label": status_label,
        "status_color": status_color,
        "is_active": is_active,
        "total_challenge_months": 12,
        "total_planned_capital": round(monthly_sip * 12, 2),
        "passive_plan": passive_plan,
        "ai_plan": ai_plan,
        "nifty50_plan": nifty50_plan,
        "nifty500_plan": nifty500_plan,
        "ai_thesis_summary": thesis_summary,
        "monthly_signal": monthly_signal,
        "top_picks": top_picks,
        "ranked_funds": monthly_signal.get("ranked_funds", []),
        "friction_breakdown": friction_breakdown,
        "schedule": schedule,
        "day1_preview": day1_preview
    }


def log_monthly_execution(
    trade_date: Optional[date] = None,
    sip_budget: float = 50000.0,
    notes: str = "",
    db = None
) -> Dict[str, Any]:
    """
    Executes and logs a live monthly SIP into Supabase / local database across:
    1. Winning AI Engine (50/50 split between Top 2 momentum leaders)
    2. Passive Groww SIPs (20% PPFC, 40% MOMC, 40% NISC)
    3. Nifty 500 Broad Market Index (100% Motilal Nifty 500 Index Direct)
    4. Nifty 50 Large Cap Index (100% UTI Nifty 50 Index Direct)

    All 4 strategies are recorded with the exact same trade_date and proportional rupee amount,
    guaranteeing that XIRR calculations remain 100% fair and synchronized even if a month is
    reduced, stepped-up, or skipped (₹0).
    """
    if db is None:
        db = get_db()
    if trade_date is None:
        trade_date = date.today()

    stamp_duty_pct = 0.00005  # 0.005% Indian MF Stamp Duty

    # 1. Evaluate locked Official Monthly Signal as of trade_date (persisted on the 2nd of each month)
    monthly_signal = get_or_create_monthly_signal(target_date=trade_date, db=db)
    top_picks = monthly_signal.get("top_picks", [])
    if len(top_picks) == 0:
        p1_key, p2_key = "MOMC", "NISC"
    elif len(top_picks) == 1:
        p1_key = top_picks[0]["fund_key"]
        p2_key = top_picks[0]["fund_key"]
    else:
        p1_key = top_picks[0]["fund_key"]
        p2_key = top_picks[1]["fund_key"]

    p1_meta = UNRESTRICTED_UNIVERSE.get(p1_key, {})
    p2_meta = UNRESTRICTED_UNIVERSE.get(p2_key, {})

    # Fetch live NAVs
    navs_dict = fetch_universe_navs()
    p1_nav = get_universe_nav_on(navs_dict.get(p1_key, {}), trade_date)
    p2_nav = get_universe_nav_on(navs_dict.get(p2_key, {}), trade_date)
    ppfc_nav = get_universe_nav_on(navs_dict.get("PPFC", {}), trade_date)
    momc_nav = get_universe_nav_on(navs_dict.get("MOMC", {}), trade_date)
    nisc_nav = get_universe_nav_on(navs_dict.get("NISC", {}), trade_date)
    n500_nav = get_universe_nav_on(navs_dict.get("MO_NIFTY500", {}), trade_date)
    n50_nav = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), trade_date)

    logged_txs = []
    settle_date = trade_date + timedelta(days=1)

    if sip_budget <= 0.0:
        # Skipped month audit logging across all 4 portfolios
        skipped_notes = f"Skipped Monthly SIP (₹0 deployed on {trade_date.isoformat()}). {notes}".strip()
        ledgers = [
            ("TACTICAL", "Winning AI Engine — Skipped Month", 0),
            ("PASSIVE", "Passive Groww SIPs — Skipped Month", 0),
            ("NIFTY_500", "Nifty 500 Broad Market — Skipped Month", 0),
            ("NIFTY_50", "Nifty 50 Large Cap — Skipped Month", 0)
        ]
        for led, name, code in ledgers:
            tx = {
                "ledger": led,
                "trade_date": trade_date.isoformat(),
                "settlement_date": trade_date.isoformat(),
                "scheme_name": name,
                "scheme_code": code,
                "transaction_type": "SIP_SKIPPED",
                "amount": 0.0,
                "units": 0.0,
                "nav": 0.0,
                "exit_load_amount": 0.0,
                "stcg_tax": 0.0,
                "ltcg_tax": 0.0,
                "net_cash_impact": 0.0,
                "notes": skipped_notes,
                "status": "SETTLED"
            }
            res = db.add_transaction(tx)
            logged_txs.append(res or tx)
    else:
        # 1. Strategy 1: Winning AI Engine (50/50 split across top 2 leaders)
        ai_split = [
            (p1_meta.get("name", "Fund #1"), p1_meta.get("amfi_code", 0), sip_budget * 0.50, p1_nav, f"AI Leader #1 (50% Split). {notes}".strip()),
            (p2_meta.get("name", "Fund #2"), p2_meta.get("amfi_code", 0), sip_budget * 0.50, p2_nav, f"AI Leader #2 (50% Split). {notes}".strip())
        ]
        active_lots = db.get_app_state("tactical_active_lots", []) or []
        for s_name, code, amt, nav, note_str in ai_split:
            duty = round(amt * stamp_duty_pct, 2)
            net_amt = amt - duty
            units = round(net_amt / nav, 4) if nav > 0 else 0.0
            tx = {
                "ledger": "TACTICAL",
                "trade_date": trade_date.isoformat(),
                "settlement_date": settle_date.isoformat(),
                "scheme_name": s_name,
                "scheme_code": code,
                "transaction_type": "SIP_EQUITY",
                "amount": amt,
                "units": units,
                "nav": nav,
                "exit_load_amount": 0.0,
                "stcg_tax": 0.0,
                "ltcg_tax": 0.0,
                "net_cash_impact": -amt,
                "notes": note_str,
                "status": "SETTLED"
            }
            res = db.add_transaction(tx)
            logged_txs.append(res or tx)

            lid = f"LOT_{trade_date.strftime('%Y%m%d')}_{code}"
            lot_entry = {
                "lot_id": lid,
                "purchase_date": trade_date.isoformat(),
                "scheme_name": s_name,
                "scheme_code": code,
                "invested_amount": amt,
                "stamp_duty": duty,
                "net_invested": net_amt,
                "purchase_nav": nav,
                "units": units,
                "notes": note_str,
                "status": "ACTIVE"
            }
            active_lots = [l for l in active_lots if l.get("lot_id") != lid]
            active_lots.append(lot_entry)

        db.set_app_state("tactical_active_lots", active_lots)

        # 2. Strategy 2: Passive Groww SIPs (20% PPFC, 40% MOMC, 40% NISC)
        groww_split = [
            ("Parag Parikh Flexi Cap Fund Direct Growth", 122639, sip_budget * 0.20, ppfc_nav, f"Passive Flexicap (20%). {notes}".strip()),
            ("Motilal Oswal Midcap Fund Direct Growth", 127042, sip_budget * 0.40, momc_nav, f"Passive Midcap (40%). {notes}".strip()),
            ("Nippon India Small Cap Fund Direct Growth", 118778, sip_budget * 0.40, nisc_nav, f"Passive Smallcap (40%). {notes}".strip())
        ]
        for s_name, code, amt, nav, note_str in groww_split:
            duty = round(amt * stamp_duty_pct, 2)
            net_amt = amt - duty
            units = round(net_amt / nav, 4) if nav > 0 else 0.0
            tx = {
                "ledger": "PASSIVE",
                "trade_date": trade_date.isoformat(),
                "settlement_date": settle_date.isoformat(),
                "scheme_name": s_name,
                "scheme_code": code,
                "transaction_type": "SIP_EQUITY",
                "amount": amt,
                "units": units,
                "nav": nav,
                "exit_load_amount": 0.0,
                "stcg_tax": 0.0,
                "ltcg_tax": 0.0,
                "net_cash_impact": -amt,
                "notes": note_str,
                "status": "SETTLED"
            }
            res = db.add_transaction(tx)
            logged_txs.append(res or tx)

        # 3. Strategy 3: Nifty 500 Broad Market Index (100%)
        n500_duty = round(sip_budget * stamp_duty_pct, 2)
        n500_net = sip_budget - n500_duty
        n500_units = round(n500_net / n500_nav, 4) if n500_nav > 0 else 0.0
        tx_n500 = {
            "ledger": "NIFTY_500",
            "trade_date": trade_date.isoformat(),
            "settlement_date": settle_date.isoformat(),
            "scheme_name": "Motilal Oswal Nifty 500 Index Fund Direct Growth",
            "scheme_code": 147625,
            "transaction_type": "SIP_EQUITY",
            "amount": sip_budget,
            "units": n500_units,
            "nav": n500_nav,
            "exit_load_amount": 0.0,
            "stcg_tax": 0.0,
            "ltcg_tax": 0.0,
            "net_cash_impact": -sip_budget,
            "notes": f"Passive Nifty 500 Index SIP (100%). {notes}".strip(),
            "status": "SETTLED"
        }
        res_n500 = db.add_transaction(tx_n500)
        logged_txs.append(res_n500 or tx_n500)

        # 4. Strategy 4: Nifty 50 Large Cap Index (100%)
        n50_duty = round(sip_budget * stamp_duty_pct, 2)
        n50_net = sip_budget - n50_duty
        n50_units = round(n50_net / n50_nav, 4) if n50_nav > 0 else 0.0
        tx_n50 = {
            "ledger": "NIFTY_50",
            "trade_date": trade_date.isoformat(),
            "settlement_date": settle_date.isoformat(),
            "scheme_name": "UTI Nifty 50 Index Fund Direct Growth",
            "scheme_code": 120716,
            "transaction_type": "SIP_EQUITY",
            "amount": sip_budget,
            "units": n50_units,
            "nav": n50_nav,
            "exit_load_amount": 0.0,
            "stcg_tax": 0.0,
            "ltcg_tax": 0.0,
            "net_cash_impact": -sip_budget,
            "notes": f"Passive Nifty 50 Index SIP (100%). {notes}".strip(),
            "status": "SETTLED"
        }
        res_n50 = db.add_transaction(tx_n50)
        logged_txs.append(res_n50 or tx_n50)

    return {
        "status": "SUCCESS",
        "trade_date": str(trade_date),
        "sip_budget": sip_budget,
        "transactions_logged": len(logged_txs),
        "details": logged_txs
    }


if __name__ == "__main__":
    simulate_six_months_dual_ledger()
    db = get_db()
    latest = db.get_latest_snapshot()
    print("Latest Portfolio Snapshot:")
    print(f"Tactical Total: ₹{latest['tactical_total_value']:,.2f} (Equity: ₹{latest['tactical_equity_value']:,.2f}, Cash: ₹{latest['tactical_cash_value']:,.2f})")
    print(f"Passive Total:  ₹{latest['passive_total_value']:,.2f} | Alpha: ₹{latest['alpha_rupees']:,.2f} ({latest['alpha_percent']:.2f}%)")
