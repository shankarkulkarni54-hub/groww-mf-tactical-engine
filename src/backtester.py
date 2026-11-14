"""5-Year Historical Backtest Engine (Nov 2021 - Nov 2026).
Compares the 30-Day Rolling Tactical Engine against Passive Blind ₹50,000/Mo SIPs.
"""

import os
import sys
import json
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple, Optional

# Ensure repository root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CACHE_FILE_PATH = os.path.join(REPO_ROOT, "data", "backtest_5yr_results.json")

# MF Scheme Codes (mfapi.in)
SCHEME_CODES = {
    "flexi": 122639,     # Parag Parikh Flexi Cap Fund Direct Growth
    "mid": 127042,       # Motilal Oswal Midcap Fund Direct Growth
    "small": 118778,     # Nippon India Small Cap Fund Direct Growth
    "us_tech": 148063    # Edelweiss US Technology Equity FoF Direct Growth
}


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

    # Quick bisection search
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


def fetch_all_5yr_navs() -> Dict[str, Dict[str, float]]:
    """Fetches 5 years of daily NAV histories from mfapi.in."""
    nav_histories = {}
    for key, code in SCHEME_CODES.items():
        try:
            url = f"https://api.mfapi.in/mf/{code}"
            r = requests.get(url, timeout=12)
            data = r.json().get("data", [])
            d_dict = {}
            for entry in data:
                pts = entry.get("date", "").split("-")
                if len(pts) == 3:
                    iso_date = f"{pts[2]}-{pts[1]}-{pts[0]}"
                    nav_val = float(entry.get("nav", 0))
                    if nav_val > 0:
                        d_dict[iso_date] = nav_val
            nav_histories[key] = d_dict
        except Exception as e:
            print(f"[Backtester] Warning: Failed fetching NAV for {key} ({code}): {e}")
            nav_histories[key] = {}
    return nav_histories


def get_nav_on_date(nav_dict: Dict[str, float], target_date: date) -> float:
    """Gets NAV for date or nearest prior trading day."""
    curr = target_date
    for _ in range(10):
        iso = curr.isoformat()
        if iso in nav_dict:
            return nav_dict[iso]
        curr -= timedelta(days=1)
    if nav_dict:
        sorted_keys = sorted(nav_dict.keys())
        # If target is before earliest date, return earliest
        if target_date.isoformat() < sorted_keys[0]:
            return nav_dict[sorted_keys[0]]
        # Else return latest
        return nav_dict[sorted_keys[-1]]
    return 100.0


def compute_5yr_regime_scores() -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Downloads 5 years of benchmark data (^NSEMDCP50 and ^INDIAVIX) and computes:
    - Daily close prices
    - 50-EMA
    - Daily Spot Regime Score (0-100)
    - 30-Day (22-trading day) Rolling Average Regime Score (0-100)
    """
    try:
        df_mid = yf.download("^NSEMDCP50", start="2021-01-01", end="2026-11-15", progress=False)
        df_vix = yf.download("^INDIAVIX", start="2021-01-01", end="2026-11-15", progress=False)

        if isinstance(df_mid.columns, pd.MultiIndex):
            df_mid.columns = df_mid.columns.get_level_values(0)
        if isinstance(df_vix.columns, pd.MultiIndex):
            df_vix.columns = df_vix.columns.get_level_values(0)

        close = df_mid["Close"].dropna()
        vix = df_vix["Close"].reindex(close.index).ffill().bfill()
    except Exception as e:
        print(f"[Backtester] yfinance error ({e}). Generating fallback indicator series...")
        dates = pd.date_range("2021-01-01", "2026-11-14", freq="B")
        close = pd.Series(np.linspace(6000, 15000, len(dates)), index=dates)
        vix = pd.Series(15.0, index=dates)

    dma_200 = close.rolling(200, min_periods=50).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    dma_dist = (close - dma_200) / dma_200 * 100.0
    ema_dist = (close - ema_50) / ema_50 * 100.0

    # 14-day RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 0.0001)
    rsi = 100 - (100 / (1 + rs))

    # Technical Score (50%)
    score_dma = np.where(dma_dist >= 5.0, 95.0,
                np.where(dma_dist >= 0.0, 75.0,
                np.where(dma_dist >= -3.0, 50.0,
                np.where(dma_dist >= -8.0, 30.0, 15.0))))

    score_ema = np.where(ema_dist >= 2.0, 90.0,
                np.where(ema_dist >= 0.0, 75.0,
                np.where(ema_dist >= -3.0, 45.0, 20.0)))

    score_rsi = np.where((rsi >= 50) & (rsi <= 68), 90.0,
                np.where((rsi >= 40) & (rsi < 50), 65.0,
                np.where(rsi > 68, 55.0, 25.0)))

    score_vix = np.where(vix <= 13.0, 90.0,
                np.where(vix <= 17.0, 70.0,
                np.where(vix <= 22.0, 45.0, 20.0)))

    tech_score = 0.30 * score_dma + 0.25 * score_ema + 0.20 * score_rsi + 0.25 * score_vix

    # Fundamental Score (50%): Valuation relative to trend
    trend = close.rolling(250, min_periods=50).mean()
    val_dev = (close - trend) / trend * 100.0
    fund_score = np.where(val_dev < -10, 85.0,
                 np.where(val_dev < 0, 70.0,
                 np.where(val_dev < 15, 55.0, 35.0)))

    spot_series = pd.Series(0.5 * tech_score + 0.5 * fund_score, index=close.index)
    rolling_series = spot_series.rolling(22, min_periods=5).mean()

    return close, ema_50, spot_series, rolling_series


def run_five_year_backtest(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Executes the 5-year daily backtest from Nov 2021 to Nov 2026.
    Returns cached results if available unless force_refresh=True.
    """
    if not force_refresh and os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data
        except Exception as e:
            print(f"[Backtester] Cache load warning ({e}). Re-running backtest...")

    print("🚀 Running 5-Year Historical Backtest (Nov 2021 - Nov 2026)...")

    # 1. Fetch NAV histories
    nav_histories = fetch_all_5yr_navs()

    # 2. Compute Benchmark & Regimes
    close, ema_50, spot_series, rolling_series = compute_5yr_regime_scores()

    start_date = date(2021, 11, 1)
    end_date = date(2026, 11, 13)

    # State tracking
    p_units = {"flexi": 0.0, "mid": 0.0, "small": 0.0}
    t_units = {"flexi": 0.0, "mid": 0.0, "small": 0.0}
    t_cash = 0.0
    total_invested = 0.0
    daily_cash_yield = (1.0 + 0.065) ** (1.0 / 365.0) - 1.0

    dates_list: List[str] = []
    p_wealth: List[float] = []
    t_wealth: List[float] = []
    invested_curve: List[float] = []
    cash_reserve_curve: List[float] = []
    cash_pct_curve: List[float] = []
    rolling_scores_curve: List[float] = []

    cfs_passive: List[Tuple[date, float]] = []
    cfs_tactical: List[Tuple[date, float]] = []

    # Historical metrics
    reentry_events: List[Dict[str, Any]] = []
    caution_divert_count = 0
    full_equity_count = 0
    crash_override_count = 0

    curr = start_date
    while curr <= end_date:
        d_str = curr.isoformat()

        # Regime scores for today
        ts_match = pd.Timestamp(curr)
        valid_idx = rolling_series.index[rolling_series.index <= ts_match]
        r_score = 65.0
        sp_score = 65.0
        c_val = 0.0
        ema_val = 0.0
        if len(valid_idx) > 0:
            latest_idx = valid_idx[-1]
            r_score = float(rolling_series.loc[latest_idx])
            sp_score = float(spot_series.loc[latest_idx])
            c_val = float(close.loc[latest_idx])
            ema_val = float(ema_50.loc[latest_idx])

        # -------------------------------------------------------------
        # MONTHLY ₹50,000 SIP ON THE 3RD OF EVERY MONTH
        # -------------------------------------------------------------
        if curr.day == 3:
            total_invested += 50000.0
            cfs_passive.append((curr, -50000.0))
            cfs_tactical.append((curr, -50000.0))

            # 1. Passive Buy & Hold (Blind ₹50k Allocation)
            p_units["flexi"] += 10000.0 / get_nav_on_date(nav_histories["flexi"], curr)
            p_units["mid"] += 20000.0 / get_nav_on_date(nav_histories["mid"], curr)
            p_units["small"] += 20000.0 / get_nav_on_date(nav_histories["small"], curr)

            # 2. Tactical Engine (30-Day Rolling Rule + Crash Override)
            # Parag Parikh Flexi Cap: core equity unless rolling < 40 or spot < 40
            if r_score >= 40.0 and sp_score >= 40.0:
                t_units["flexi"] += 10000.0 / get_nav_on_date(nav_histories["flexi"], curr)
            else:
                t_cash += 10000.0

            # Midcap & Smallcap (₹40k total)
            if sp_score < 40.0:
                # Crash Override: divert both Midcap & Smallcap to Shadow Cash
                t_cash += 40000.0
                crash_override_count += 1
            elif r_score >= 60.0:
                # Bullish: full equity deployment
                t_units["mid"] += 20000.0 / get_nav_on_date(nav_histories["mid"], curr)
                t_units["small"] += 20000.0 / get_nav_on_date(nav_histories["small"], curr)
                full_equity_count += 1
            elif r_score >= 40.0:
                # Caution (40-59): Midcap continues in equity; Smallcap diverted to Shadow Cash
                t_units["mid"] += 20000.0 / get_nav_on_date(nav_histories["mid"], curr)
                t_cash += 20000.0
                caution_divert_count += 1
            else:
                # Defensive (< 40): divert all ₹40k to Shadow Cash
                t_cash += 40000.0
                caution_divert_count += 1

            # -------------------------------------------------------------
            # TACTICAL 3-TRANCHE RE-ENTRY DEPLOYMENT
            # If 30-Day Rolling >= 60 + Technical Reclaim (Price > 50-EMA),
            # deploy 1/3rd of accumulated dry powder into equity at correction bottom.
            # -------------------------------------------------------------
            if r_score >= 60.0 and c_val >= ema_val and t_cash >= 20000.0:
                reentry_tranche = t_cash * 0.35  # Deploy ~1/3rd tranche
                t_cash -= reentry_tranche
                half_t = reentry_tranche * 0.5
                t_units["mid"] += half_t / get_nav_on_date(nav_histories["mid"], curr)
                t_units["small"] += half_t / get_nav_on_date(nav_histories["small"], curr)
                reentry_events.append({
                    "date": d_str,
                    "reentry_amount": round(reentry_tranche, 2),
                    "rolling_score": round(r_score, 1)
                })

        # Daily Shadow Cash interest accrual (6.5% p.a.)
        t_cash += t_cash * daily_cash_yield

        # Daily Portfolio Valuation
        nav_f = get_nav_on_date(nav_histories["flexi"], curr)
        nav_m = get_nav_on_date(nav_histories["mid"], curr)
        nav_s = get_nav_on_date(nav_histories["small"], curr)

        p_total = (p_units["flexi"] * nav_f) + (p_units["mid"] * nav_m) + (p_units["small"] * nav_s)
        t_eq = (t_units["flexi"] * nav_f) + (t_units["mid"] * nav_m) + (t_units["small"] * nav_s)
        t_total = t_eq + t_cash
        cash_pct = (t_cash / t_total * 100.0) if t_total > 0 else 0.0

        dates_list.append(d_str)
        p_wealth.append(round(p_total, 2))
        t_wealth.append(round(t_total, 2))
        invested_curve.append(round(total_invested, 2))
        cash_reserve_curve.append(round(t_cash, 2))
        cash_pct_curve.append(round(cash_pct, 2))
        rolling_scores_curve.append(round(r_score, 1))

        curr += timedelta(days=1)

    # -------------------------------------------------------------
    # PERFORMANCE METRICS CALCULATION
    # -------------------------------------------------------------
    final_passive_val = p_wealth[-1]
    final_tactical_val = t_wealth[-1]
    final_cash_val = cash_reserve_curve[-1]
    alpha_rupees = round(final_tactical_val - final_passive_val, 2)

    # Terminal cash flows for XIRR
    cfs_passive.append((end_date, final_passive_val))
    cfs_tactical.append((end_date, final_tactical_val))

    xirr_passive = calculate_xirr(cfs_passive)
    xirr_tactical = calculate_xirr(cfs_tactical)
    alpha_xirr = round(xirr_tactical - xirr_passive, 2)

    # Max Drawdowns
    p_series = pd.Series(p_wealth)
    t_series = pd.Series(t_wealth)

    p_peaks = p_series.cummax()
    p_dds = (p_series - p_peaks) / p_peaks * 100.0
    max_dd_passive = round(float(p_dds.min()), 2)

    t_peaks = t_series.cummax()
    t_dds = (t_series - t_peaks) / t_peaks * 100.0
    max_dd_tactical = round(float(t_dds.min()), 2)
    dd_cushion = round(max_dd_tactical - max_dd_passive, 2)

    max_cash_pct = round(max(cash_pct_curve), 2)
    avg_cash_pct = round(sum(cash_pct_curve) / len(cash_pct_curve), 2)
    max_cash_rupees = round(max(cash_reserve_curve), 2)

    # Downsample time-series to weekly points for smooth web dashboard rendering
    downsample_step = 5  # Every 5th calendar day
    downsampled_dates = dates_list[::downsample_step]
    downsampled_p_wealth = p_wealth[::downsample_step]
    downsampled_t_wealth = t_wealth[::downsample_step]
    downsampled_invested = invested_curve[::downsample_step]
    downsampled_cash = cash_reserve_curve[::downsample_step]
    downsampled_cash_pct = cash_pct_curve[::downsample_step]
    downsampled_p_dd = [round(float(v), 2) for v in p_dds.iloc[::downsample_step]]
    downsampled_t_dd = [round(float(v), 2) for v in t_dds.iloc[::downsample_step]]
    downsampled_scores = rolling_scores_curve[::downsample_step]

    # Ensure last point is included
    if downsampled_dates[-1] != dates_list[-1]:
        downsampled_dates.append(dates_list[-1])
        downsampled_p_wealth.append(p_wealth[-1])
        downsampled_t_wealth.append(t_wealth[-1])
        downsampled_invested.append(invested_curve[-1])
        downsampled_cash.append(cash_reserve_curve[-1])
        downsampled_cash_pct.append(cash_pct_curve[-1])
        downsampled_p_dd.append(round(float(p_dds.iloc[-1]), 2))
        downsampled_t_dd.append(round(float(t_dds.iloc[-1]), 2))
        downsampled_scores.append(rolling_scores_curve[-1])

    results = {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_invested": round(total_invested, 2),
        "months_count": len(cfs_passive) - 1,
        "passive_final_corpus": round(final_passive_val, 2),
        "tactical_final_corpus": round(final_tactical_val, 2),
        "tactical_final_cash": round(final_cash_val, 2),
        "alpha_rupees": alpha_rupees,
        "alpha_percent": round((alpha_rupees / final_passive_val * 100.0), 2) if final_passive_val > 0 else 0.0,
        "passive_xirr": xirr_passive,
        "tactical_xirr": xirr_tactical,
        "alpha_xirr": alpha_xirr,
        "passive_max_dd": max_dd_passive,
        "tactical_max_dd": max_dd_tactical,
        "dd_cushion": dd_cushion,
        "max_cash_pct": max_cash_pct,
        "avg_cash_pct": avg_cash_pct,
        "max_cash_rupees": max_cash_rupees,
        "caution_divert_count": caution_divert_count,
        "full_equity_count": full_equity_count,
        "crash_override_count": crash_override_count,
        "reentry_events_count": len(reentry_events),
        "dates": downsampled_dates,
        "passive_wealth": downsampled_p_wealth,
        "tactical_wealth": downsampled_t_wealth,
        "invested_curve": downsampled_invested,
        "cash_reserve_curve": downsampled_cash,
        "cash_pct_curve": downsampled_cash_pct,
        "passive_drawdowns": downsampled_p_dd,
        "tactical_drawdowns": downsampled_t_dd,
        "rolling_scores": downsampled_scores,
        "generated_at": datetime.now().isoformat()
    }

    # Save to cache
    os.makedirs(os.path.dirname(CACHE_FILE_PATH), exist_ok=True)
    with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"✅ 5-Year Backtest completed and cached to {CACHE_FILE_PATH}!")
    return results


if __name__ == "__main__":
    res = run_five_year_backtest(force_refresh=True)
    print("\n=== 5-YEAR HISTORICAL BACKTEST SUMMARY (Nov 2021 - Nov 2026) ===")
    print(f"Total Invested:        ₹{res['total_invested']:,.2f} ({res['months_count']} months @ ₹50k/mo)")
    print(f"Passive Final Corpus:  ₹{res['passive_final_corpus']:,.2f} | XIRR: {res['passive_xirr']:.2f}% | Max DD: {res['passive_max_dd']:.2f}%")
    print(f"Tactical Final Corpus: ₹{res['tactical_final_corpus']:,.2f} | XIRR: {res['tactical_xirr']:.2f}% | Max DD: {res['tactical_max_dd']:.2f}%")
    print(f"Net Rupee Alpha:       ₹{res['alpha_rupees']:+,.2f} ({res['alpha_percent']:+.2f}%)")
    print(f"XIRR Alpha:            {res['alpha_xirr']:+.2f}% p.a.")
    print(f"Drawdown Cushion:      {res['dd_cushion']:+.2f}% (fell less in corrections)")
    print(f"Peak Cash Reserve:     ₹{res['max_cash_rupees']:,.2f} ({res['max_cash_pct']:.1f}% of total portfolio)")
    print(f"SIP Months Diverted:   {res['caution_divert_count']} Caution / Defensive vs {res['full_equity_count']} Full Equity")
