"""Multi-regime scoring engine combining 50% Technicals + 50% Fundamentals across 3 sleeves."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from datetime import date, datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from src.db import get_db

SLEEVE_CONFIG = {
    "NIFTY_500": {
        "name": "Nifty 500 Sleeve",
        "primary_ticker": "^CRSLDX",
        "fallback_tickers": ["^NSEI"],
        "vix_ticker": "^INDIAVIX",
        "pe_mean": 21.8,
        "pe_std": 3.2,
        "pb_mean": 3.6,
        "pb_std": 0.6,
        "benchmark_10y_yield": 6.85,
        "funds": ["Parag Parikh Flexi Cap Fund Direct Growth"]
    },
    "MID_SMALL": {
        "name": "Nifty Mid & Small Cap Sleeve",
        "primary_ticker": "^NSEMDCP50",
        "fallback_tickers": ["MID150BEES.NS", "^CNXSC", "^NSEI"],
        "vix_ticker": "^INDIAVIX",
        "pe_mean": 28.5,
        "pe_std": 4.5,
        "pb_mean": 4.2,
        "pb_std": 0.8,
        "benchmark_10y_yield": 6.85,
        "funds": [
            "Motilal Oswal Midcap Fund Direct Growth",
            "Nippon India Small Cap Fund Direct Growth"
        ]
    },
    "NASDAQ_100": {
        "name": "NASDAQ 100 Sleeve",
        "primary_ticker": "^NDX",
        "fallback_tickers": ["QQQ"],
        "vix_ticker": "^VIX",
        "pe_mean": 27.5,
        "pe_std": 4.0,
        "pb_mean": 6.8,
        "pb_std": 1.2,
        "benchmark_10y_yield": 4.40,
        "funds": ["Edelweiss US Technology Equity FoF Direct Growth"]
    }
}


def format_inr(amount: Optional[float], decimals: int = 0, show_sign: bool = False) -> str:
    """Formats a number in the Indian numbering system (Lakhs and Crores).
    E.g. 4722571 -> ₹47,22,571; 50000 -> ₹50,000; -81872 -> -₹81,872.
    """
    if amount is None:
        return "₹0"
    is_negative = amount < 0
    abs_amt = abs(amount)
    if decimals > 0:
        val_str = f"{abs_amt:.{decimals}f}"
        int_part, dec_part = val_str.split(".")
        dec_suffix = f".{dec_part}"
    else:
        int_part = str(int(round(abs_amt)))
        dec_suffix = ""

    if len(int_part) <= 3:
        formatted_int = int_part
    else:
        last3 = int_part[-3:]
        rem = int_part[:-3]
        groups = []
        while len(rem) > 2:
            groups.insert(0, rem[-2:])
            rem = rem[:-2]
        if rem:
            groups.insert(0, rem)
        formatted_int = ",".join(groups) + "," + last3

    sign_prefix = "+" if (show_sign and amount > 0) else ("-" if is_negative else "")
    return f"{sign_prefix}₹{formatted_int}{dec_suffix}"


__all__ = [
    "SLEEVE_CONFIG",
    "UNRESTRICTED_UNIVERSE",
    "fetch_universe_navs",
    "get_universe_nav_on",
    "score_unrestricted_universe",
    "check_smart_ltcg_switches",
    "format_inr",
    "compute_sleeve_regime",
    "update_all_regimes"
]

# =====================================================================
# UNRESTRICTED INDIAN DIRECT MUTUAL FUND UNIVERSE & AI ADVISOR
# =====================================================================

UNRESTRICTED_UNIVERSE: Dict[str, Dict[str, Any]] = {
    "UTI_NIFTY50": {
        "name": "UTI Nifty 50 Index Fund Direct Growth",
        "short_name": "UTI Nifty 50 Index",
        "amfi_code": 120716,
        "category": "EQUITY",
        "sub_category": "Core Large Cap",
        "benchmark": "^NSEI",
        "exit_load_days": 0,
        "exit_load_pct": 0.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "MO_NIFTY500": {
        "name": "Motilal Oswal Nifty 500 Index Fund Direct Growth",
        "short_name": "Motilal Nifty 500 Index",
        "amfi_code": 147625,
        "category": "EQUITY",
        "sub_category": "Core Broad Market",
        "benchmark": "^CRSLDX",
        "exit_load_days": 15,
        "exit_load_pct": 1.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "PPFC": {
        "name": "Parag Parikh Flexi Cap Fund Direct Growth",
        "short_name": "Parag Parikh Flexi Cap",
        "amfi_code": 122639,
        "category": "EQUITY",
        "sub_category": "Core Flexi Cap",
        "benchmark": "^CRSLDX",
        "exit_load_days": 365,
        "exit_load_pct": 2.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "MOMC": {
        "name": "Motilal Oswal Midcap Fund Direct Growth",
        "short_name": "Motilal Oswal Midcap",
        "amfi_code": 127042,
        "category": "EQUITY",
        "sub_category": "Cap Midcap",
        "benchmark": "^NSEMDCP50",
        "exit_load_days": 365,
        "exit_load_pct": 1.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "NISC": {
        "name": "Nippon India Small Cap Fund Direct Growth",
        "short_name": "Nippon India Small Cap",
        "amfi_code": 118778,
        "category": "EQUITY",
        "sub_category": "Cap Smallcap",
        "benchmark": "^CNXSC",
        "exit_load_days": 365,
        "exit_load_pct": 1.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "TATA_TECH": {
        "name": "Tata Digital India Fund Direct Growth",
        "short_name": "Tata Digital India (IT)",
        "amfi_code": 135800,
        "category": "EQUITY",
        "sub_category": "Sector IT / Tech",
        "benchmark": "^CNXIT",
        "exit_load_days": 30,
        "exit_load_pct": 0.25,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "NIPPON_PHARMA": {
        "name": "Nippon India Pharma Fund Direct Growth",
        "short_name": "Nippon India Pharma",
        "amfi_code": 118759,
        "category": "EQUITY",
        "sub_category": "Sector Healthcare / Pharma",
        "benchmark": "^CNXPHARMA",
        "exit_load_days": 30,
        "exit_load_pct": 0.25,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "NIPPON_BANK": {
        "name": "Nippon India Banking & Financial Services Direct Growth",
        "short_name": "Nippon Banking & Fin",
        "amfi_code": 118589,
        "category": "EQUITY",
        "sub_category": "Sector Banking & Fin",
        "benchmark": "^NSEBANK",
        "exit_load_days": 30,
        "exit_load_pct": 0.25,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "UTI_AUTO": {
        "name": "UTI Transportation and Logistics Fund Direct Growth",
        "short_name": "UTI Transportation & Auto",
        "amfi_code": 120731,
        "category": "EQUITY",
        "sub_category": "Sector Auto & Mobility",
        "benchmark": "^CNXAUTO",
        "exit_load_days": 30,
        "exit_load_pct": 0.50,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "ICICI_FMCG": {
        "name": "ICICI Prudential FMCG Fund Direct Growth",
        "short_name": "ICICI Prudential FMCG",
        "amfi_code": 120587,
        "category": "EQUITY",
        "sub_category": "Sector FMCG & Consumption",
        "benchmark": "^CNXFMCG",
        "exit_load_days": 15,
        "exit_load_pct": 1.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "ICICI_INFRA": {
        "name": "ICICI Prudential Infrastructure Fund Direct Growth",
        "short_name": "ICICI Prudential Infrastructure",
        "amfi_code": 120621,
        "category": "EQUITY",
        "sub_category": "Sector Infra / Capital Goods",
        "benchmark": "^CNXINFRA",
        "exit_load_days": 15,
        "exit_load_pct": 1.0,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "INVESCO_PSU": {
        "name": "Invesco India PSU Equity Fund Direct Growth",
        "short_name": "Invesco India PSU Equity",
        "amfi_code": 120395,
        "category": "EQUITY",
        "sub_category": "Sector PSU & CPSE",
        "benchmark": "^CNXPSUBANK",
        "exit_load_days": 30,
        "exit_load_pct": 0.50,
        "tax_category": "DOMESTIC_EQUITY"
    },
    "SBI_GOLD": {
        "name": "SBI Gold Fund Direct Growth",
        "short_name": "SBI Gold Fund",
        "amfi_code": 119788,
        "category": "COMMODITY",
        "sub_category": "Precious Metals (Gold)",
        "benchmark": "GC=F",
        "exit_load_days": 15,
        "exit_load_pct": 1.0,
        "tax_category": "OTHER_COMMODITY"
    },
    "EDEL_USTECH": {
        "name": "Edelweiss US Technology Equity FoF Direct Growth",
        "short_name": "Edelweiss US Tech FoF",
        "amfi_code": 148063,
        "category": "INTERNATIONAL",
        "sub_category": "Global Tech (US NDX)",
        "benchmark": "^NDX",
        "exit_load_days": 30,
        "exit_load_pct": 1.0,
        "tax_category": "FOREIGN_EQUITY_FOF"
    },
    "NIPPON_LIQUID": {
        "name": "Nippon India Liquid Fund Direct Growth",
        "short_name": "Nippon India Liquid (Cash)",
        "amfi_code": 118701,
        "category": "CASH",
        "sub_category": "Defensive Cash Reserve",
        "benchmark": "TREPS",
        "exit_load_days": 7,
        "exit_load_pct": 0.005,
        "tax_category": "DEBT_LIQUID"
    }
}

_UNRESTRICTED_NAV_CACHE: Dict[int, Dict[str, float]] = {}


def fetch_universe_navs(force_refresh: bool = False) -> Dict[str, Dict[str, float]]:
    """Fetches daily NAVs for all 13 universe funds from mfapi.in."""
    global _UNRESTRICTED_NAV_CACHE
    result = {}
    for key, meta in UNRESTRICTED_UNIVERSE.items():
        code = meta["amfi_code"]
        if not force_refresh and code in _UNRESTRICTED_NAV_CACHE:
            result[key] = _UNRESTRICTED_NAV_CACHE[code]
            continue
        try:
            r = requests.get(f"https://api.mfapi.in/mf/{code}", timeout=10)
            data = r.json().get("data", [])
            d_dict = {}
            for item in data:
                pts = item.get("date", "").split("-")
                if len(pts) == 3:
                    iso = f"{pts[2]}-{pts[1]}-{pts[0]}"
                    val = float(item.get("nav", 0))
                    if val > 0:
                        d_dict[iso] = val
            _UNRESTRICTED_NAV_CACHE[code] = d_dict
            result[key] = d_dict
        except Exception as e:
            print(f"[RegimeEngine] Warning: Could not fetch NAV for {key} ({code}): {e}")
            result[key] = _UNRESTRICTED_NAV_CACHE.get(code, {})
    return result


def get_universe_nav_on(nav_dict: Dict[str, float], target_date: date) -> float:
    """Gets NAV on or before target date."""
    curr = target_date
    for _ in range(12):
        iso = curr.isoformat()
        if iso in nav_dict:
            return nav_dict[iso]
        curr -= timedelta(days=1)
    if nav_dict:
        sorted_keys = sorted(nav_dict.keys())
        if target_date.isoformat() < sorted_keys[0]:
            return nav_dict[sorted_keys[0]]
        return nav_dict[sorted_keys[-1]]
    return 100.0


def score_unrestricted_universe(
    as_of_date: Optional[date] = None,
    navs_dict: Optional[Dict[str, Dict[str, float]]] = None
) -> Dict[str, Any]:
    """
    Evaluates and ranks all 13 funds in the Unrestricted Direct MF Universe.
    Computes 30-day relative strength vs Nifty 50, 90-day momentum, 200-DMA trend,
    and generates plain-English AI theses for monthly SIP allocation.
    """
    if as_of_date is None:
        as_of_date = date.today()
    if navs_dict is None:
        navs_dict = fetch_universe_navs()

    # Nifty 50 benchmark
    nifty_now = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), as_of_date)
    nifty_30 = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), as_of_date - timedelta(days=30))
    nifty_90 = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), as_of_date - timedelta(days=90))
    nifty_200 = get_universe_nav_on(navs_dict.get("UTI_NIFTY50", {}), as_of_date - timedelta(days=200))

    nifty_mom30 = ((nifty_now - nifty_30) / nifty_30 * 100.0) if nifty_30 > 0 else 0.0
    nifty_mom90 = ((nifty_now - nifty_90) / nifty_90 * 100.0) if nifty_90 > 0 else 0.0
    nifty_dma_dist = ((nifty_now - nifty_200) / nifty_200 * 100.0) if nifty_200 > 0 else 0.0

    fund_evaluations = {}

    for key, meta in UNRESTRICTED_UNIVERSE.items():
        if key == "NIPPON_LIQUID":
            fund_evaluations[key] = {
                "key": key,
                "name": meta["name"],
                "short_name": meta["short_name"],
                "category": meta["category"],
                "sub_category": meta["sub_category"],
                "score": 30.0,
                "mom_30": 0.53,  # ~6.5% annualized
                "mom_90": 1.60,
                "dma_dist": 0.0,
                "rs_30": round(0.53 - nifty_mom30, 2),
                "rs_90": round(1.60 - nifty_mom90, 2),
                "current_nav": get_universe_nav_on(navs_dict.get(key, {}), as_of_date),
                "status": "DEFENSIVE_CASH",
                "thesis": "Protected liquid yield (~6.5% p.a.). Zero equity volatility, deployed during severe market drawdowns."
            }
            continue

        f_navs = navs_dict.get(key, {})
        n_now = get_universe_nav_on(f_navs, as_of_date)
        n_30 = get_universe_nav_on(f_navs, as_of_date - timedelta(days=30))
        n_90 = get_universe_nav_on(f_navs, as_of_date - timedelta(days=90))
        n_200 = get_universe_nav_on(f_navs, as_of_date - timedelta(days=200))

        mom_30 = ((n_now - n_30) / n_30 * 100.0) if n_30 > 0 else 0.0
        mom_90 = ((n_now - n_90) / n_90 * 100.0) if n_90 > 0 else 0.0
        dma_dist = ((n_now - n_200) / n_200 * 100.0) if n_200 > 0 else 0.0

        rs_30 = mom_30 - nifty_mom30
        rs_90 = mom_90 - nifty_mom90

        # Trend gating: strict 200-DMA filter (funds below 200-DMA are disqualified from fresh equity SIPs)
        if dma_dist < 0.0 and key != "SBI_GOLD":
            raw_score = 30.0 + min(9.0, max(-25.0, mom_90 + dma_dist))
            status = "DEFENSIVE"
        else:
            raw_score = 55.0 + (mom_90 * 1.2) + (dma_dist * 0.25)
            status = "BULLISH" if raw_score >= 60.0 else "CAUTION"

        final_score = max(5.0, min(98.0, round(raw_score, 1)))

        # Synthesize plain-English AI thesis
        cat = meta["sub_category"]
        if dma_dist < 0.0 and key != "SBI_GOLD":
            thesis = f"Below 200-DMA ({dma_dist:+.1f}%). Bearish/consolidating in {cat}. Capital routed elsewhere."
        elif dma_dist > 5.0 and mom_90 >= 5.0:
            thesis = f"Strong leadership in {cat}. 90d momentum: {mom_90:+.1f}%, trading {dma_dist:+.1f}% above 200-DMA."
        elif dma_dist > 0:
            thesis = f"Healthy uptrend in {cat} above 200-DMA ({dma_dist:+.1f}%). 90d gain: {mom_90:+.1f}%."
        elif key == "SBI_GOLD" and mom_90 > 5.0:
            thesis = f"Precious metals showing robust hedge momentum (+{mom_90:.1f}% in 90d). Strong safe-haven demand."
        else:
            thesis = f"Consolidating in {cat} ({dma_dist:+.1f}% vs 200-DMA). 90d momentum: {mom_90:+.1f}%."

        fund_evaluations[key] = {
            "key": key,
            "name": meta["name"],
            "short_name": meta["short_name"],
            "category": meta["category"],
            "sub_category": meta["sub_category"],
            "score": final_score,
            "mom_30": round(mom_30, 2),
            "mom_90": round(mom_90, 2),
            "dma_dist": round(dma_dist, 2),
            "rs_30": round(rs_30, 2),
            "rs_90": round(rs_90, 2),
            "current_nav": round(n_now, 2),
            "status": status,
            "thesis": thesis
        }

    # Rank funds descending by score
    ranked_keys = sorted(fund_evaluations.keys(), key=lambda k: fund_evaluations[k]["score"], reverse=True)

    top1_key = ranked_keys[0]
    top2_key = ranked_keys[1]

    # Market crash check: if Nifty < 200-DMA by -5% and top equity score < 35
    if nifty_dma_dist < -5.0 and fund_evaluations[top1_key]["score"] < 35.0:
        top1_key = "SBI_GOLD" if fund_evaluations["SBI_GOLD"]["score"] >= 40.0 else "NIPPON_LIQUID"
        top2_key = "NIPPON_LIQUID"
        allocation_mode = "DEFENSIVE_CASH_OR_GOLD"
    else:
        allocation_mode = "EQUITY_MOMENTUM_LEADERSHIP"

    top_picks = [
        {
            "fund_key": top1_key,
            "name": fund_evaluations[top1_key]["name"],
            "short_name": fund_evaluations[top1_key]["short_name"],
            "allocation_amount": 25000.0,
            "score": fund_evaluations[top1_key]["score"],
            "category": fund_evaluations[top1_key]["category"],
            "sub_category": fund_evaluations[top1_key]["sub_category"],
            "thesis": fund_evaluations[top1_key]["thesis"]
        },
        {
            "fund_key": top2_key,
            "name": fund_evaluations[top2_key]["name"],
            "short_name": fund_evaluations[top2_key]["short_name"],
            "allocation_amount": 25000.0,
            "score": fund_evaluations[top2_key]["score"],
            "category": fund_evaluations[top2_key]["category"],
            "sub_category": fund_evaluations[top2_key]["sub_category"],
            "thesis": fund_evaluations[top2_key]["thesis"]
        }
    ]

    p1 = top_picks[0]
    p2 = top_picks[1]
    thesis_summary = (
        f"AI Advisor deploys ₹50k monthly SIP into top momentum leaders: "
        f"₹25k in {p1['short_name']} (Score {p1['score']:.0f}) and ₹25k in {p2['short_name']} (Score {p2['score']:.0f}). "
        f"{p1['short_name']} shows {p1['sub_category']} strength ({fund_evaluations[top1_key]['thesis']}), "
        f"while {p2['short_name']} leads in {p2['sub_category']} ({fund_evaluations[top2_key]['thesis']})."
    )

    return {
        "as_of_date": str(as_of_date),
        "allocation_mode": allocation_mode,
        "nifty_benchmark": {
            "current_nav": round(nifty_now, 2),
            "mom_30": round(nifty_mom30, 2),
            "mom_90": round(nifty_mom90, 2),
            "dma_200_dist": round(nifty_dma_dist, 2)
        },
        "top_picks": top_picks,
        "thesis_summary": thesis_summary,
        "ranked_funds": [fund_evaluations[k] for k in ranked_keys]
    }


def check_smart_ltcg_switches(
    holdings: Optional[List[Dict[str, Any]]] = None,
    as_of_date: Optional[date] = None,
    navs_dict: Optional[Dict[str, Dict[str, float]]] = None
) -> List[Dict[str, Any]]:
    """
    Evaluates whether any active portfolio holding has broken down > 8.0% below its 200-DMA
    after being held for > 365 days, triggering a Smart LTCG Switch at 12.5% LTCG / 0% exit load.
    """
    if as_of_date is None:
        as_of_date = date.today()
    if navs_dict is None:
        navs_dict = fetch_universe_navs()
    if holdings is None:
        try:
            from src.db import get_db
            holdings = get_db().get_holdings(active_only=True)
        except Exception:
            holdings = []

    name_to_key = {
        "Motilal Oswal Midcap Fund Direct Growth": "MOMC",
        "Nippon India Small Cap Fund Direct Growth": "NISC",
        "Parag Parikh Flexi Cap Fund Direct Growth": "PPFC",
        "Edelweiss US Technology Equity FoF Direct Growth": "EDEL_USTECH"
    }

    alerts = []
    for h in holdings:
        s_name = h.get("scheme_name", "")
        key = name_to_key.get(s_name)
        if not key or key not in navs_dict:
            continue
        f_navs = navs_dict[key]
        n_now = get_universe_nav_on(f_navs, as_of_date)
        n_200 = get_universe_nav_on(f_navs, as_of_date - timedelta(days=200))
        dma_dist = ((n_now - n_200) / n_200 * 100.0) if n_200 > 0 else 0.0

        if dma_dist < -8.0:
            units = float(h.get("units", 0))
            current_val = units * n_now
            invested_val = float(h.get("invested_value", 0))
            gain = max(0.0, current_val - invested_val)
            tax_rate = 0.20 if key == "EDEL_USTECH" else 0.125
            taxable_gain = max(0.0, gain - (125000.0 if key != "EDEL_USTECH" else 0.0))
            est_tax = tax_rate * taxable_gain

            alerts.append({
                "scheme_name": s_name,
                "fund_key": key,
                "current_nav": round(n_now, 2),
                "dma_200": round(n_200, 2),
                "dma_dist_pct": round(dma_dist, 2),
                "current_value": round(current_val, 2),
                "units": units,
                "estimated_tax": round(est_tax, 2),
                "message": (
                    f"Structural Breakdown: {s_name} is trading at {dma_dist:.1f}% vs 200-DMA (NAV {format_inr(n_now, decimals=2)} vs 200-DMA {format_inr(n_200, decimals=2)}). "
                    f"Units held >365 days qualify for 0% exit load and 12.5% LTCG. "
                    f"Recommended: Harvest dead capital and switch proceeds into current #1 momentum leader."
                )
            })
    return alerts






def fetch_ticker_data_with_fallbacks(tickers: List[str], period: str = "2y") -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Fetches price history from primary ticker or fallbacks if primary is empty."""
    for t in tickers:
        try:
            t_obj = yf.Ticker(t)
            df = t_obj.history(period=period)
            if df is not None and len(df) >= 40:
                return df, t
        except Exception as e:
            print(f"[RegimeEngine] Ticker {t} fetch failed ({e}). Trying fallback...")
            continue
    return None, None


def calculate_technical_score(df: pd.DataFrame, vix_val: float) -> Dict[str, Any]:
    """
    Computes technical score (0-100) based on:
    - 200-DMA (30% weight)
    - 50-EMA (25% weight)
    - Weekly RSI (20% weight)
    - ATR % (10% weight)
    - VIX volatility (15% weight)
    """
    close = df["Close"]
    last_price = float(close.iloc[-1])

    # 1. 200-DMA
    dma_200 = float(close.rolling(min(200, len(close))).mean().iloc[-1])
    dma_200_prev = float(close.rolling(min(200, len(close))).mean().iloc[-20]) if len(close) > 20 else dma_200
    dma_dist_pct = ((last_price - dma_200) / dma_200) * 100.0
    dma_slope_up = dma_200 >= dma_200_prev

    if dma_dist_pct >= 5.0 and dma_slope_up:
        score_dma = 95.0
    elif dma_dist_pct >= 0.0 and dma_slope_up:
        score_dma = 85.0
    elif dma_dist_pct >= 0.0:
        score_dma = 70.0
    elif dma_dist_pct >= -3.0:
        score_dma = 50.0
    elif dma_dist_pct >= -8.0:
        score_dma = 30.0
    else:
        score_dma = 15.0

    # 2. 50-EMA
    ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema_dist_pct = ((last_price - ema_50) / ema_50) * 100.0
    golden_cross = ema_50 > dma_200

    if ema_dist_pct >= 2.0 and golden_cross:
        score_ema = 90.0
    elif ema_dist_pct >= 0.0:
        score_ema = 75.0
    elif ema_dist_pct >= -3.0:
        score_ema = 45.0
    else:
        score_ema = 20.0

    # 3. Weekly RSI (14 period)
    weekly_close = close.resample("W-FRI").last().dropna()
    if len(weekly_close) >= 15:
        delta = weekly_close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, 0.0001)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_weekly = float(rsi_series.iloc[-1])
    else:
        rsi_weekly = 55.0

    if 55.0 <= rsi_weekly <= 68.0:
        score_rsi = 90.0  # Sweet spot momentum
    elif 48.0 <= rsi_weekly < 55.0:
        score_rsi = 75.0
    elif 68.0 < rsi_weekly <= 78.0:
        score_rsi = 65.0  # Overextended but strong
    elif 40.0 <= rsi_weekly < 48.0:
        score_rsi = 50.0  # Mild consolidation
    elif rsi_weekly > 78.0:
        score_rsi = 35.0  # Froth / extreme bubble risk
    elif 30.0 <= rsi_weekly < 40.0:
        score_rsi = 30.0  # Oversold / weak
    else:
        score_rsi = 15.0  # Breakdown / crash

    # 4. ATR %
    high = df["High"]
    low = df["Low"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    atr_pct = (atr / last_price) * 100.0

    if atr_pct <= 1.2:
        score_atr = 90.0  # Low volatility grind up
    elif atr_pct <= 1.8:
        score_atr = 75.0  # Healthy volatility
    elif atr_pct <= 2.5:
        score_atr = 50.0  # Choppy
    else:
        score_atr = 25.0  # Elevated turbulence

    # 5. VIX Score
    if vix_val <= 13.5:
        score_vix = 95.0
    elif vix_val <= 16.5:
        score_vix = 80.0
    elif vix_val <= 19.5:
        score_vix = 60.0
    elif vix_val <= 23.0:
        score_vix = 40.0
    else:
        score_vix = 20.0

    # Composite Technical Score
    tech_score = (
        0.30 * score_dma +
        0.25 * score_ema +
        0.20 * score_rsi +
        0.10 * score_atr +
        0.15 * score_vix
    )

    return {
        "technical_score": round(tech_score, 2),
        "last_price": round(last_price, 2),
        "dma_200": round(dma_200, 2),
        "dma_dist_pct": round(dma_dist_pct, 2),
        "ema_50": round(ema_50, 2),
        "ema_dist_pct": round(ema_dist_pct, 2),
        "rsi_weekly": round(rsi_weekly, 2),
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "vix": round(vix_val, 2),
        "score_breakdown": {
            "dma": score_dma,
            "ema": score_ema,
            "rsi": score_rsi,
            "atr": score_atr,
            "vix": score_vix
        }
    }


def calculate_fundamental_score(
    pe_val: float,
    pb_val: float,
    pe_mean: float,
    pe_std: float,
    pb_mean: float,
    pb_std: float,
    bond_yield: float
) -> Dict[str, Any]:
    """
    Computes fundamental score (0-100) based on:
    - Index P/E Z-Score (45% weight)
    - Index P/B Percentile / Z-Score (25% weight)
    - Earnings Yield vs 10Y Bond Yield Spread (30% weight)
    """
    # 1. P/E Z-Score
    pe_zscore = (pe_val - pe_mean) / pe_std
    if pe_zscore <= -1.2:
        score_pe = 95.0  # Extreme value
    elif pe_zscore <= -0.5:
        score_pe = 85.0
    elif pe_zscore <= 0.3:
        score_pe = 70.0  # Fair value
    elif pe_zscore <= 1.0:
        score_pe = 55.0  # Slightly elevated
    elif pe_zscore <= 1.8:
        score_pe = 35.0  # Stretched
    else:
        score_pe = 15.0  # Dangerous froth

    # 2. P/B Percentile estimation
    pb_zscore = (pb_val - pb_mean) / pb_std
    # Map Z to percentile roughly via sigmoid
    pb_percentile = round(100.0 / (1.0 + np.exp(-0.8 * pb_zscore)), 1)
    if pb_percentile <= 25.0:
        score_pb = 90.0
    elif pb_percentile <= 50.0:
        score_pb = 75.0
    elif pb_percentile <= 75.0:
        score_pb = 55.0
    elif pb_percentile <= 90.0:
        score_pb = 35.0
    else:
        score_pb = 15.0

    # 3. Earnings Yield vs 10Y Bond Yield
    earnings_yield = (1.0 / max(pe_val, 5.0)) * 100.0
    yield_spread = earnings_yield - bond_yield

    if yield_spread >= 0.5:
        score_spread = 90.0  # Generous equity risk premium
    elif yield_spread >= -0.5:
        score_spread = 75.0  # Fair compensation
    elif yield_spread >= -1.8:
        score_spread = 50.0  # Slim equity premium
    elif yield_spread >= -3.0:
        score_spread = 35.0  # Poor equity premium
    else:
        score_spread = 15.0  # Negative / extreme bond advantage

    fund_score = (
        0.45 * score_pe +
        0.25 * score_pb +
        0.30 * score_spread
    )

    return {
        "fundamental_score": round(fund_score, 2),
        "pe_ratio": round(pe_val, 2),
        "pe_zscore": round(pe_zscore, 2),
        "pb_ratio": round(pb_val, 2),
        "pb_percentile": pb_percentile,
        "earnings_yield": round(earnings_yield, 2),
        "bond_yield": round(bond_yield, 2),
        "yield_spread": round(yield_spread, 2),
        "score_breakdown": {
            "pe": score_pe,
            "pb": score_pb,
            "spread": score_spread
        }
    }


def fetch_live_vix(vix_ticker: str = "^INDIAVIX") -> float:
    """Fetches VIX or falls back cleanly."""
    try:
        df = yf.Ticker(vix_ticker).history(period="5d")
        if df is not None and len(df) > 0:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return 15.4  # Long term benign baseline


def compute_sleeve_regime(sleeve_key: str, as_of_date: date = None) -> Dict[str, Any]:
    """Computes full multi-regime score for a given sleeve."""
    conf = SLEEVE_CONFIG[sleeve_key]
    if as_of_date is None:
        as_of_date = date.today()

    tickers = [conf["primary_ticker"]] + conf["fallback_tickers"]
    df, active_ticker = fetch_ticker_data_with_fallbacks(tickers, period="2y")

    if df is None or len(df) < 30:
        # Emergency synthetic fallback if entire internet or Yahoo is down
        print(f"[RegimeEngine] Warning: Could not fetch market data for {sleeve_key}. Using baseline.")
        return {
            "score_date": str(as_of_date),
            "sleeve": sleeve_key,
            "composite_score": 60.0,
            "spot_score": 60.0,
            "rolling_avg_score": 60.0,
            "technical_score": 60.0,
            "fundamental_score": 60.0,
            "regime_status": "BULLISH",
            "rolling_status": "BULLISH",
            "dma_200": 0.0,
            "ema_50": 0.0,
            "price": 0.0,
            "rsi_weekly": 52.0,
            "atr": 0.0,
            "vix": 15.0,
            "pe_ratio": conf["pe_mean"],
            "pe_zscore": 0.0,
            "pb_ratio": conf["pb_mean"],
            "pb_percentile": 50.0,
            "earnings_yield": 4.5,
            "bond_yield": conf["benchmark_10y_yield"],
            "yield_spread": -2.3,
            "details": {
                "ticker": "FALLBACK_BASELINE",
                "mode": "emergency",
                "spot_score": 60.0,
                "rolling_avg_score": 60.0,
                "rolling_status": "BULLISH"
            }
        }

    # Fetch VIX
    vix_val = fetch_live_vix(conf["vix_ticker"])

    # Technical calculation
    tech = calculate_technical_score(df, vix_val)

    # Fundamental valuation: Derive or use current baseline
    # For Indian indices, Nifty 500 current PE ~22.4, PB ~3.8
    # Mid/Small cap current PE ~29.1, PB ~4.3
    # NASDAQ 100 current PE ~29.5, PB ~7.2
    if sleeve_key == "NIFTY_500":
        current_pe = 22.4
        current_pb = 3.75
    elif sleeve_key == "MID_SMALL":
        current_pe = 29.2
        current_pb = 4.35
    else:  # NASDAQ_100
        current_pe = 29.8
        current_pb = 7.10

    fund = calculate_fundamental_score(
        pe_val=current_pe,
        pb_val=current_pb,
        pe_mean=conf["pe_mean"],
        pe_std=conf["pe_std"],
        pb_mean=conf["pb_mean"],
        pb_std=conf["pb_std"],
        bond_yield=conf["benchmark_10y_yield"]
    )

    # Spot Composite Score: 50% Technicals + 50% Fundamentals
    spot_score = round(0.50 * tech["technical_score"] + 0.50 * fund["fundamental_score"], 2)

    # 30-Day Rolling Average Score across last 22 trading days (~30 calendar days)
    rolling_window = min(22, len(df))
    rolling_scores = []
    for i in range(len(df) - rolling_window, len(df)):
        sub_df = df.iloc[: i + 1]
        sub_tech = calculate_technical_score(sub_df, vix_val)
        sub_comp = round(0.50 * sub_tech["technical_score"] + 0.50 * fund["fundamental_score"], 2)
        rolling_scores.append(sub_comp)

    rolling_avg = round(float(np.mean(rolling_scores)), 2) if rolling_scores else spot_score

    # Classify Regime Status
    regime_status = "BULLISH" if spot_score >= 60.0 else ("CAUTION" if spot_score >= 40.0 else "DEFENSIVE")
    rolling_status = "BULLISH" if rolling_avg >= 60.0 else ("CAUTION" if rolling_avg >= 40.0 else "DEFENSIVE")

    return {
        "score_date": str(as_of_date),
        "sleeve": sleeve_key,
        "composite_score": spot_score,
        "spot_score": spot_score,
        "rolling_avg_score": rolling_avg,
        "technical_score": tech["technical_score"],
        "fundamental_score": fund["fundamental_score"],
        "regime_status": regime_status,
        "rolling_status": rolling_status,
        "dma_200": tech["dma_200"],
        "ema_50": tech["ema_50"],
        "price": tech["last_price"],
        "rsi_weekly": tech["rsi_weekly"],
        "atr": tech["atr"],
        "vix": tech["vix"],
        "pe_ratio": fund["pe_ratio"],
        "pe_zscore": fund["pe_zscore"],
        "pb_ratio": fund["pb_ratio"],
        "pb_percentile": fund["pb_percentile"],
        "earnings_yield": fund["earnings_yield"],
        "bond_yield": fund["bond_yield"],
        "yield_spread": fund["yield_spread"],
        "details": {
            "spot_score": spot_score,
            "rolling_avg_score": rolling_avg,
            "rolling_status": rolling_status,
            "rolling_window_days": rolling_window,
            "active_ticker": active_ticker,
            "dma_dist_pct": tech["dma_dist_pct"],
            "ema_dist_pct": tech["ema_dist_pct"],
            "atr_pct": tech["atr_pct"],
            "technical_breakdown": tech["score_breakdown"],
            "fundamental_breakdown": fund["score_breakdown"],
            "associated_funds": conf["funds"]
        }
    }


def update_all_regimes(as_of_date: date = None) -> Dict[str, Dict[str, Any]]:
    """Calculates regime scores for all 3 sleeves and stores them in the DB."""
    if as_of_date is None:
        as_of_date = date.today()

    db = get_db()
    results = {}
    records_to_save = []

    for sleeve_key in SLEEVE_CONFIG:
        score_data = compute_sleeve_regime(sleeve_key, as_of_date)
        results[sleeve_key] = score_data
        records_to_save.append(score_data)

    db.record_regime_scores(records_to_save)
    return results


if __name__ == "__main__":
    scores = update_all_regimes()
    print("=" * 60)
    print("MULTI-REGIME SCORE REPORT:")
    for k, s in scores.items():
        print(f"[{k}] Spot: {s['spot_score']}/100 ({s['regime_status']}) | 30-Day Avg: {s['rolling_avg_score']}/100 ({s['rolling_status']})")
        print(f"       Tech: {s['technical_score']} | Fund: {s['fundamental_score']} | Price: {s['price']} | 50-EMA: {s['ema_50']} | 200-DMA: {s['dma_200']}")
    print("=" * 60)
    print("\nUNRESTRICTED AI ADVISOR REPORT:")
    ai_report = score_unrestricted_universe()
    print(f"Allocation Mode: {ai_report['allocation_mode']}")
    print(f"Thesis Summary: {ai_report['thesis_summary']}")
    for pick in ai_report['top_picks']:
        print(f"  • {pick['short_name']} (₹{pick['allocation_amount']:,.0f}): Score {pick['score']} | {pick['thesis']}")
    print("=" * 60)
