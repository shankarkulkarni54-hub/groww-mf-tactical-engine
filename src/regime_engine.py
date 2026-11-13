"""Multi-regime scoring engine combining 50% Technicals + 50% Fundamentals across 3 sleeves."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import date, datetime
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
            "technical_score": 60.0,
            "fundamental_score": 60.0,
            "regime_status": "BULLISH",
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
            "details": {"ticker": "FALLBACK_BASELINE", "mode": "emergency"}
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

    # Composite Score: 50% Technicals + 50% Fundamentals
    composite = round(0.50 * tech["technical_score"] + 0.50 * fund["fundamental_score"], 2)

    # Classify Regime Status
    if composite >= 60.0:
        regime_status = "BULLISH"
    elif composite >= 40.0:
        regime_status = "CAUTION"
    else:
        regime_status = "DEFENSIVE"

    return {
        "score_date": str(as_of_date),
        "sleeve": sleeve_key,
        "composite_score": composite,
        "technical_score": tech["technical_score"],
        "fundamental_score": fund["fundamental_score"],
        "regime_status": regime_status,
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
        print(f"[{k}] Composite: {s['composite_score']}/100 | Tech: {s['technical_score']} | Fund: {s['fundamental_score']} | Status: {s['regime_status']}")
        print(f"       Price: {s['price']} | 50-EMA: {s['ema_50']} | 200-DMA: {s['dma_200']} | RSI: {s['rsi_weekly']} | VIX: {s['vix']}")
    print("=" * 60)
