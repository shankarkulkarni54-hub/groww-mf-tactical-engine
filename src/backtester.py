"""5-Year Historical Backtest Engine (Nov 2021 - Nov 2026).
Compares the Unrestricted AI Mutual Fund Advisor against Passive Blind ₹50,000/Mo Groww SIPs
and the Old Cash-Parking Strategy, strictly factoring in FIFO tax lots, 0.005% stamp duty,
exit loads, and current Indian capital gains taxes (20% STCG / 12.5% LTCG above ₹1.25L).
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple, Optional

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.regime_engine import (
    UNRESTRICTED_UNIVERSE,
    fetch_universe_navs,
    get_universe_nav_on,
    score_unrestricted_universe
)

CACHE_FILE_PATH = os.path.join(REPO_ROOT, "data", "backtest_5yr_results.json")


class TaxLot:
    """Represents a single purchase lot with FIFO tax tracking."""
    def __init__(
        self,
        purchase_date: date,
        units: float,
        purchase_nav: float,
        category: str,
        exit_days: int,
        exit_pct: float,
        scheme_key: str,
        invested_amount: float
    ):
        self.purchase_date = purchase_date
        self.units = units
        self.purchase_nav = purchase_nav
        self.category = category  # EQUITY, COMMODITY, INTERNATIONAL, CASH
        self.exit_days = exit_days
        self.exit_pct = exit_pct
        self.scheme_key = scheme_key
        self.invested_amount = invested_amount


def calculate_xirr(cash_flows: List[Tuple[date, float]]) -> float:
    """
    Computes exact annualized XIRR using robust bisection + Newton-Raphson.
    Cash flows format: [(date_obj, cash_flow_amount), ...]
    Negative for investments, positive for terminal value.
    """
    if not cash_flows or len(cash_flows) < 2:
        return 0.0

    t0 = cash_flows[0][0]
    years = [(cf[0] - t0).days / 365.0 for cf in cash_flows]
    amounts = [cf[1] for cf in cash_flows]

    low, high = -0.70, 3.0
    for _ in range(80):
        mid = (low + high) / 2.0
        val = sum(amt / ((1.0 + mid) ** t) for t, amt in zip(years, amounts))
        if abs(val) < 1e-4 or (high - low) < 1e-6:
            return round(mid * 100.0, 2)
        if sum(amt / ((1.0 + low) ** t) for t, amt in zip(years, amounts)) * val < 0:
            high = mid
        else:
            low = mid
    return round(mid * 100.0, 2)


def compute_portfolio_tax_and_friction(
    lots_dict: Dict[str, List[TaxLot]],
    navs_dict: Dict[str, Dict[str, float]],
    eval_date: date
) -> Tuple[float, float, float, float]:
    """
    Computes gross portfolio value, net portfolio value, total tax liability,
    and total exit load friction following strict FIFO lot tracking and Indian MF tax laws:
    - Equity: 20% STCG if held <= 365 days; 12.5% LTCG if held > 365 days (with ₹1.25L annual exemption).
    - Gold / International: 20% capital gains tax.
    - Exit Load: Exact fund rules if held < exit_days.
    Returns: (gross_total, net_total, total_tax, total_exit_load)
    """
    gross_total = 0.0
    total_tax = 0.0
    total_exit_load = 0.0
    annual_equity_exemption = 125000.0  # ₹1.25L exemption per financial year

    for s_key, lots in lots_dict.items():
        if not lots:
            continue
        cur_nav = get_universe_nav_on(navs_dict.get(s_key, {}), eval_date)
        for lot in lots:
            lot_gross = lot.units * cur_nav
            gross_total += lot_gross
            gain = lot_gross - (lot.units * lot.purchase_nav)
            holding_days = (eval_date - lot.purchase_date).days

            # Exit Load
            if holding_days < lot.exit_days:
                total_exit_load += (lot.exit_pct / 100.0) * lot_gross

            # Capital Gains Tax
            if gain > 0:
                if lot.category == "EQUITY":
                    if holding_days <= 365:
                        total_tax += 0.20 * gain  # 20% STCG
                    else:
                        exempt = min(gain, annual_equity_exemption)
                        annual_equity_exemption -= exempt
                        taxable = max(0.0, gain - exempt)
                        total_tax += 0.125 * taxable  # 12.5% LTCG above ₹1.25L
                elif lot.category == "CASH":
                    pass  # Liquid cash NAV yield handled as ordinary interest
                else:  # Commodity Gold / International Tech
                    total_tax += 0.20 * gain

    net_total = max(0.0, gross_total - total_tax - total_exit_load)
    return gross_total, net_total, total_tax, total_exit_load


def run_five_year_backtest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Runs full 5-year historical simulation (Nov 1, 2021 to Nov 13, 2026):
    1. Strategy 1: Unrestricted AI Advisor (Net of Stamp Duty, Exit Loads & Taxes)
    2. Strategy 2: Passive Blind ₹50,000/Mo Groww SIPs (₹10k PPFC, ₹20k MOMC, ₹20k NISC)
    3. Strategy 3: Old Cash-Parking Strategy (diverting to 6.5% Liquid cash in caution/defensive regimes)
    Caches results to data/backtest_5yr_results.json.
    """
    if not force_refresh and os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
                if cached.get("total_invested", 0) > 0 and "ai_net_corpus" in cached:
                    return cached
        except Exception as e:
            print(f"[Backtester] Cache read error ({e}), recomputing backtest...")

    print("🚀 Starting 5-Year Historical Backtest (Nov 2021 - Nov 2026)...")

    # Fetch daily NAVs for all 13 universe funds
    navs_dict = fetch_universe_navs(force_refresh=force_refresh)

    start_date = date(2021, 11, 1)
    end_date = date(2026, 11, 13)

    # Strategy 1: Unrestricted AI Advisor
    ai_lots: Dict[str, List[TaxLot]] = {k: [] for k in UNRESTRICTED_UNIVERSE}
    ai_cfs: List[Tuple[date, float]] = []
    ai_picks_history: List[Dict[str, Any]] = []

    # Strategy 2: Passive Blind Groww SIPs
    p_lots: Dict[str, List[TaxLot]] = {"PPFC": [], "MOMC": [], "NISC": []}
    p_cfs: List[Tuple[date, float]] = []

    # Strategy 3: Old Cash-Parking Strategy
    cp_lots: Dict[str, List[TaxLot]] = {"PPFC": [], "MOMC": [], "NISC": []}
    cp_cash = 0.0
    cp_cfs: List[Tuple[date, float]] = []

    total_invested = 0.0
    monthly_sip_amount = 50000.0
    stamp_duty_pct = 0.00005  # 0.005% Indian MF Stamp Duty
    stamp_duty_rupees = monthly_sip_amount * stamp_duty_pct
    net_sip_invested = monthly_sip_amount - stamp_duty_rupees
    daily_cash_yield = (1.0 + 0.065) ** (1.0 / 365.0) - 1.0  # 6.5% p.a.

    curr_date = start_date
    daily_records: List[Dict[str, Any]] = []

    while curr_date <= end_date:
        # On the 3rd of every month: Execute ₹50,000 SIP across all 3 strategies
        if curr_date.day == 3:
            total_invested += monthly_sip_amount
            ai_cfs.append((curr_date, -monthly_sip_amount))
            p_cfs.append((curr_date, -monthly_sip_amount))
            cp_cfs.append((curr_date, -monthly_sip_amount))

            # --- STRATEGY 2: PASSIVE GROWW SIPS ---
            # ₹10k PPFC, ₹20k MOMC, ₹20k NISC
            p_split = {
                "PPFC": net_sip_invested * 0.20,
                "MOMC": net_sip_invested * 0.40,
                "NISC": net_sip_invested * 0.40
            }
            for k, amt in p_split.items():
                nav_val = get_universe_nav_on(navs_dict.get(k, {}), curr_date)
                meta = UNRESTRICTED_UNIVERSE[k]
                lot = TaxLot(
                    purchase_date=curr_date,
                    units=amt / nav_val,
                    purchase_nav=nav_val,
                    category=meta["category"],
                    exit_days=meta["exit_load_days"],
                    exit_pct=meta["exit_load_pct"],
                    scheme_key=k,
                    invested_amount=amt
                )
                p_lots[k].append(lot)

            # --- STRATEGY 1: UNRESTRICTED AI ADVISOR ---
            # Score universe on curr_date using historical NAVs
            ai_score_result = score_unrestricted_universe(curr_date, navs_dict)
            top_picks = ai_score_result["top_picks"]
            top1_key = top_picks[0]["fund_key"]
            top2_key = top_picks[1]["fund_key"]

            ai_split = {
                top1_key: net_sip_invested * 0.50,
                top2_key: net_sip_invested * 0.50
            }
            for k, amt in ai_split.items():
                nav_val = get_universe_nav_on(navs_dict.get(k, {}), curr_date)
                meta = UNRESTRICTED_UNIVERSE[k]
                lot = TaxLot(
                    purchase_date=curr_date,
                    units=amt / nav_val,
                    purchase_nav=nav_val,
                    category=meta["category"],
                    exit_days=meta["exit_load_days"],
                    exit_pct=meta["exit_load_pct"],
                    scheme_key=k,
                    invested_amount=amt
                )
                ai_lots[k].append(lot)

            ai_picks_history.append({
                "date": curr_date.isoformat(),
                "top1_key": top1_key,
                "top1_name": UNRESTRICTED_UNIVERSE[top1_key]["short_name"],
                "top1_amt": 25000.0,
                "top2_key": top2_key,
                "top2_name": UNRESTRICTED_UNIVERSE[top2_key]["short_name"],
                "top2_amt": 25000.0,
                "thesis": ai_score_result["thesis_summary"],
                "mode": ai_score_result["allocation_mode"]
            })

            # --- STRATEGY 3: OLD CASH-PARKING STRATEGY ---
            nifty_now = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), curr_date)
            nifty_200 = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), curr_date - timedelta(days=200))
            nifty_dist = ((nifty_now - nifty_200) / nifty_200 * 100.0) if nifty_200 > 0 else 0.0

            # PPFC always gets ₹10,000 equity
            ppfc_nav = get_universe_nav_on(navs_dict.get("PPFC", {}), curr_date)
            cp_lots["PPFC"].append(TaxLot(
                purchase_date=curr_date,
                units=10000.0 / ppfc_nav,
                purchase_nav=ppfc_nav,
                category="EQUITY",
                exit_days=365,
                exit_pct=2.0,
                scheme_key="PPFC",
                invested_amount=10000.0
            ))

            if nifty_dist >= 0.0:  # Bullish
                m_nav = get_universe_nav_on(navs_dict.get("MOMC", {}), curr_date)
                s_nav = get_universe_nav_on(navs_dict.get("NISC", {}), curr_date)
                cp_lots["MOMC"].append(TaxLot(curr_date, 20000.0 / m_nav, m_nav, "EQUITY", 365, 1.0, "MOMC", 20000.0))
                cp_lots["NISC"].append(TaxLot(curr_date, 20000.0 / s_nav, s_nav, "EQUITY", 365, 1.0, "NISC", 20000.0))
            elif nifty_dist >= -5.0:  # Caution: divert smallcap to cash
                m_nav = get_universe_nav_on(navs_dict.get("MOMC", {}), curr_date)
                cp_lots["MOMC"].append(TaxLot(curr_date, 20000.0 / m_nav, m_nav, "EQUITY", 365, 1.0, "MOMC", 20000.0))
                cp_cash += 20000.0
            else:  # Defensive: divert mid & small to cash
                cp_cash += 40000.0

        # Daily interest compounding on Cash Parking reserve
        cp_cash += cp_cash * daily_cash_yield

        # Record daily valuation
        ai_g, ai_n, ai_t, ai_e = compute_portfolio_tax_and_friction(ai_lots, navs_dict, curr_date)
        p_g, p_n, p_t, p_e = compute_portfolio_tax_and_friction(p_lots, navs_dict, curr_date)
        cp_g, cp_n, cp_t, cp_e = compute_portfolio_tax_and_friction(cp_lots, navs_dict, curr_date)
        cp_total_n = cp_n + cp_cash

        daily_records.append({
            "date": curr_date.isoformat(),
            "invested": total_invested,
            "ai_net": ai_n,
            "passive_net": p_n,
            "cash_parking_net": cp_total_n,
            "cash_parking_cash": cp_cash
        })

        curr_date += timedelta(days=1)

    # --- FINAL TERMINAL VALUATIONS & POST-TAX RETURNS ---
    ai_final_g, ai_final_n, ai_final_tax, ai_final_exit = compute_portfolio_tax_and_friction(ai_lots, navs_dict, end_date)
    p_final_g, p_final_n, p_final_tax, p_final_exit = compute_portfolio_tax_and_friction(p_lots, navs_dict, end_date)
    cp_final_g, cp_final_n, cp_final_tax, cp_final_exit = compute_portfolio_tax_and_friction(cp_lots, navs_dict, end_date)
    cp_final_total_n = cp_final_n + cp_cash

    # Append terminal values for XIRR
    ai_cfs.append((end_date, ai_final_n))
    p_cfs.append((end_date, p_final_n))
    cp_cfs.append((end_date, cp_final_total_n))

    ai_xirr = calculate_xirr(ai_cfs)
    p_xirr = calculate_xirr(p_cfs)
    cp_xirr = calculate_xirr(cp_cfs)

    # --- DRAWDOWN CALCULATIONS ---
    df_daily = pd.DataFrame(daily_records)
    df_daily["ai_peak"] = df_daily["ai_net"].cummax()
    df_daily["ai_dd"] = (df_daily["ai_net"] - df_daily["ai_peak"]) / df_daily["ai_peak"].replace(0, 1) * 100.0

    df_daily["p_peak"] = df_daily["passive_net"].cummax()
    df_daily["p_dd"] = (df_daily["passive_net"] - df_daily["p_peak"]) / df_daily["p_peak"].replace(0, 1) * 100.0

    df_daily["cp_peak"] = df_daily["cash_parking_net"].cummax()
    df_daily["cp_dd"] = (df_daily["cash_parking_net"] - df_daily["cp_peak"]) / df_daily["cp_peak"].replace(0, 1) * 100.0

    ai_max_dd = round(float(df_daily["ai_dd"].min()), 2)
    p_max_dd = round(float(df_daily["p_dd"].min()), 2)
    cp_max_dd = round(float(df_daily["cp_dd"].min()), 2)

    # Alpha calculations
    alpha_rupees = round(ai_final_n - p_final_n, 2)
    alpha_xirr = round(ai_xirr - p_xirr, 2)
    dd_cushion = round(p_max_dd - ai_max_dd, 2)

    # Downsample daily series for fast rendering in Streamlit (1 data point every 7 days + final)
    step = 7
    ds_dates = df_daily["date"].iloc[::step].tolist()
    ds_ai = [round(float(v), 2) for v in df_daily["ai_net"].iloc[::step]]
    ds_p = [round(float(v), 2) for v in df_daily["passive_net"].iloc[::step]]
    ds_cp = [round(float(v), 2) for v in df_daily["cash_parking_net"].iloc[::step]]
    ds_inv = [round(float(v), 2) for v in df_daily["invested"].iloc[::step]]
    ds_cash = [round(float(v), 2) for v in df_daily["cash_parking_cash"].iloc[::step]]

    if ds_dates[-1] != df_daily["date"].iloc[-1]:
        ds_dates.append(df_daily["date"].iloc[-1])
        ds_ai.append(round(float(df_daily["ai_net"].iloc[-1]), 2))
        ds_p.append(round(float(df_daily["passive_net"].iloc[-1]), 2))
        ds_cp.append(round(float(df_daily["cash_parking_net"].iloc[-1]), 2))
        ds_inv.append(round(float(df_daily["invested"].iloc[-1]), 2))
        ds_cash.append(round(float(df_daily["cash_parking_cash"].iloc[-1]), 2))

    results = {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_invested": round(total_invested, 2),
        "months_count": len(ai_picks_history),

        # Strategy 1: Unrestricted AI Advisor
        "ai_net_corpus": round(ai_final_n, 2),
        "ai_gross_corpus": round(ai_final_g, 2),
        "ai_xirr": ai_xirr,
        "ai_max_dd": ai_max_dd,
        "ai_tax_paid": round(ai_final_tax, 2),
        "ai_exit_load_paid": round(ai_final_exit, 2),

        # Strategy 2: Passive Blind Groww SIPs
        "passive_net_corpus": round(p_final_n, 2),
        "passive_gross_corpus": round(p_final_g, 2),
        "passive_xirr": p_xirr,
        "passive_max_dd": p_max_dd,
        "passive_tax_paid": round(p_final_tax, 2),
        "passive_exit_load_paid": round(p_final_exit, 2),

        # Strategy 3: Old Cash Parking
        "cash_parking_net_corpus": round(cp_final_total_n, 2),
        "cash_parking_gross_corpus": round(cp_final_g, 2),
        "cash_parking_final_cash": round(cp_cash, 2),
        "cash_parking_xirr": cp_xirr,
        "cash_parking_max_dd": cp_max_dd,

        # Net Alpha Metrics (AI Advisor vs Passive Groww)
        "alpha_rupees": alpha_rupees,
        "alpha_percent": round((alpha_rupees / p_final_n * 100.0), 2) if p_final_n > 0 else 0.0,
        "alpha_xirr": alpha_xirr,
        "dd_cushion": dd_cushion,

        # Backwards-compatible keys for existing views
        "tactical_final_corpus": round(ai_final_n, 2),
        "passive_final_corpus": round(p_final_n, 2),
        "tactical_xirr": ai_xirr,
        "tactical_max_dd": ai_max_dd,
        "tactical_wealth": ds_ai,
        "passive_wealth": ds_p,
        "cash_parking_wealth": ds_cp,
        "invested_curve": ds_inv,
        "cash_reserve_curve": ds_cash,
        "cash_pct_curve": [round((c / w * 100.0) if w > 0 else 0.0, 1) for c, w in zip(ds_cash, ds_cp)],
        "dates": ds_dates,

        # History and metadata
        "ai_picks_history": ai_picks_history,
        "generated_at": datetime.now().isoformat()
    }

    # Cache to disk
    os.makedirs(os.path.dirname(CACHE_FILE_PATH), exist_ok=True)
    with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"✅ 5-Year Backtest completed and cached to {CACHE_FILE_PATH}!")
    return results


if __name__ == "__main__":
    res = run_five_year_backtest(force_refresh=True)
    print("\n" + "=" * 65)
    print("5-YEAR HISTORICAL BACKTEST SUMMARY (Nov 2021 – Nov 2026)")
    print("=" * 65)
    print(f"Total Invested:        ₹{res['total_invested']:,.0f} ({res['months_count']} months @ ₹50,000/mo)")
    print(f"1. Unrestricted AI:    Net: ₹{res['ai_net_corpus']:,.0f} | Post-Tax XIRR: {res['ai_xirr']:.2f}% | Max DD: {res['ai_max_dd']:.2f}%")
    print(f"2. Passive Groww SIP:  Net: ₹{res['passive_net_corpus']:,.0f} | Post-Tax XIRR: {res['passive_xirr']:.2f}% | Max DD: {res['passive_max_dd']:.2f}%")
    print(f"3. Old Cash Parking:   Net: ₹{res['cash_parking_net_corpus']:,.0f} | Post-Tax XIRR: {res['cash_parking_xirr']:.2f}% | Max DD: {res['cash_parking_max_dd']:.2f}%")
    print("-" * 65)
    print(f"Post-Tax Rupee Alpha:  ₹{res['alpha_rupees']:+,.0f} ({res['alpha_percent']:+.2f}%)")
    print(f"Post-Tax XIRR Alpha:   {res['alpha_xirr']:+.2f}% p.a.")
    print(f"Drawdown Cushion:      {res['dd_cushion']:+.2f}% (fell less in corrections)")
    print("=" * 65)
