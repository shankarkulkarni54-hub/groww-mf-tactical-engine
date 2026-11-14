"""Mobile-first responsive Streamlit dashboard for Groww Mutual Fund Tactical Allocation Engine."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date
from src.db import get_db
from src.regime_engine import update_all_regimes, SLEEVE_CONFIG
from src.paper_ledger import evaluate_tactical_decisions, calculate_friction_and_drag
from src.telegram_bot import format_tactical_alert, send_telegram_alert

# Streamlit Page Config - Centered layout is optimal for mobile viewports
st.set_page_config(
    page_title="Tactical MF Engine",
    page_icon="🛡️",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom Mobile-First CSS
st.markdown("""
<style>
    /* Global Styles */
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 680px !important;
    }
    
    /* Sleek Cards */
    .metric-card {
        background: linear-gradient(135deg, #1E222D 0%, #262C3A 100%);
        border: 1px solid #363D4E;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    .metric-title {
        font-size: 0.82rem;
        font-weight: 500;
        color: #9AA0A6;
        margin-bottom: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-val {
        font-size: 1.55rem;
        font-weight: 700;
        color: #FFFFFF;
        line-height: 1.2;
    }
    .metric-sub {
        font-size: 0.85rem;
        margin-top: 4px;
    }
    .text-green { color: #00D09C !important; font-weight: 600; }
    .text-amber { color: #FFB020 !important; font-weight: 600; }
    .text-red { color: #FF5252 !important; font-weight: 600; }

    /* Action Banners */
    .banner-green {
        background: rgba(0, 208, 156, 0.12);
        border: 1px solid #00D09C;
        border-left: 6px solid #00D09C;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
    .banner-amber {
        background: rgba(255, 176, 32, 0.12);
        border: 1px solid #FFB020;
        border-left: 6px solid #FFB020;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
    .banner-red {
        background: rgba(255, 82, 82, 0.12);
        border: 1px solid #FF5252;
        border-left: 6px solid #FF5252;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }

    /* Fund Holding Card */
    .fund-card {
        background: #1A1F2B;
        border: 1px solid #2D3546;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 12px;
    }
    .fund-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #E8EAED;
        margin-bottom: 6px;
    }
    .fund-row {
        display: flex;
        justify-content: space-between;
        margin-top: 4px;
        font-size: 0.85rem;
    }
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.72rem;
        font-weight: 600;
    }
    .badge-locked {
        background: #3c4043;
        color: #bdc1c6;
    }
    .badge-sleeve {
        background: #1e3a8a;
        color: #93c5fd;
    }
    
    /* Responsive Buttons */
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        height: 44px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


def init_app():
    """Initializes and caches base state."""
    db = get_db()
    holdings = db.get_holdings(active_only=False)
    if not holdings:
        from src.ingest_groww import seed_holdings_to_db
        seed_holdings_to_db()
        holdings = db.get_holdings(active_only=False)

    scores = db.get_latest_regime_scores()
    if not scores:
        scores = update_all_regimes()

    snapshots = db.get_portfolio_snapshots(days=180)
    if not snapshots:
        from src.paper_ledger import simulate_six_months_dual_ledger
        simulate_six_months_dual_ledger()
        snapshots = db.get_portfolio_snapshots(days=180)

    return db, holdings, scores, snapshots


db, holdings, scores, snapshots = init_app()
active_holdings = [h for h in holdings if h.get("is_active")]
locked_holdings = [h for h in holdings if h.get("is_locked")]

latest_snap = snapshots[-1] if snapshots else {}
decisions = evaluate_tactical_decisions(scores)

# --- TOP MOBILE HEADER ---
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.markdown("### 🛡️ Tactical MF Engine")
    st.caption("Groww Holdings • ₹50,000/Mo SIP • Cloud Automated")
with col_head2:
    now_ist = datetime.now()
    cutoff_time = now_ist.replace(hour=15, minute=0, second=0, microsecond=0)
    if now_ist < cutoff_time:
        mins_left = int((cutoff_time - now_ist).total_seconds() / 60)
        st.markdown(f"<span class='badge' style='background:#1b4d3e; color:#5eead4;'>⏰ {mins_left}m to 3 PM</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='badge' style='background:#2a2e39; color:#9ca3af;'>Settled Today</span>", unsafe_allow_html=True)

# --- MONTHLY SIP ACTION GUIDE (3rd of Month) ---
is_outside_window = decisions.get("is_outside_sip_window", True)
has_emergency_switch = any(s.get("action") == "SWITCH_TO_CASH" for s in decisions.get("switch_signals", []))
is_action_window = decisions.get("is_sip_action_window", False)
is_execution_day = decisions.get("is_sip_execution_day", False)

if has_emergency_switch:
    badge_bg = "rgba(239, 68, 68, 0.18)"
    badge_fg = "#fca5a5"
    badge_border = "#ef4444"
    guide_border = "#ef4444"
    badge_text = "🚨 EMERGENCY ACTION REQUIRED: Corpus Switch Triggered"
elif is_action_window:
    badge_bg = "rgba(16, 185, 129, 0.18)"
    badge_fg = "#6ee7b7"
    badge_border = "#10b981"
    guide_border = "#10b981"
    badge_text = "⚡ ACTION WINDOW OPEN — Set Groww SIP Allocation for the 3rd"
elif is_execution_day:
    badge_bg = "rgba(245, 158, 11, 0.18)"
    badge_fg = "#fcd34d"
    badge_border = "#f59e0b"
    guide_border = "#f59e0b"
    badge_text = "📅 SIP EXECUTION DAY — Auto-debit Active on Groww"
else:
    badge_bg = "rgba(59, 130, 246, 0.15)"
    badge_fg = "#93c5fd"
    badge_border = "#3b82f6"
    guide_border = "#2563eb"
    badge_text = "🛡️ NO ACTION REQUIRED TODAY — Hold Existing Units"

tot_eq = decisions.get("total_sip_equity", 30000.0)
tot_cash = decisions.get("total_sip_cash", 20000.0)
sip_decs = decisions.get("sip_decisions", {})

st.markdown(f"""
<div class='metric-card' style='border: 1px solid {guide_border}; background: linear-gradient(135deg, #131d34 0%, #1a2544 100%); padding: 16px 18px; margin-bottom: 16px;'>
    <div style='display:flex; justify-content:space-between; align-items:center;'>
        <div style='font-size:1.02rem; font-weight:700; color:#FFFFFF;'>📅 Monthly SIP Action Guide (3rd of Month)</div>
        <span class='badge' style='background:#1e3a8a; color:#bfdbfe; font-size:0.75rem;'>₹50,000/Mo Total</span>
    </div>
    
    <div style='margin-top:10px; margin-bottom:12px;'>
        <div style='display:inline-block; background:{badge_bg}; color:{badge_fg}; border:1px solid {badge_border}; font-size:0.84rem; padding:5px 12px; border-radius:6px; font-weight:700;'>
            {badge_text}
        </div>
    </div>

    <div style='background:rgba(15, 23, 42, 0.65); border:1px solid #334155; border-radius:8px; padding:10px 12px; margin-bottom:12px;'>
        <div style='font-size:0.72rem; text-transform:uppercase; color:#94a3b8; font-weight:600; letter-spacing:0.5px;'>Next Action Window (Review & Set on Groww)</div>
        <div style='font-size:0.92rem; font-weight:600; color:#38bdf8; margin-top:2px;'>
            🗓️ {decisions.get('window_status_label')}
        </div>
    </div>

    <div>
        <div style='font-size:0.72rem; text-transform:uppercase; color:#94a3b8; font-weight:600; margin-bottom:8px;'>₹50k Allocation Split (Governed by 30-Day Rolling Score)</div>
        
        <div style='background:rgba(255,255,255,0.03); border-radius:6px; padding:8px 10px; margin-bottom:6px;'>
            <div style='display:flex; justify-content:space-between; font-size:0.86rem;'>
                <span><b>Parag Parikh Flexi Cap</b> (₹10k)</span>
                <span class='badge' style='background:{"#065f46" if sip_decs.get("Parag Parikh Flexi Cap Fund Direct Growth", {}).get("action") == "EQUITY" else "#78350f"}; color:{"#a7f3d0" if sip_decs.get("Parag Parikh Flexi Cap Fund Direct Growth", {}).get("action") == "EQUITY" else "#fde68a"};'>
                    {sip_decs.get("Parag Parikh Flexi Cap Fund Direct Growth", {}).get("action")} • ₹{sip_decs.get("Parag Parikh Flexi Cap Fund Direct Growth", {}).get("amount", 10000):,.0f}
                </span>
            </div>
            <div style='font-size:0.75rem; color:#94a3b8; margin-top:2px;'>{sip_decs.get("Parag Parikh Flexi Cap Fund Direct Growth", {}).get("reason", "")}</div>
        </div>

        <div style='background:rgba(255,255,255,0.03); border-radius:6px; padding:8px 10px; margin-bottom:6px;'>
            <div style='display:flex; justify-content:space-between; font-size:0.86rem;'>
                <span><b>Motilal Oswal Midcap</b> (₹20k)</span>
                <span class='badge' style='background:{"#065f46" if sip_decs.get("Motilal Oswal Midcap Fund Direct Growth", {}).get("action") == "EQUITY" else "#78350f"}; color:{"#a7f3d0" if sip_decs.get("Motilal Oswal Midcap Fund Direct Growth", {}).get("action") == "EQUITY" else "#fde68a"};'>
                    {sip_decs.get("Motilal Oswal Midcap Fund Direct Growth", {}).get("action")} • ₹{sip_decs.get("Motilal Oswal Midcap Fund Direct Growth", {}).get("amount", 20000):,.0f}
                </span>
            </div>
            <div style='font-size:0.75rem; color:#94a3b8; margin-top:2px;'>{sip_decs.get("Motilal Oswal Midcap Fund Direct Growth", {}).get("reason", "")}</div>
        </div>

        <div style='background:rgba(255,255,255,0.03); border-radius:6px; padding:8px 10px; margin-bottom:6px;'>
            <div style='display:flex; justify-content:space-between; font-size:0.86rem;'>
                <span><b>Nippon India Small Cap</b> (₹20k)</span>
                <span class='badge' style='background:{"#065f46" if sip_decs.get("Nippon India Small Cap Fund Direct Growth", {}).get("action") == "EQUITY" else "#78350f"}; color:{"#a7f3d0" if sip_decs.get("Nippon India Small Cap Fund Direct Growth", {}).get("action") == "EQUITY" else "#fde68a"};'>
                    {sip_decs.get("Nippon India Small Cap Fund Direct Growth", {}).get("action")} • ₹{sip_decs.get("Nippon India Small Cap Fund Direct Growth", {}).get("amount", 20000):,.0f}
                </span>
            </div>
            <div style='font-size:0.75rem; color:#94a3b8; margin-top:2px;'>{sip_decs.get("Nippon India Small Cap Fund Direct Growth", {}).get("reason", "")}</div>
        </div>

        <div style='display:flex; justify-content:space-between; font-weight:700; font-size:0.86rem; margin-top:10px; padding-top:8px; border-top:1px solid #334155;'>
            <span class='text-green'>🟢 Equity SIP: ₹{tot_eq:,.0f}</span>
            <span class='text-amber'>🟡 Liquid / Shadow Cash: ₹{tot_cash:,.0f}</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- TOP EXECUTIVE METRICS ---
tac_val = latest_snap.get("tactical_total_value", 0.0)
tac_cash = latest_snap.get("tactical_cash_value", 0.0)
tac_equity = tac_val - tac_cash
pas_val = latest_snap.get("passive_total_value", 0.0)
alpha_rs = latest_snap.get("alpha_rupees", 0.0)
alpha_pct = latest_snap.get("alpha_percent", 0.0)

cash_pct = (tac_cash / tac_val * 100.0) if tac_val > 0 else 0.0
eq_pct = 100.0 - cash_pct

m1, m2 = st.columns(2)
with m1:
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-title'>Tactical Net Worth (Ledger A)</div>
        <div class='metric-val'>₹{tac_val:,.0f}</div>
        <div class='metric-sub'>
            <span class='text-green'>{eq_pct:.1f}% Equity</span> • 
            <span class='text-amber'>{cash_pct:.1f}% Cash</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with m2:
    alpha_class = "text-green" if alpha_rs >= 0 else "text-red"
    alpha_sign = "+" if alpha_rs >= 0 else ""
    st.markdown(f"""
    <div class='metric-card'>
        <div class='metric-title'>Tactical Alpha vs Passive</div>
        <div class='metric-val {alpha_class}'>{alpha_sign}₹{alpha_rs:,.0f}</div>
        <div class='metric-sub'>
            <span class='{alpha_class}'>{alpha_sign}{alpha_pct:.2f}%</span> vs Buy & Hold (₹{pas_val:,.0f})
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- TABS FOR MOBILE NAVIGATION ---
tab_regimes, tab_holdings, tab_chart, tab_trades, tab_settings = st.tabs([
    "🎯 Regimes", "💼 Holdings", "📈 Alpha", "📝 Ledger", "⚙️ Actions"
])

# ==========================================
# TAB 1: MULTI-REGIME SCORES
# ==========================================
with tab_regimes:
    st.markdown("#### Market Regime Breakdown (0-100)")
    st.caption("50% Technicals (200-DMA, 50-EMA, RSI, ATR, VIX) + 50% Fundamentals (PE Z-score, PB, Yield Spread)")

    for sleeve_key, label in [
        ("NIFTY_500", "Nifty 500 (Parag Parikh Flexi Cap)"),
        ("MID_SMALL", "Mid & Small Cap (Motilal & Nippon)"),
        ("NASDAQ_100", "NASDAQ 100 (Edelweiss US Tech)")
    ]:
        s = scores.get(sleeve_key, {})
        spot = float(s.get("spot_score", s.get("composite_score", 50.0)))
        rolling = float(s.get("rolling_avg_score", s.get("composite_score", 50.0)))
        tech = float(s.get("technical_score", 50.0))
        fund = float(s.get("fundamental_score", 50.0))
        spot_status = s.get("regime_status", "NEUTRAL")
        rolling_status = s.get("rolling_status", "NEUTRAL")

        badge_color = "#00D09C" if rolling_status == "BULLISH" else ("#FFB020" if rolling_status == "CAUTION" else "#FF5252")
        spot_color = "#00D09C" if spot_status == "BULLISH" else ("#FFB020" if spot_status == "CAUTION" else "#FF5252")
        dma_dist = s.get("details", {}).get("dma_dist_pct", 0.0)
        rsi = s.get("rsi_weekly", 50.0)
        vix = s.get("vix", 15.0)
        pe_z = s.get("pe_zscore", 0.0)

        st.markdown(f"""
        <div class='fund-card' style='border-left: 4px solid {badge_color};'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <span class='fund-title'>{label}</span>
                <span class='badge' style='background:{badge_color}; color:#111;'>30-Day Avg: {rolling:.1f} • {rolling_status}</span>
            </div>
            
            <div style='display:grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top:10px; background:rgba(0,0,0,0.22); padding:8px 10px; border-radius:6px; border:1px solid #2d3748;'>
                <div>
                    <div style='font-size:0.70rem; color:#94a3b8; text-transform:uppercase; font-weight:600;'>30-Day Rolling Avg</div>
                    <div style='font-size:1.15rem; font-weight:700; color:{badge_color};'>{rolling:.1f}/100</div>
                    <div style='font-size:0.68rem; color:#cbd5e1;'>Governs 3rd SIP Decision</div>
                </div>
                <div style='border-left:1px solid #334155; padding-left:10px;'>
                    <div style='font-size:0.70rem; color:#94a3b8; text-transform:uppercase; font-weight:600;'>Today's Spot Score</div>
                    <div style='font-size:1.15rem; font-weight:700; color:{spot_color};'>{spot:.1f}/100</div>
                    <div style='font-size:0.68rem; color:#cbd5e1;'>Governs Crash De-risking</div>
                </div>
            </div>

            <div style='margin-top:8px;'>
                <div style='display:flex; justify-content:space-between; font-size:0.78rem; color:#9AA0A6;'>
                    <span>Technical Score: <b>{tech:.1f}</b></span>
                    <span>Fundamental Score: <b>{fund:.1f}</b></span>
                </div>
                <div style='background:#2D3546; border-radius:4px; height:5px; margin:5px 0; overflow:hidden;'>
                    <div style='background:{badge_color}; width:{min(100.0, max(0.0, rolling))}%; height:100%;'></div>
                </div>
            </div>
            <div class='fund-row' style='color:#bdc1c6; font-size:0.78rem; margin-top:4px;'>
                <span>200-DMA: <b>{dma_dist:+.1f}%</b></span>
                <span>RSI (W): <b>{rsi:.1f}</b></span>
                <span>VIX: <b>{vix:.1f}</b></span>
                <span>P/E Z-Score: <b>{pe_z:+.2f}</b></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Tactical Rules Reference Card
    with st.expander("ℹ️ Tactical Friction & Re-entry Rules", expanded=False):
        st.markdown("""
        - **Tier 1 (3rd-of-Month SIP Allocation)**:
          * Based on **30-Day Rolling Average Score** (buffers against daily whipsaws).
          * **30-Day Avg >= 60**: Full ₹50k equity SIPs.
          * **30-Day Avg 40-59**: Divert ₹20k Smallcap SIP to Shadow Cash (~6.5% p.a.); Flexi Cap and Midcap continue in equity.
          * **30-Day Avg < 40**: Divert all ₹50k SIPs to Shadow Cash.
          * **Crash Override**: If today's Spot Score drops sharply below 40, immediately route to Shadow Cash.
        - **Tier 2 (Emergency Corpus Switch < 30)**:
          * Evaluated on **Spot Score** so genuine crashes aren't delayed.
          * Switch to Cash **ONLY** if Spot Score < 30 **AND** Expected Drawdown > Exit Load + STCG/LTCG Tax.
        - **Re-entry in 3 Tranches**:
          * Deploying parked cash tranches requires **30-Day Average Score >= 60** PLUS technical reclaim (Price > 50-EMA / 200-DMA).
        """)

# ==========================================
# TAB 2: ACTIVE TRADABLE HOLDINGS
# ==========================================
with tab_holdings:
    st.markdown("#### Active Tradable Universe (4 Funds)")
    st.caption("Locked ELSS holdings excluded from tactical switching.")

    for h in active_holdings:
        name = h.get("scheme_name", "")
        units = float(h.get("units", 0))
        nav = float(h.get("current_nav", 0))
        curr_val = float(h.get("current_value", 0))
        inv_val = float(h.get("invested_value", 0))
        gain = curr_val - inv_val
        gain_pct = (gain / inv_val * 100.0) if inv_val > 0 else 0.0
        sip_amt = float(h.get("sip_amount", 0))

        friction = calculate_friction_and_drag(name, units, nav, inv_val, holding_days=380)

        gain_color = "text-green" if gain >= 0 else "text-red"
        gain_sign = "+" if gain >= 0 else ""

        st.markdown(f"""
        <div class='fund-card'>
            <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div>
                    <div class='fund-title'>{name}</div>
                    <span class='badge badge-sleeve'>{h.get('sleeve')}</span>
                    <span class='badge' style='background:#1e293b; color:#cbd5e1;'>Folio: {h.get('folio_no')}</span>
                </div>
                <div style='text-align:right;'>
                    <div style='font-size:1.1rem; font-weight:700;'>₹{curr_val:,.2f}</div>
                    <div class='{gain_color}' style='font-size:0.82rem;'>{gain_sign}₹{gain:,.2f} ({gain_sign}{gain_pct:.1f}%)</div>
                </div>
            </div>
            <div style='margin-top:10px; border-top:1px solid #2D3546; padding-top:8px;'>
                <div class='fund-row'>
                    <span style='color:#9ca3af;'>Units & NAV:</span>
                    <span><b>{units:,.3f}</b> @ <b>₹{nav:.2f}</b></span>
                </div>
                <div class='fund-row'>
                    <span style='color:#9ca3af;'>Invested Value:</span>
                    <span>₹{inv_val:,.2f}</span>
                </div>
                <div class='fund-row'>
                    <span style='color:#9ca3af;'>Monthly SIP (3rd):</span>
                    <span><b>{"₹{:,.0f}".format(sip_amt) if sip_amt > 0 else "None (Hold Only)"}</b></span>
                </div>
                <div class='fund-row'>
                    <span style='color:#9ca3af;'>Exit Load & Tax Drag:</span>
                    <span>Load: <b>{friction['load_pct']}%</b> | Tax: <b>₹{friction['stcg_tax'] + friction['ltcg_tax']:,.0f}</b> ({friction['friction_drag_pct']:.1f}%)</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Excluded Locked Funds Section
    if locked_holdings:
        st.markdown("#### 🔒 Excluded Locked Holdings")
        st.caption("Preserved in portfolio view, strictly excluded from tactical allocation & de-risking.")
        for l in locked_holdings:
            l_curr = float(l.get("current_value", 0))
            l_inv = float(l.get("invested_value", 0))
            l_units = float(l.get("units", 0))
            st.markdown(f"""
            <div class='fund-card' style='opacity:0.8; background:#181c24;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <div>
                        <div style='font-weight:600; font-size:0.9rem;'>🔒 {l.get('scheme_name')}</div>
                        <span class='badge badge-locked'>ELSS 3-Year Lock-in</span>
                    </div>
                    <div style='text-align:right;'>
                        <div style='font-weight:700;'>₹{l_curr:,.2f}</div>
                        <div style='font-size:0.78rem; color:#9ca3af;'>{l_units:,.2f} Units</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ==========================================
# TAB 3: DUAL LEDGER ALPHA CHART
# ==========================================
with tab_chart:
    st.markdown("#### 6-Month Performance Comparison")
    st.caption("Ledger A (Tactical Post-Tax Engine) vs Ledger B (Passive Buy & Hold)")

    if snapshots:
        df_snap = pd.DataFrame(snapshots)
        df_snap["Date"] = pd.to_datetime(df_snap["snapshot_date"])

        # ==========================================
        # CHART 1: PORTFOLIO VALUE COMPARISON
        # ==========================================
        st.markdown("<div style='font-size:0.92rem; font-weight:700; color:#E2E8F0; margin-bottom:4px;'>📊 1. Portfolio Value Comparison: Tactical vs. Passive</div>", unsafe_allow_html=True)
        
        all_vals = pd.concat([df_snap["tactical_total_value"], df_snap["passive_total_value"]]).dropna()
        y_min = float(all_vals.min()) * 0.98
        y_max = float(all_vals.max()) * 1.02

        fig1 = go.Figure()

        # Tactical Total Line (Solid Green)
        fig1.add_trace(go.Scatter(
            x=df_snap["Date"],
            y=df_snap["tactical_total_value"],
            mode="lines",
            name="Tactical Engine (Total)",
            line=dict(color="#00D09C", width=2.8),
            hovertemplate="Tactical Total: ₹%{y:,.0f}<extra></extra>"
        ))

        # Passive Buy & Hold (Dashed White/Amber Line)
        fig1.add_trace(go.Scatter(
            x=df_snap["Date"],
            y=df_snap["passive_total_value"],
            mode="lines",
            name="Passive Buy & Hold",
            line=dict(color="#F8FAFC", width=2.2, dash="dash"),
            hovertemplate="Passive Buy & Hold: ₹%{y:,.0f}<extra></extra>"
        ))

        fig1.update_layout(
            template="plotly_dark",
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            margin=dict(l=10, r=10, t=10, b=10),
            height=280,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5,
                font=dict(size=10)
            ),
            hovermode="x unified",
            yaxis=dict(
                range=[y_min, y_max],
                showgrid=True,
                gridcolor="#232733",
                tickprefix="₹",
                tickformat=","
            ),
            xaxis=dict(showgrid=False)
        )
        st.plotly_chart(fig1, use_container_width=True)

        # ==========================================
        # CHART 2: NET ALPHA & SHADOW CASH
        # ==========================================
        st.markdown("<div style='font-size:0.92rem; font-weight:700; color:#E2E8F0; margin-top:14px; margin-bottom:4px;'>💰 2. Daily Rupee Alpha (₹) & Shadow Cash Reserve</div>", unsafe_allow_html=True)
        
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])

        # Bar chart for Daily Rupee Alpha
        fig2.add_trace(
            go.Bar(
                x=df_snap["Date"],
                y=df_snap["alpha_rupees"],
                name="Net Alpha (₹)",
                marker_color="#00D09C",
                hovertemplate="Net Alpha: ₹%{y:+,.2f}<extra></extra>"
            ),
            secondary_y=False
        )

        # Area chart for Shadow Cash Reserve
        max_cash = float(df_snap["tactical_cash_value"].max()) if not df_snap.empty else 10000.0
        fig2.add_trace(
            go.Scatter(
                x=df_snap["Date"],
                y=df_snap["tactical_cash_value"],
                mode="lines",
                name="Shadow Cash Reserve",
                line=dict(color="#F59E0B", width=2),
                fill="tozeroy",
                fillcolor="rgba(245, 158, 11, 0.15)",
                hovertemplate="Shadow Cash: ₹%{y:,.0f}<extra></extra>"
            ),
            secondary_y=True
        )

        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="#131722",
            plot_bgcolor="#131722",
            margin=dict(l=10, r=10, t=10, b=10),
            height=260,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5,
                font=dict(size=10)
            ),
            hovermode="x unified",
            xaxis=dict(showgrid=False)
        )
        fig2.update_yaxes(
            title_text="Net Alpha (₹)",
            showgrid=True,
            gridcolor="#232733",
            tickprefix="₹",
            tickformat=",",
            secondary_y=False
        )
        fig2.update_yaxes(
            title_text="Shadow Cash (₹)",
            range=[0, max_cash * 1.15 if max_cash > 0 else 10000.0],
            showgrid=False,
            tickprefix="₹",
            tickformat=",",
            secondary_y=True
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Alpha Summary Card
        st.markdown(f"""
        <div class='metric-card' style='margin-top:10px;'>
            <div style='display:flex; justify-content:space-between;'>
                <div>
                    <div class='metric-title'>Net Alpha Generated</div>
                    <div style='font-size:1.2rem; font-weight:700;' class='text-green'>+₹{alpha_rs:,.2f}</div>
                </div>
                <div style='text-align:right;'>
                    <div class='metric-title'>Post-Tax Alpha %</div>
                    <div style='font-size:1.2rem; font-weight:700;' class='text-green'>+{alpha_pct:.2f}%</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ==========================================
# TAB 4: TRANSACTION LEDGER
# ==========================================
with tab_trades:
    st.markdown("#### Transaction Log & Settlements")
    st.caption("T+1 NAV Settlement Lag enforced on all trades.")

    txs = db.get_transactions(limit=100)
    if txs:
        for t in txs:
            t_type = t.get("transaction_type", "")
            t_amt = float(t.get("amount", 0))
            t_date = t.get("trade_date", "")
            t_settle = t.get("settlement_date", "")
            t_units = float(t.get("units", 0))
            t_nav = float(t.get("nav", 0))
            status = t.get("status", "SETTLED")

            badge_color = "#00D09C" if "EQUITY" in t_type else ("#FFB020" if "CASH" in t_type else "#38BDF8")

            st.markdown(f"""
            <div class='fund-card' style='padding:10px 14px; margin-bottom:8px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-weight:600; font-size:0.85rem;'>{t.get('scheme_name')}</span>
                    <span class='badge' style='background:{badge_color}; color:#111;'>{t_type}</span>
                </div>
                <div class='fund-row' style='color:#9ca3af; font-size:0.78rem;'>
                    <span>Trade: <b>{t_date}</b> (Settle: <b>{t_settle}</b>)</span>
                    <span style='font-weight:700; color:#fff;'>₹{t_amt:,.2f}</span>
                </div>
                <div class='fund-row' style='color:#6b7280; font-size:0.75rem;'>
                    <span>{t_units:.3f} units @ ₹{t_nav:.2f}</span>
                    <span>Status: <b>{status}</b></span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No transaction records found yet.")

# ==========================================
# TAB 5: ON-DEMAND ACTIONS & SIMULATOR
# ==========================================
with tab_settings:
    st.markdown("#### Cloud Control & Testing")
    st.caption("Trigger live pipeline steps or test alerts.")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("⚡ Run Daily Pipeline"):
            with st.spinner("Executing daily cycle (NAVs, Regimes, Snapshots)..."):
                from src.daily_job import run_daily_cycle
                res = run_daily_cycle(force_send_telegram=False)
                st.success("Daily cycle executed successfully!")
                st.rerun()

    with col_btn2:
        if st.button("📲 Test Telegram Alert"):
            with st.spinner("Dispatching Telegram notification..."):
                alert_text = format_tactical_alert(scores, decisions, latest_snap)
                resp = send_telegram_alert(alert_text)
                if resp.get("ok"):
                    st.success("Delivered to Telegram!")
                else:
                    st.error(f"Error: {resp.get('error')}")

    # Stress-Test Simulator
    st.markdown("---")
    st.markdown("##### 🎛️ Tactical Stress-Test Simulator")
    st.caption("Adjust simulated Mid/Smallcap regime score to verify Tier 1 SIP rerouting and Tier 2 friction checks in real-time.")

    test_rolling = st.slider("Simulated Mid/Smallcap 30-Day Rolling Avg (Governs SIP)", min_value=15.0, max_value=90.0, value=52.0, step=1.0)
    test_spot = st.slider("Simulated Mid/Smallcap Today's Spot Score (Crash Override)", min_value=15.0, max_value=90.0, value=60.0, step=1.0)

    sim_scores = {
        "NIFTY_500": scores.get("NIFTY_500", {}),
        "MID_SMALL": {
            "spot_score": test_spot,
            "rolling_avg_score": test_rolling,
            "composite_score": test_spot,
            "details": {"dma_dist_pct": -8.0 if test_spot < 40 else 2.0}
        },
        "NASDAQ_100": scores.get("NASDAQ_100", {})
    }
    sim_decisions = evaluate_tactical_decisions(sim_scores)

    st.markdown(f"**Simulated Directive:** {sim_decisions['action_badge']}")
    st.markdown(f"- Equity SIP Allocation: **₹{sim_decisions['total_sip_equity']:,.0f}**")
    st.markdown(f"- Shadow Cash Diversion: **₹{sim_decisions['total_sip_cash']:,.0f}**")
    for s_fund, s_d in sim_decisions.get("sip_decisions", {}).items():
        st.caption(f"• {s_fund.replace(' Direct Growth', '')}: **{s_d['action']}** (₹{s_d['amount']:,.0f}) — {s_d.get('reason')}")

    # Cloud Deployment Info
    st.markdown("---")
    st.markdown("##### ☁️ Cloud Deployment Status")
    supabase_configured = bool(os.getenv("SUPABASE_URL") and "supabase.co" in os.getenv("SUPABASE_URL", ""))
    telegram_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    st.markdown(f"""
    - **Database**: {'🟢 Supabase PostgreSQL Connected' if supabase_configured else '🟡 Local SQLite (Run schema.sql in Supabase to switch)'}
    - **Telegram Bot**: {'🟢 Verified & Connected' if telegram_configured else '🔴 Token Missing'}
    - **GitHub Scheduler**: 🟢 Scheduled Mon–Fri at 09:00 UTC (2:30 PM IST)
    """)
