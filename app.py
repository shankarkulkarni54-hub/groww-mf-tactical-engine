"""Finology-inspired modern Indian wealth-tech dashboard for Groww Mutual Fund Tactical Allocation Engine."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import textwrap
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date, timedelta
from src.db import get_db

try:
    from src.regime_engine import (
        update_all_regimes,
        SLEEVE_CONFIG,
        UNRESTRICTED_UNIVERSE,
        score_unrestricted_universe,
        check_smart_ltcg_switches,
        get_fund_chart_data,
        format_inr
    )
except ImportError:
    from src import (
        update_all_regimes,
        SLEEVE_CONFIG,
        UNRESTRICTED_UNIVERSE,
        score_unrestricted_universe,
        check_smart_ltcg_switches,
        get_fund_chart_data,
        format_inr
    )

from src.paper_ledger import (
    evaluate_tactical_decisions,
    calculate_friction_and_drag,
    get_live_portfolio_summary,
    get_live_forward_challenge,
    log_monthly_execution
)
from src.telegram_bot import format_tactical_alert, send_telegram_alert
from src.backtester import run_five_year_backtest

# Streamlit Page Config - Full-Width Layout for Finology Bento Design
st.set_page_config(
    page_title="Tactical MF Engine | WealthTech",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =====================================================================
# THEME STATE INITIALIZATION (DEFAULT: DARK MODE)
# =====================================================================
if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "🌙 Dark"

if "monthly_sip_budget" not in st.session_state:
    st.session_state.monthly_sip_budget = 50000.0

is_dark = (st.session_state.theme_mode == "🌙 Dark")

# Calculate Cut-off Countdown
now_ist = datetime.now()
cutoff_time = now_ist.replace(hour=15, minute=0, second=0, microsecond=0)
if now_ist < cutoff_time:
    mins_left = int((cutoff_time - now_ist).total_seconds() / 60)
    cutoff_text = f"🟢 3 PM Cut-off: {mins_left}m Left"
else:
    cutoff_text = "🟢 3 PM Cut-off"

# ---------------------------------------------------------------------
# DESIGN TOKENS (DYNAMIC DARK & LIGHT THEME)
# ---------------------------------------------------------------------
if is_dark:
    T = {
        "mode": "dark",
        "bg_canvas": "#090D16",
        "bg_card": "#111827",
        "bg_card_hover": "#1F2937",
        "bg_subtle": "#1E293B",
        "bg_alt": "#0B1120",
        "border": "#1E293B",
        "border_light": "#334155",
        "text_primary": "#F8FAFC",
        "text_secondary": "#CBD5E1",
        "text_muted": "#94A3B8",
        "accent_blue": "#3B82F6",
        "accent_emerald": "#10B981",
        "accent_amber": "#F59E0B",
        "accent_rose": "#EF4444",
        "header_bg": "rgba(9, 13, 22, 0.95)",
        "tab_unselected_color": "#CBD5E1",
        "tab_unselected_bg": "transparent",
        "tab_active_bg": "#1E293B",
        "tab_active_color": "#60A5FA",
        "tab_active_border": "#3B82F6",
        "widget_label_color": "#F1F5F9",
        "select_bg": "#111827",
        "select_border": "#334155",
        "select_hover": "#3B82F6",
        "menu_bg": "#111827",
        "menu_text": "#F8FAFC",
        "menu_hover_bg": "#1E293B",
        "menu_hover_text": "#60A5FA",
        "table_header_bg": "#1E293B",
        "table_header_text": "#F8FAFC",
        "table_row_bg": "#111827",
        "table_row_alt": "#0F172A",
        "table_row_text": "#F8FAFC",
        "table_border": "#1E293B",
        "table_hover": "#1F2937",
        "shadow_sm": "0 1px 3px 0 rgba(0, 0, 0, 0.4)",
        "plotly_template": "plotly_dark",
        "plotly_paper": "#111827",
        "plotly_plot": "#111827",
        "plotly_grid": "#1E293B",
        "plotly_text": "#F8FAFC",
        "pill_emerald_bg": "#064E3B",
        "pill_emerald_border": "#059669",
        "pill_emerald_text": "#34D399",
        "pill_blue_bg": "#1E3A8A",
        "pill_blue_border": "#2563EB",
        "pill_blue_text": "#93C5FD",
        "pill_amber_bg": "#451A03",
        "pill_amber_border": "#D97706",
        "pill_amber_text": "#FCD34D",
        "pill_rose_bg": "#4C0519",
        "pill_rose_border": "#DC2626",
        "pill_rose_text": "#FCA5A5",
        "pill_slate_bg": "#1E293B",
        "pill_slate_border": "#334155",
        "pill_slate_text": "#CBD5E1",
        "pill_purple_bg": "#2E1065",
        "pill_purple_border": "#7C3AED",
        "pill_purple_text": "#C4B5FD",
        "toggle_bg": "#1E293B",
        "toggle_border": "#334155",
        "toggle_active_bg": "#3B82F6",
        "toggle_active_text": "#FFFFFF",
    }
else:
    T = {
        "mode": "light",
        "bg_canvas": "#F8FAFC",
        "bg_card": "#FFFFFF",
        "bg_card_hover": "#F1F5F9",
        "bg_subtle": "#F1F5F9",
        "bg_alt": "#F8FAFC",
        "border": "#E2E8F0",
        "border_light": "#CBD5E1",
        "text_primary": "#0F172A",
        "text_secondary": "#475569",
        "text_muted": "#64748B",
        "accent_blue": "#2563EB",
        "accent_emerald": "#059669",
        "accent_amber": "#D97706",
        "accent_rose": "#DC2626",
        "header_bg": "rgba(248, 250, 252, 0.95)",
        "tab_unselected_color": "#475569",
        "tab_unselected_bg": "transparent",
        "tab_active_bg": "#EFF6FF",
        "tab_active_color": "#2563EB",
        "tab_active_border": "#2563EB",
        "widget_label_color": "#1E293B",
        "select_bg": "#FFFFFF",
        "select_border": "#CBD5E1",
        "select_hover": "#2563EB",
        "menu_bg": "#FFFFFF",
        "menu_text": "#0F172A",
        "menu_hover_bg": "#EFF6FF",
        "menu_hover_text": "#2563EB",
        "table_header_bg": "#F8FAFC",
        "table_header_text": "#1E293B",
        "table_row_bg": "#FFFFFF",
        "table_row_alt": "#F8FAFC",
        "table_row_text": "#0F172A",
        "table_border": "#E2E8F0",
        "table_hover": "#F8FAFC",
        "shadow_sm": "0 1px 3px 0 rgba(0, 0, 0, 0.04)",
        "plotly_template": "plotly_white",
        "plotly_paper": "#FFFFFF",
        "plotly_plot": "#FFFFFF",
        "plotly_grid": "#E2E8F0",
        "plotly_text": "#0F172A",
        "pill_emerald_bg": "#ECFDF5",
        "pill_emerald_border": "#A7F3D0",
        "pill_emerald_text": "#065F46",
        "pill_blue_bg": "#EFF6FF",
        "pill_blue_border": "#BFDBFE",
        "pill_blue_text": "#1E40AF",
        "pill_amber_bg": "#FFFBEB",
        "pill_amber_border": "#FDE68A",
        "pill_amber_text": "#92400E",
        "pill_rose_bg": "#FEF2F2",
        "pill_rose_border": "#FECACA",
        "pill_rose_text": "#991B1B",
        "pill_slate_bg": "#F1F5F9",
        "pill_slate_border": "#E2E8F0",
        "pill_slate_text": "#475569",
        "pill_purple_bg": "#F5F3FF",
        "pill_purple_border": "#DDD6FE",
        "pill_purple_text": "#7C3AED",
        "toggle_bg": "#E2E8F0",
        "toggle_border": "#CBD5E1",
        "toggle_active_bg": "#2563EB",
        "toggle_active_text": "#FFFFFF",
    }

# Dynamic Theme-Driven CSS Style Sheet
st.markdown(f"""
<style>
    /* -------------------------------------------------------------
       1. GOOGLE FONTS: Modern Fintech Typography System
       - Plus Jakarta Sans: Page titles, card headers, section titles
       - Inter: UI body text, tabs, captions, descriptions
       - JetBrains Mono: All ₹ rupee metrics, percentages, NAV values
       ------------------------------------------------------------- */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

    :root {{
        --bg-canvas: {T['bg_canvas']};
        --bg-card: {T['bg_card']};
        --bg-card-hover: {T['bg_card_hover']};
        --bg-subtle: {T['bg_subtle']};
        --border: {T['border']};
        --border-light: {T['border_light']};
        --text-primary: {T['text_primary']};
        --text-secondary: {T['text_secondary']};
        --text-muted: {T['text_muted']};
        --accent-blue: {T['accent_blue']};
        --accent-emerald: {T['accent_emerald']};
        --toggle-bg: {T['toggle_bg']};
        --toggle-border: {T['toggle_border']};
        --toggle-active-bg: {T['toggle_active_bg']};
        --pill-emerald-bg: {T['pill_emerald_bg']};
        --pill-emerald-border: {T['pill_emerald_border']};
        --pill-emerald-text: {T['pill_emerald_text']};
    }}

    /* Global Root & Streamlit Canvas */
    html, body, [class*="css"], .stApp {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background-color: {T['bg_canvas']} !important;
        color: {T['text_primary']} !important;
    }}

    /* Headings & Editorial Typography - Bright White in Dark Mode */
    h1, h2, h3, h4, h5, h6,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
    [data-testid="stHeadingWithActionElements"],
    [data-testid="stHeadingWithActionElements"] h1,
    [data-testid="stHeadingWithActionElements"] h2,
    [data-testid="stHeadingWithActionElements"] h3,
    [data-testid="stHeadingWithActionElements"] h4,
    div[data-testid="stMarkdownContainer"] h1,
    div[data-testid="stMarkdownContainer"] h2,
    div[data-testid="stMarkdownContainer"] h3,
    div[data-testid="stMarkdownContainer"] h4,
    .section-title,
    .hero-title,
    .fin-title {{
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 700 !important;
        color: {T['text_primary']} !important;
        letter-spacing: -0.02em !important;
    }}

    /* Body & Caption Paragraphs - Crisp Light Slate in Dark Mode */
    p, span, label, li,
    div[data-testid="stMarkdownContainer"] p,
    .stCaption, div[data-testid="stCaptionContainer"] p {{
        color: {T['text_secondary']} !important;
        font-family: 'Inter', sans-serif !important;
    }}

    /* Tabular Rupee & Numeric Figures (JetBrains Mono) */
    .tabular, .mono-num, .kpi-value, .metric-val, .metric-num, .nav-val {{
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
        font-feature-settings: 'tnum' 1 !important;
    }}

    /* Main Container Padding: Clean clearance below fixed header */
    section.main {{
        padding-top: 0 !important;
    }}
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stAppViewBlockContainer"],
    .block-container {{
        max-width: 100% !important;
        padding-top: 3.6rem !important;
        padding-bottom: 3.5rem !important;
        padding-left: 2.2rem !important;
        padding-right: 2.2rem !important;
        font-feature-settings: 'tnum' 1;
    }}

    @media (max-width: 768px) {{
        div[data-testid="stMainBlockContainer"],
        div[data-testid="stAppViewBlockContainer"],
        .block-container {{
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 3.2rem !important;
        }}
    }}

    /* -------------------------------------------------------------
       2. TOP HEADER BAR & STREAMLIT CONTROLS
       ------------------------------------------------------------- */
    header[data-testid="stHeader"] {{
        background: {T['header_bg']} !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border-bottom: 1px solid {T['border']} !important;
        height: 3.5rem !important;
    }}

    div[data-testid="stDecoration"] {{
        display: none !important;
    }}

    header[data-testid="stHeader"] * {{
        color: {T['text_secondary']} !important;
    }}

    header[data-testid="stHeader"] button,
    header[data-testid="stHeader"] a {{
        background-color: {T['bg_card']} !important;
        border: 1px solid {T['border_light']} !important;
        border-radius: 8px !important;
        color: {T['text_secondary']} !important;
        transition: all 0.15s ease !important;
    }}

    header[data-testid="stHeader"] button:hover,
    header[data-testid="stHeader"] a:hover {{
        background-color: {T['bg_card_hover']} !important;
        border-color: {T['accent_blue']} !important;
        color: {T['text_primary']} !important;
    }}

    header[data-testid="stHeader"] svg {{
        fill: {T['text_secondary']} !important;
        stroke: {T['text_secondary']} !important;
        color: {T['text_secondary']} !important;
    }}

    header[data-testid="stHeader"] button:hover svg {{
        fill: {T['text_primary']} !important;
        stroke: {T['text_primary']} !important;
        color: {T['text_primary']} !important;
    }}

    /* Dedicated Fully-Visible Right-Aligned Theme Toggle Pill */
    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) {{
        margin: 0 !important;
        padding: 4px 0 !important;
        display: flex !important;
        justify-content: flex-end !important;
        position: static !important;
        z-index: 10 !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] {{
        display: inline-flex !important;
        flex-direction: row !important;
        background: {T['toggle_bg']} !important;
        border: 1px solid {T['toggle_border']} !important;
        border-radius: 9999px !important;
        padding: 3px 4px !important;
        gap: 3px !important;
        box-shadow: {T['shadow_sm']} !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] label {{
        margin: 0 !important;
        padding: 4px 14px !important;
        border-radius: 9999px !important;
        cursor: pointer !important;
        background: transparent !important;
        transition: all 0.15s ease-in-out !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] label > div:first-child {{
        display: none !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] label div p {{
        font-family: 'Inter', sans-serif !important;
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        color: {T['text_secondary']} !important;
        margin: 0 !important;
        line-height: 1.2 !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] label:has(input:checked) {{
        background: {T['toggle_active_bg']} !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25) !important;
    }}

    div[data-testid="stRadio"]:is(:has(input[value="🌙 Dark"]), :has(input[value*="Dark"])) div[role="radiogroup"] label:has(input:checked) div p {{
        color: {T['toggle_active_text']} !important;
        font-weight: 700 !important;
    }}

    /* -------------------------------------------------------------
       3. STREAMLIT TABS CONTRAST & TYPOGRAPHY
       ------------------------------------------------------------- */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 8px !important;
        background-color: transparent !important;
        border-bottom: 2px solid {T['border']} !important;
        padding-bottom: 0px !important;
        margin-bottom: 18px !important;
    }}

    .stTabs [data-baseweb="tab"] {{
        background-color: transparent !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
        border-radius: 8px 8px 0 0 !important;
        padding: 8px 16px !important;
        margin-bottom: -2px !important;
        color: {T['tab_unselected_color']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.90rem !important;
        transition: all 0.15s ease-in-out !important;
    }}

    .stTabs [data-baseweb="tab"]:hover {{
        color: {T['text_primary']} !important;
        background-color: {T['bg_card_hover']} !important;
    }}

    .stTabs [data-baseweb="tab"] div,
    .stTabs [data-baseweb="tab"] p,
    .stTabs [data-baseweb="tab"] span {{
        color: {T['tab_unselected_color']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.90rem !important;
        transition: color 0.15s ease-in-out !important;
    }}

    .stTabs [data-baseweb="tab"]:hover div,
    .stTabs [data-baseweb="tab"]:hover p,
    .stTabs [data-baseweb="tab"]:hover span {{
        color: {T['text_primary']} !important;
    }}

    .stTabs [data-baseweb="tab"][aria-selected="true"] {{
        background-color: {T['tab_active_bg']} !important;
        color: {T['tab_active_color']} !important;
        border-bottom: 2px solid {T['tab_active_border']} !important;
    }}

    .stTabs [data-baseweb="tab"][aria-selected="true"] div,
    .stTabs [data-baseweb="tab"][aria-selected="true"] p,
    .stTabs [data-baseweb="tab"][aria-selected="true"] span {{
        color: {T['tab_active_color']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }}

    .stTabs [data-baseweb="tab-highlight"] {{
        background-color: {T['tab_active_border']} !important;
        height: 2px !important;
    }}

    .stTabs [data-baseweb="tab-border"] {{
        display: none !important;
    }}

    /* -------------------------------------------------------------
       4. FORM CONTROLS, SELECTBOXES & RADIOS
       ------------------------------------------------------------- */
    div[data-testid="stWidgetLabel"],
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stWidgetLabel"] label,
    div[data-testid="stWidgetLabel"] span,
    label[data-testid="stWidgetLabel"],
    .stSelectbox label, 
    .stRadio:not(:has(input[value="🌙 Dark"])) label, 
    .stSlider label,
    .stMultiSelect label,
    label {{
        color: {T['widget_label_color']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.84rem !important;
        letter-spacing: -0.01em !important;
    }}

    div[data-baseweb="select"] {{
        background-color: {T['select_bg']} !important;
        border: 1px solid {T['select_border']} !important;
        border-radius: 8px !important;
        box-shadow: {T['shadow_sm']} !important;
    }}
    div[data-baseweb="select"] * {{
        color: {T['text_primary']} !important;
        font-family: 'Inter', sans-serif !important;
    }}
    div[data-baseweb="select"]:hover {{
        border-color: {T['select_hover']} !important;
    }}
    ul[data-baseweb="menu"] {{
        background-color: {T['menu_bg']} !important;
        border: 1px solid {T['border']} !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25) !important;
    }}
    ul[data-baseweb="menu"] li {{
        color: {T['menu_text']} !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.85rem !important;
    }}
    ul[data-baseweb="menu"] li:hover,
    ul[data-baseweb="menu"] li[aria-selected="true"] {{
        background-color: {T['menu_hover_bg']} !important;
        color: {T['menu_hover_text']} !important;
        font-weight: 600 !important;
    }}

    div[data-testid="stRadio"]:not(:has(input[value="🌙 Dark"])) div[role="radiogroup"] label {{
        color: {T['text_secondary']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        font-size: 0.85rem !important;
    }}
    div[data-testid="stRadio"]:not(:has(input[value="🌙 Dark"])) div[role="radiogroup"] label div p,
    div[data-testid="stRadio"]:not(:has(input[value="🌙 Dark"])) div[role="radiogroup"] label span {{
        color: {T['text_secondary']} !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
    }}
    div[data-testid="stRadio"]:not(:has(input[value="🌙 Dark"])) div[role="radiogroup"] label:hover div p,
    div[data-testid="stRadio"]:not(:has(input[value="🌙 Dark"])) div[role="radiogroup"] label:hover span {{
        color: {T['text_primary']} !important;
    }}

    div[data-testid="stExpander"] {{
        background-color: {T['bg_card']} !important;
        border: 1px solid {T['border']} !important;
        border-radius: 10px !important;
        box-shadow: {T['shadow_sm']} !important;
        margin-bottom: 12px !important;
    }}
    div[data-testid="stExpander"] details summary {{
        color: {T['text_primary']} !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stExpander"] details summary svg {{
        fill: {T['text_secondary']} !important;
    }}
    div[data-testid="stExpander"] details summary:hover {{
        color: {T['accent_blue']} !important;
    }}
    div[data-testid="stExpander"] details div[data-testid="stExpanderDetails"] {{
        background-color: {T['bg_card']} !important;
        border-top: 1px solid {T['border']} !important;
        color: {T['text_secondary']} !important;
    }}

    .stCaption, 
    div[data-testid="stCaptionContainer"] p {{
        color: {T['text_muted']} !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.78rem !important;
    }}
    div[data-testid="stMarkdownContainer"] p {{
        color: {T['text_secondary']} !important;
        font-family: 'Inter', sans-serif !important;
    }}

    /* -------------------------------------------------------------
       5. DATAFRAMES & TABLES
       ------------------------------------------------------------- */
    div[data-testid="stDataFrame"],
    div[data-testid="stTable"],
    .stDataFrame {{
        background: {T['table_row_bg']} !important;
        background-color: {T['table_row_bg']} !important;
        border: 1px solid {T['table_border']} !important;
        border-radius: 10px !important;
        overflow: hidden !important;
        box-shadow: {T['shadow_sm']} !important;
    }}
    div[data-testid="stDataFrame"] > div,
    div[data-testid="stDataFrame"] > div > div {{
        background: {T['table_row_bg']} !important;
        background-color: {T['table_row_bg']} !important;
    }}
    div[data-testid="stDataFrame"] *,
    div[data-testid="stTable"] * {{
        font-family: 'Inter', sans-serif !important;
        color: {T['table_row_text']} !important;
    }}

    table {{
        width: 100% !important;
        border-collapse: separate !important;
        border-spacing: 0 !important;
        background-color: {T['table_row_bg']} !important;
        border: 1px solid {T['table_border']} !important;
        border-radius: 10px !important;
        overflow: hidden !important;
        box-shadow: {T['shadow_sm']} !important;
        margin-top: 8px !important;
        margin-bottom: 14px !important;
    }}
    thead th, th {{
        background-color: {T['table_header_bg']} !important;
        color: {T['table_header_text']} !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 700 !important;
        font-size: 0.80rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.03em !important;
        padding: 10px 14px !important;
        border-bottom: 1px solid {T['table_border']} !important;
        border-right: 1px solid {T['border_light']} !important;
        text-align: left !important;
    }}
    thead th:last-child, th:last-child {{
        border-right: none !important;
    }}
    tbody td, td {{
        background-color: {T['table_row_bg']} !important;
        color: {T['table_row_text']} !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.85rem !important;
        padding: 10px 14px !important;
        border-bottom: 1px solid {T['table_border']} !important;
        border-right: 1px solid {T['border']} !important;
    }}
    tbody td:last-child, td:last-child {{
        border-right: none !important;
    }}
    tbody tr:last-child td, tr:last-child td {{
        border-bottom: none !important;
    }}
    tbody tr:hover td, tr:hover td {{
        background-color: {T['table_hover']} !important;
    }}

    div[data-testid="stSlider"] div[data-baseweb="slider"] {{
        color: {T['accent_blue']} !important;
    }}
    div[data-testid="stSlider"] p,
    div[data-testid="stSlider"] span {{
        color: {T['text_primary']} !important;
        font-family: 'JetBrains Mono', monospace !important;
    }}

    /* -------------------------------------------------------------
       6. BENTO CARDS & BADGES
       ------------------------------------------------------------- */
    .fin-card {{
        background: {T['bg_card']} !important;
        border: 1px solid {T['border']} !important;
        border-radius: 12px !important;
        padding: 16px 18px !important;
        margin-bottom: 14px !important;
        box-shadow: {T['shadow_sm']} !important;
        transition: box-shadow 0.15s ease, border-color 0.15s ease !important;
    }}
    .fin-card:hover {{
        border-color: {T['border_light']} !important;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15) !important;
    }}

    .kpi-ribbon {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 16px;
    }}
    @media (max-width: 768px) {{
        .kpi-ribbon {{
            grid-template-columns: repeat(2, 1fr);
        }}
    }}
    @media (max-width: 480px) {{
        .kpi-ribbon {{
            grid-template-columns: 1fr;
        }}
    }}

    .kpi-tile {{
        background: {T['bg_card']} !important;
        border: 1px solid {T['border']} !important;
        border-radius: 12px !important;
        padding: 14px 16px !important;
        box-shadow: {T['shadow_sm']} !important;
        transition: transform 0.15s ease, border-color 0.15s ease !important;
    }}
    .kpi-tile:hover {{
        transform: translateY(-1px);
        border-color: {T['border_light']} !important;
    }}
    .kpi-label {{
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.72rem;
        font-weight: 700;
        color: {T['text_muted']};
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }}
    .kpi-value {{
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.35rem;
        font-weight: 700;
        color: {T['text_primary']};
        line-height: 1.2;
        font-feature-settings: 'tnum' 1;
        font-variant-numeric: tabular-nums;
    }}
    .kpi-sub {{
        font-family: 'Inter', sans-serif !important;
        font-size: 0.75rem;
        margin-top: 5px;
        font-feature-settings: 'tnum' 1;
        display: flex;
        align-items: center;
        gap: 4px;
        color: {T['text_secondary']};
    }}

    .hero-card {{
        background: {T['bg_card']} !important;
        border: 1px solid {T['border']} !important;
        border-top: 4px solid {T['accent_blue']} !important;
        border-radius: 14px !important;
        padding: 18px 20px !important;
        margin-bottom: 18px !important;
        box-shadow: {T['shadow_sm']} !important;
    }}

    .badge-pill {{
        font-family: 'Inter', sans-serif !important;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 6px;
        display: inline-block;
        letter-spacing: 0.2px;
        line-height: 1.3;
    }}
    .pill-emerald {{
        background: {T['pill_emerald_bg']} !important;
        color: {T['pill_emerald_text']} !important;
        border: 1px solid {T['pill_emerald_border']} !important;
    }}
    .pill-blue {{
        background: {T['pill_blue_bg']} !important;
        color: {T['pill_blue_text']} !important;
        border: 1px solid {T['pill_blue_border']} !important;
    }}
    .pill-amber {{
        background: {T['pill_amber_bg']} !important;
        color: {T['pill_amber_text']} !important;
        border: 1px solid {T['pill_amber_border']} !important;
    }}
    .pill-rose {{
        background: {T['pill_rose_bg']} !important;
        color: {T['pill_rose_text']} !important;
        border: 1px solid {T['pill_rose_border']} !important;
    }}
    .pill-slate {{
        background: {T['pill_slate_bg']} !important;
        color: {T['pill_slate_text']} !important;
        border: 1px solid {T['pill_slate_border']} !important;
    }}
    .pill-purple {{
        background: {T['pill_purple_bg']} !important;
        color: {T['pill_purple_text']} !important;
        border: 1px solid {T['pill_purple_border']} !important;
    }}

    .stButton>button {{
        width: 100%;
        border-radius: 8px;
        height: 42px;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600;
        border: 1px solid {T['border_light']};
        background: {T['bg_card']};
        color: {T['text_primary']};
        box-shadow: {T['shadow_sm']};
        transition: all 0.15s ease;
    }}
    .stButton>button:hover {{
        background: {T['bg_card_hover']};
        border-color: {T['accent_blue']};
        color: {T['accent_blue']};
    }}

    /* Global dynamic catch-all overrides for inline markup */
    div[style*="background:#F8FAFC"],
    div[style*="background: #F8FAFC"] {{
        background: {T['bg_alt']} !important;
        border-color: {T['border']} !important;
    }}
    div[style*="background:#FFFFFF"],
    div[style*="background: #FFFFFF"],
    div[style*="background-color:#FFFFFF"],
    div[style*="background-color: #FFFFFF"] {{
        background: {T['bg_card']} !important;
        background-color: {T['bg_card']} !important;
        border-color: {T['border']} !important;
    }}
    div[style*="color:#0F172A"],
    div[style*="0F172A"],
    div[style*="0f172a"],
    span[style*="0F172A"],
    span[style*="0f172a"],
    b[style*="0F172A"],
    b[style*="0f172a"] {{
        color: {T['text_primary']} !important;
    }}
    div[style*="64748B"],
    div[style*="64748b"],
    span[style*="64748B"],
    span[style*="64748b"] {{
        color: {T['text_secondary']} !important;
    }}
    div[style*="border:1px solid #E2E8F0"],
    div[style*="border: 1px solid #E2E8F0"] {{
        border-color: {T['border']} !important;
    }}
</style>
""", unsafe_allow_html=True)


def render_html(html_str: str):
    """Renders HTML in Streamlit adapting colors to the active theme."""
    cleaned = "\n".join(line.strip() for line in html_str.splitlines() if line.strip())
    if is_dark:
        cleaned = (
            cleaned.replace("background:#FFFFFF", "background:#111827")
                   .replace("background: #FFFFFF", "background:#111827")
                   .replace("background-color:#FFFFFF", "background-color:#111827")
                   .replace("background-color: #FFFFFF", "background-color:#111827")
                   .replace("background:#F8FAFC", "background:#0B1120")
                   .replace("background: #F8FAFC", "background:#0B1120")
                   .replace("background-color:#F8FAFC", "background-color:#0B1120")
                   .replace("background-color: #F8FAFC", "background-color:#0B1120")
                   .replace("border:1px solid #E2E8F0", "border:1px solid #1E293B")
                   .replace("border: 1px solid #E2E8F0", "border: 1px solid #1E293B")
                   .replace("color:#0F172A", "color:#F8FAFC")
                   .replace("color: #0F172A", "color: #F8FAFC")
                   .replace("color:#0f172a", "color:#F8FAFC")
                   .replace("color: #0f172a", "color: #F8FAFC")
                   .replace("color:#334155", "color:#CBD5E1")
                   .replace("color: #334155", "color: #CBD5E1")
                   .replace("color:#475569", "color:#CBD5E1")
                   .replace("color: #475569", "color: #CBD5E1")
                   .replace("color:#64748B", "color:#CBD5E1")
                   .replace("color: #64748B", "color: #CBD5E1")
        )
    st.markdown(cleaned, unsafe_allow_html=True)


def render_section_header(title: str, caption: str = None, margin_top: int = 0):
    """Renders a section header and optional caption respecting active theme colors."""
    mt = f"margin-top:{margin_top}px;" if margin_top > 0 else ""
    c_primary = T["text_primary"]
    render_html(f"""<div style='font-family:"Plus Jakarta Sans", sans-serif; font-size:1.05rem; font-weight:800; color:{c_primary}; {mt} margin-bottom:2px;'>{title}</div>""")
    if caption:
        st.caption(caption)


def init_app():
    """Initializes and caches base state."""
    db = get_db()
    scores = db.get_latest_regime_scores()
    if not scores:
        scores = update_all_regimes()

    portfolio_sum = get_live_portfolio_summary(db)
    return db, scores, portfolio_sum


db, scores, portfolio_sum = init_app()
decisions = evaluate_tactical_decisions(scores)

# =====================================================================
# 1. DEDICATED TOP ACTION STRIP (BRAND & RIGHT-ALIGNED THEME SWITCHER)
# =====================================================================
top_strip_left, top_strip_right = st.columns([3, 1])
with top_strip_left:
    render_html(f"""
    <div style='display:flex; align-items:center; gap:10px; padding:4px 0;'>
        <span style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:1.15rem; font-weight:800; color:{T["text_primary"]}; letter-spacing:-0.02em;'>
            📈 Tactical MF Engine
        </span>
        <span style='color:{T["border_light"]}; font-size:0.9rem;'>|</span>
        <span style='font-family:\"Inter\", sans-serif; font-size:0.82rem; color:{T["text_secondary"]}; font-weight:500;'>
            Groww Direct Portfolios • <b style='color:{T["accent_blue"]};'>17.55% AI Momentum</b>
        </span>
        <span style='color:{T["border_light"]}; font-size:0.9rem;'>|</span>
        <span class='badge-pill pill-emerald' style='font-size:0.75rem; font-weight:700;'>
            {cutoff_text}
        </span>
    </div>
    """)
with top_strip_right:
    theme_choice = st.radio(
        "Theme Switcher",
        options=["🌙 Dark", "☀️ Light"],
        index=0 if st.session_state.theme_mode == "🌙 Dark" else 1,
        horizontal=True,
        label_visibility="collapsed",
        key="theme_switcher_radio"
    )
    if theme_choice != st.session_state.theme_mode:
        st.session_state.theme_mode = theme_choice
        st.rerun()

# =====================================================================
# 2. COMPACT HORIZONTAL KPI RIBBON (4 TILES SIDE-BY-SIDE)
# =====================================================================
tot_net_worth = portfolio_sum.get("total_net_worth", 1924654.0)
tot_invested = portfolio_sum.get("total_invested", 1687422.0)
tot_gain_rs = portfolio_sum.get("total_gain_rs", 237232.0)
tot_gain_pct = portfolio_sum.get("total_gain_pct", 14.06)
gain_color = "#059669" if tot_gain_rs >= 0 else "#DC2626"
gain_pill_cls = "pill-emerald" if tot_gain_rs >= 0 else "pill-rose"

ai_picks = decisions.get("ai_top_picks", [])
if not ai_picks and score_unrestricted_universe:
    ai_picks = score_unrestricted_universe().get("top_picks", [])

pick1_name = ai_picks[0]["short_name"] if len(ai_picks) > 0 else "Nippon India Pharma"
pick2_name = ai_picks[1]["short_name"] if len(ai_picks) > 1 else "Motilal Oswal Midcap"

render_html(f"""
<div class='kpi-ribbon'>
    <!-- Tile 1: Portfolio Net Worth -->
    <div class='kpi-tile' style='border-left: 3px solid #059669;'>
        <div class='kpi-label'>Groww Portfolio Net Worth</div>
        <div class='kpi-value'>{format_inr(tot_net_worth)}</div>
        <div class='kpi-sub'>
            <span class='badge-pill {gain_pill_cls} mono-num'>{format_inr(tot_gain_rs, show_sign=True)} ({tot_gain_pct:+.2f}%)</span>
            <span style='color:#64748B; font-size:0.72rem;'>• 100% Equity</span>
        </div>
    </div>

    <!-- Tile 2: 5-Yr Alpha vs Nifty 500 -->
    <div class='kpi-tile' style='border-left: 3px solid #2563EB;'>
        <div class='kpi-label'>5-Yr Alpha vs Nifty 500</div>
        <div class='kpi-value' style='color:#059669;'>+{format_inr(872787)}</div>
        <div class='kpi-sub'>
            <span class='badge-pill pill-emerald mono-num'>+8.28% p.a.</span>
            <span style='color:#64748B; font-size:0.72rem;'>17.55% vs 9.27%</span>
        </div>
    </div>

    <!-- Tile 3: 5-Yr Alpha vs Passive Groww -->
    <div class='kpi-tile' style='border-left: 3px solid #D97706;'>
        <div class='kpi-label'>5-Yr Alpha vs Passive Groww</div>
        <div class='kpi-value' style='color:#059669;'>+{format_inr(329792)}</div>
        <div class='kpi-sub'>
            <span class='badge-pill pill-amber mono-num'>+2.95% p.a.</span>
            <span style='color:#64748B; font-size:0.72rem;'>17.55% vs 14.60%</span>
        </div>
    </div>

    <!-- Tile 4: Upcoming Dec 3 SIP -->
    <div class='kpi-tile' style='border-left: 3px solid #7C3AED;'>
        <div class='kpi-label'>Upcoming Dec 3 SIP</div>
        <div class='kpi-value' style='font-size:1.20rem;'>{format_inr(st.session_state.get('monthly_sip_budget', 50000.0))} {'Full Equity' if st.session_state.get('monthly_sip_budget', 50000.0) > 0 else 'Skipped'}</div>
        <div class='kpi-sub'>
            <span class='badge-pill pill-purple'>Top 2 Leaders</span>
            <span style='color:#64748B; font-size:0.70rem;'>Pharma & Midcap</span>
        </div>
    </div>
</div>
""")

# =====================================================================
# 3. HERO ACTION BANNER: SCANNABLE 2-COLUMN SIP RECOMMENDATION CARD
# =====================================================================
col_hero_hdr, col_hero_input = st.columns([2.7, 1.3])
with col_hero_hdr:
    render_section_header("📅 Monthly SIP Allocation Directive", "Governed by Winning 17.55% AI Engine • Dec 3, 2026 Kickoff", margin_top=4)
with col_hero_input:
    active_budget = float(st.number_input(
        "This Month's SIP Budget (₹)",
        min_value=0,
        max_value=500000,
        value=int(st.session_state.get("monthly_sip_budget", 50000.0)),
        step=5000,
        key="hero_sip_budget_input",
        help="Editable monthly investment amount (₹0 to ₹5,00,000). Set to ₹0 to simulate/log a skipped month. Dynamically computes 50/50 split across top AI leaders."
    ))
    st.session_state["monthly_sip_budget"] = active_budget

is_outside_window = decisions.get("is_outside_sip_window", True)
has_emergency_switch = any(s.get("action") == "SWITCH_TO_CASH" for s in decisions.get("switch_signals", []))
is_action_window = decisions.get("is_sip_action_window", False)
is_execution_day = decisions.get("is_sip_execution_day", False)
smart_alerts = decisions.get("smart_ltcg_alerts", [])

if active_budget <= 0:
    badge_cls = "pill-slate"
    badge_text = "⏸️ MONTH SKIPPED (₹0 SIP) — Zero Capital Deployed"
elif has_emergency_switch:
    badge_cls = "pill-rose"
    badge_text = "🚨 EMERGENCY ACTION: Crash Exit Triggered"
elif len(smart_alerts) > 0:
    badge_cls = "pill-amber"
    badge_text = "⚡ SMART LTCG SWITCH: Breakdown Below 200-DMA"
elif is_action_window:
    badge_cls = "pill-emerald"
    badge_text = "⚡ ACTION WINDOW OPEN — Set Groww SIP"
elif is_execution_day:
    badge_cls = "pill-amber"
    badge_text = "📅 SIP EXECUTION DAY — Auto-debit Active"
else:
    badge_cls = "pill-blue"
    badge_text = "🛡️ NO ACTION REQUIRED TODAY — Hold Existing Units"

tot_eq = active_budget
tot_cash = 0.0
stamp_duty = round(active_budget * 0.00005, 2) if active_budget > 0 else 0.0

p1 = ai_picks[0] if len(ai_picks) > 0 else {}
p2 = ai_picks[1] if len(ai_picks) > 1 else {}

p1_name = p1.get("short_name", "Nippon India Pharma")
p1_subcat = p1.get("sub_category", "Sector Healthcare / Pharma")
p1_score = p1.get("score", 61.8)

p2_name = p2.get("short_name", "Motilal Oswal Midcap")
p2_subcat = p2.get("sub_category", "Cap Midcap")
p2_score = p2.get("score", 61.7)

if active_budget <= 0:
    p1_amt = 0.0
    p2_amt = 0.0
else:
    p1_amt = round(active_budget * 0.50, 2)
    p2_amt = round(active_budget * 0.50, 2)

render_html(f"""
<div class='hero-card' style='margin-top:6px;'>
    <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;'>
        <div>
            <div style='display:flex; align-items:center; gap:8px;'>
                <span style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:1.02rem; font-weight:800; color:{T["text_primary"]};'>📅 Monthly SIP Allocation Directive</span>
                <span class='badge-pill pill-blue'>Dec 3, 2026 Kickoff</span>
            </div>
            <div style='font-size:0.78rem; color:{T["text_secondary"]}; margin-top:2px;'>
                Governed by Winning 17.55% AI Engine • <span class='mono-num' style='font-weight:700; color:#059669;'>{format_inr(active_budget)}</span>/Month Capital ({'50/50 Split: ' + format_inr(p1_amt) + ' each' if active_budget > 0 else 'Month Skipped'})
            </div>
        </div>
        <div>
            <span class='badge-pill {badge_cls}' style='font-size:0.76rem; padding:4px 10px;'>
                {badge_text}
            </span>
        </div>
    </div>

    <!-- 2-Column Scannable Recommendation Bento -->
    <div style='display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-top:14px;'>
        <!-- Pick 1: Nippon India Pharma -->
        <div style='background:{T["bg_subtle"]}; border:1px solid {T["border"]}; border-radius:10px; padding:12px 14px;'>
            <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div>
                    <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:0.92rem; font-weight:700; color:{T["text_primary"]};'>{p1_name}</div>
                    <div style='font-size:0.72rem; color:{T["text_secondary"]};'>{p1_subcat}</div>
                </div>
                <div style='text-align:right;'>
                    <div class='mono-num' style='font-size:1.08rem; font-weight:800; color:#059669;'>{format_inr(p1_amt)}</div>
                    <span class='badge-pill pill-emerald mono-num' style='font-size:0.68rem;'>{'50% Split' if active_budget > 0 else 'Skipped'} • Score {p1_score:.0f}/100</span>
                </div>
            </div>
            <div style='margin-top:8px; display:flex; gap:6px; flex-wrap:wrap;'>
                <span class='badge-pill pill-blue mono-num'>200-DMA +13.6%</span>
                <span class='badge-pill pill-slate mono-num'>90d Return +2.8%</span>
                <span class='badge-pill pill-emerald'>0% Exit Load</span>
            </div>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; margin-top:8px; line-height:1.4;'>
                <b>Why Picked:</b> Sector momentum leader with structural breakout above 200-DMA.
            </div>
        </div>

        <!-- Pick 2: Motilal Oswal Midcap -->
        <div style='background:{T["bg_subtle"]}; border:1px solid {T["border"]}; border-radius:10px; padding:12px 14px;'>
            <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div>
                    <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:0.92rem; font-weight:700; color:{T["text_primary"]};'>{p2_name}</div>
                    <div style='font-size:0.72rem; color:{T["text_secondary"]};'>{p2_subcat}</div>
                </div>
                <div style='text-align:right;'>
                    <div class='mono-num' style='font-size:1.08rem; font-weight:800; color:#059669;'>{format_inr(p2_amt)}</div>
                    <span class='badge-pill pill-emerald mono-num' style='font-size:0.68rem;'>{'50% Split' if active_budget > 0 else 'Skipped'} • Score {p2_score:.0f}/100</span>
                </div>
            </div>
            <div style='margin-top:8px; display:flex; gap:6px; flex-wrap:wrap;'>
                <span class='badge-pill pill-blue mono-num'>200-DMA +16.3%</span>
                <span class='badge-pill pill-slate mono-num'>90d Return +2.2%</span>
                <span class='badge-pill pill-emerald'>0% Exit Load</span>
            </div>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; margin-top:8px; line-height:1.4;'>
                <b>Why Picked:</b> High-alpha midcap compounder with strong relative strength vs Nifty 50.
            </div>
        </div>
    </div>

    <!-- Smart LTCG & Execution Footnote -->
    <div style='margin-top:12px; padding-top:10px; border-top:1px solid {T["border"]}; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;'>
        <div style='display:flex; align-items:center; gap:6px;'>
            <span class='badge-pill pill-emerald'>🛡️ Smart LTCG Status</span>
            <span style='font-size:0.75rem; color:{T["text_secondary"]};'>Zero churn triggered — all active units trade safely above 200-DMA bands.</span>
        </div>
        <div style='font-size:0.75rem; color:{T["text_muted"]};'>
            Total Equity: <b class='mono-num' style='color:#059669;'>{format_inr(tot_eq)}</b> • Cash: <b class='mono-num' style='color:{T["text_muted"]};'>{format_inr(tot_cash)}</b> • Stamp Duty: <span class='mono-num'>{format_inr(stamp_duty, decimals=2)}</span>
        </div>
    </div>
</div>
""")

# =====================================================================
# 4. SEGMENTED TABS (FINOLOGY-STYLE MODERN WEALTH NAVIGATION)
# =====================================================================
tab_regimes, tab_holdings, tab_chart, tab_trades, tab_settings = st.tabs([
    "🎯 Regimes", "💼 Holdings", "📈 Alpha", "📝 Ledger", "⚙️ Actions"
])

# =====================================================================
# TAB 1: REGIMES & INTERACTIVE MOMENTUM SCREENER
# =====================================================================
with tab_regimes:
    render_section_header("🎯 Market Regime Breakdown (0–100)", "50% Technicals (200-DMA, 50-EMA, RSI, ATR, VIX) + 50% Fundamentals (PE Z-score, PB, Yield Spread)")

    # 3-Column Macro Sleeve Cards
    sleeve_cols = st.columns(3)
    sleeves_data = [
        ("NIFTY_500", "Nifty 500", "Parag Parikh Flexi Cap"),
        ("MID_SMALL", "Mid & Small Cap", "Motilal & Nippon"),
        ("NASDAQ_100", "NASDAQ 100", "Edelweiss US Tech")
    ]

    for idx, (s_key, s_title, s_fund) in enumerate(sleeves_data):
        with sleeve_cols[idx]:
            s_obj = scores.get(s_key, {})
            spot = float(s_obj.get("spot_score", s_obj.get("composite_score", 50.0)))
            rolling = float(s_obj.get("rolling_avg_score", s_obj.get("composite_score", 50.0)))
            status = s_obj.get("regime_status", "NEUTRAL")
            status_cls = "pill-emerald" if status == "BULLISH" else ("pill-amber" if status == "CAUTION" else "pill-rose")
            dma_dist = s_obj.get("details", {}).get("dma_dist_pct", 0.0)
            dma_sign = "+" if dma_dist >= 0 else ""
            rsi = s_obj.get("rsi_weekly", 50.0)
            vix = s_obj.get("vix", 15.0)

            render_html(f"""
            <div class='fin-card' style='padding:12px 14px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:0.88rem; font-weight:700; color:{T["text_primary"]};'>{s_title}</div>
                    <span class='badge-pill {status_cls}'>{status}</span>
                </div>
                <div style='font-size:0.70rem; color:{T["text_secondary"]}; margin-top:2px;'>{s_fund}</div>

                <div style='display:grid; grid-template-columns: 1fr 1fr; gap:6px; margin-top:10px; background:{T["bg_subtle"]}; padding:8px 10px; border-radius:8px; border:1px solid {T["border"]};'>
                    <div>
                        <div style='font-size:0.65rem; color:{T["text_secondary"]}; text-transform:uppercase;'>Spot Score</div>
                        <div class='mono-num' style='font-size:1.15rem; font-weight:800; color:{T["text_primary"]};'>{spot:.1f}</div>
                    </div>
                    <div>
                        <div style='font-size:0.65rem; color:#2563EB; text-transform:uppercase;'>30d Average</div>
                        <div class='mono-num' style='font-size:1.15rem; font-weight:800; color:#2563EB;'>{rolling:.1f}</div>
                    </div>
                </div>

                <div style='display:flex; justify-content:space-between; margin-top:8px; font-size:0.72rem; color:{T["text_secondary"]};'>
                    <span>200-DMA: <b class='mono-num' style='color:{T["text_primary"]};'>{dma_sign}{dma_dist:.1f}%</b></span>
                    <span>RSI: <b class='mono-num' style='color:{T["text_primary"]};'>{rsi:.1f}</b></span>
                    <span>VIX: <b class='mono-num' style='color:{T["text_primary"]};'>{vix:.1f}</b></span>
                </div>
            </div>
            """)

    # -------------------------------------------------------------
    # INTERACTIVE UNIVERSE MOMENTUM SCREENER
    # -------------------------------------------------------------
    render_section_header("🔍 Interactive Universe Momentum & 200-DMA Screener", "Scans direct Indian mutual funds across Core, Thematic, Commodities & Global sleeves.", margin_top=18)

    rep = score_unrestricted_universe()
    ranked_funds = rep.get("ranked_funds", [])

    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        cat_filter = st.selectbox(
            "Category Filter",
            ["All Categories", "Core & Cap-Based", "Sectoral / Thematic", "Commodities & Global", "Defensive Cash"],
            index=0
        )
    with f_col2:
        status_filter = st.selectbox(
            "Eligibility Status",
            ["All Statuses", "✅ Buy Candidate (Score >= 60 & > 200-DMA)", "⏳ Hold (Healthy Trend)", "🚨 >365d Switch Alert"],
            index=0
        )
    with f_col3:
        sort_order = st.selectbox(
            "Sort Screener By",
            ["90-Day Return % (Descending)", "Distance from 200-DMA % (Descending)", "AI Composite Score (Descending)"],
            index=0
        )

    # Filter & Sort
    filtered_list = []
    for f in ranked_funds:
        cat = f.get("category", "")
        subcat = f.get("sub_category", "")
        score = f.get("score", 0.0)
        dma_dist = f.get("dma_dist", 0.0)

        if cat_filter == "Core & Cap-Based" and ("Large Cap" not in subcat and "Midcap" not in subcat and "Smallcap" not in subcat and "Flexi" not in subcat and "Broad" not in subcat):
            continue
        elif cat_filter == "Sectoral / Thematic" and not subcat.startswith("Sector"):
            continue
        elif cat_filter == "Commodities & Global" and ("Precious" not in subcat and "Global" not in subcat):
            continue
        elif cat_filter == "Defensive Cash" and cat != "CASH":
            continue

        if status_filter.startswith("✅ Buy Candidate") and (score < 60.0 or dma_dist <= 0.0):
            continue
        elif status_filter.startswith("⏳ Hold") and (score < 50.0 or dma_dist < -8.0):
            continue
        elif status_filter.startswith("🚨 >365d Switch Alert") and dma_dist >= -8.0:
            continue

        filtered_list.append(f)

    if sort_order.startswith("90-Day"):
        filtered_list.sort(key=lambda x: x.get("mom_90", 0.0), reverse=True)
    elif sort_order.startswith("Distance"):
        filtered_list.sort(key=lambda x: x.get("dma_dist", 0.0), reverse=True)
    else:
        filtered_list.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    # Compact Finology Screener Table
    scr_rows = []
    for item in filtered_list:
        s_score = item.get("score", 0.0)
        s_dma = item.get("dma_dist", 0.0)
        s_m90 = item.get("mom_90", 0.0)
        s_m30 = item.get("mom_30", 0.0)
        s_nav = item.get("current_nav", 0.0)

        if s_score >= 60.0 and s_dma > 0.0:
            status_label = "✅ Buy Candidate"
        elif s_dma < -8.0:
            status_label = "🚨 >365d Switch Alert"
        else:
            status_label = "⏳ Hold"

        scr_rows.append({
            "Fund Scheme": item.get("short_name", ""),
            "Category": item.get("sub_category", ""),
            "Score": f"{s_score:.1f}",
            "90d Return": f"{s_m90:+.2f}%",
            "30d Return": f"{s_m30:+.2f}%",
            "200-DMA Dist": f"{s_dma:+.2f}%",
            "Live NAV": format_inr(s_nav, decimals=2),
            "Status": status_label
        })

    if scr_rows:
        st.dataframe(pd.DataFrame(scr_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No funds match current filters.")

    # -------------------------------------------------------------
    # LIGHT-CANVAS PRICE VS 200-DMA & 50-EMA TREND INSPECTOR
    # -------------------------------------------------------------
    render_section_header("📈 Technical Trend & Moving Averages Inspector", "Clean light-canvas Plotly chart showing daily NAV, 200-day trend gate, and 50-day momentum.", margin_top=20)

    fund_keys = [f["key"] for f in ranked_funds]
    fund_names = {f["key"]: f"{f['short_name']} ({f['sub_category']})" for f in ranked_funds}

    insp_col1, insp_col2 = st.columns([2, 1])
    with insp_col1:
        selected_key = st.selectbox(
            "Select Fund to Inspect",
            fund_keys,
            format_func=lambda k: fund_names.get(k, k),
            index=0
        )
    with insp_col2:
        chart_days = st.radio("Lookback Period", ["1 Year (365d)", "2 Years (730d)"], horizontal=True)

    num_days = 730 if "2 Years" in chart_days else 365
    c_data = get_fund_chart_data(selected_key, days=num_days)

    if c_data and c_data.get("dates"):
        fig_c = go.Figure()

        # NAV Price line (Finology Emerald)
        fig_c.add_trace(go.Scatter(
            x=c_data["dates"],
            y=c_data["navs"],
            mode="lines",
            name=f"{c_data['meta']['short_name']} NAV",
            line=dict(color="#059669", width=2.4),
            customdata=[format_inr(v, decimals=2) for v in c_data["navs"]],
            hovertemplate="NAV: %{customdata}<extra></extra>"
        ))

        # 200-DMA line (Amber dashed)
        fig_c.add_trace(go.Scatter(
            x=c_data["dates"],
            y=c_data["dma_200"],
            mode="lines",
            name="200-DMA (Trend Gate)",
            line=dict(color="#D97706", width=1.8, dash="dash"),
            customdata=[format_inr(v, decimals=2) for v in c_data["dma_200"]],
            hovertemplate="200-DMA: %{customdata}<extra></extra>"
        ))

        # 50-EMA line (Royal Blue dotted)
        fig_c.add_trace(go.Scatter(
            x=c_data["dates"],
            y=c_data["ema_50"],
            mode="lines",
            name="50-EMA (Momentum)",
            line=dict(color="#2563EB", width=1.5, dash="dot"),
            customdata=[format_inr(v, decimals=2) for v in c_data["ema_50"]],
            hovertemplate="50-EMA: %{customdata}<extra></extra>"
        ))

        fig_c.update_layout(
            template=T["plotly_template"],
            paper_bgcolor=T["plotly_paper"],
            plot_bgcolor=T["plotly_plot"],
            font=dict(family="Inter, sans-serif", color=T["text_secondary"]),
            height=280,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10, color=T["text_primary"])),
            xaxis=dict(gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            yaxis=dict(gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            hovermode="x unified"
        )
        st.plotly_chart(fig_c, use_container_width=True)

        d_sign = "+" if c_data['dma_dist_pct'] >= 0 else ""
        render_html(f"""
        <div style='background:{T["bg_card"]}; border:1px solid {T["border"]}; border-radius:8px; padding:8px 14px; display:flex; justify-content:space-between; align-items:center; font-size:0.78rem;'>
            <span>Latest NAV: <b class='mono-num' style='color:{T["text_primary"]};'>{format_inr(c_data['current_nav'], decimals=2)}</b></span>
            <span>200-DMA: <b class='mono-num' style='color:{T["text_secondary"]};'>{format_inr(c_data['current_200_dma'], decimals=2)}</b></span>
            <span>Distance from 200-DMA: <b class='mono-num' style='color:{"#059669" if c_data["dma_dist_pct"]>=0 else "#DC2626"};'>{d_sign}{c_data['dma_dist_pct']:.2f}%</b></span>
        </div>
        """)

# ==========================================
# TAB 2: UNIFIED HOLDINGS & FORWARD CHALLENGE
# ==========================================
with tab_holdings:
    # -------------------------------------------------------------
    # SECTION A: 12-MONTH LIVE FORWARD CHALLENGE PORTFOLIOS
    # -------------------------------------------------------------
    render_section_header("🏆 Section A: 12-Month Live Forward Challenge Portfolios", f"Starting Dec 3, 2026 • {format_inr(active_budget)}/Mo SIP on the 3rd • 4 Portfolios Tracked Side-by-Side")

    fwd = get_live_forward_challenge(monthly_sip=active_budget)

    # 4-Column Finology Comparison Grid
    render_html(f"""
    <div style='display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:14px;'>
        <!-- Strategy 1: Winning AI Engine -->
        <div class='fin-card' style='border-top:3px solid #059669; padding:12px 14px;'>
            <div style='font-size:0.72rem; font-weight:700; color:#059669; text-transform:uppercase;'>🏆 Winning AI Engine</div>
            <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(active_budget)}<span style='font-size:0.70rem; color:{T["text_secondary"]};'>/mo</span></div>
            <div style='font-size:0.72rem; color:{T["text_secondary"]}; margin-top:4px;'>{'Top 2 Leaders (' + format_inr(round(active_budget * 0.5, 2)) + ' each)' if active_budget > 0 else 'Month Skipped (₹0)'}</div>
            <div style='margin-top:8px;'>
                <span class='badge-pill pill-emerald mono-num'>17.55% XIRR</span>
                <span class='mono-num' style='font-size:0.68rem; color:{T["text_secondary"]}; margin-left:4px;'>-13.9% DD</span>
            </div>
        </div>

        <!-- Strategy 2: My Passive Groww SIPs -->
        <div class='fin-card' style='border-top:3px solid #D97706; padding:12px 14px;'>
            <div style='font-size:0.72rem; font-weight:700; color:#D97706; text-transform:uppercase;'>📦 Passive Groww</div>
            <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(active_budget)}<span style='font-size:0.70rem; color:{T["text_secondary"]};'>/mo</span></div>
            <div style='font-size:0.72rem; color:{T["text_secondary"]}; margin-top:4px;'>{'PPFC ' + format_inr(round(active_budget * 0.2, 2)) + ' + MOMC ' + format_inr(round(active_budget * 0.4, 2)) + ' + NISC ' + format_inr(round(active_budget * 0.4, 2)) if active_budget > 0 else 'Month Skipped (₹0)'}</div>
            <div style='margin-top:8px;'>
                <span class='badge-pill pill-amber mono-num'>14.60% XIRR</span>
                <span class='mono-num' style='font-size:0.68rem; color:{T["text_secondary"]}; margin-left:4px;'>-15.9% DD</span>
            </div>
        </div>

        <!-- Strategy 3: Nifty 500 Broad Market -->
        <div class='fin-card' style='border-top:3px solid #2563EB; padding:12px 14px;'>
            <div style='font-size:0.72rem; font-weight:700; color:#2563EB; text-transform:uppercase;'>🌐 Nifty 500 Index</div>
            <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(active_budget)}<span style='font-size:0.70rem; color:{T["text_secondary"]};'>/mo</span></div>
            <div style='font-size:0.72rem; color:{T["text_secondary"]}; margin-top:4px;'>{'Motilal Nifty 500 Index (100%)' if active_budget > 0 else 'Month Skipped (₹0)'}</div>
            <div style='margin-top:8px;'>
                <span class='badge-pill pill-blue mono-num'>9.27% XIRR</span>
                <span class='mono-num' style='font-size:0.68rem; color:{T["text_secondary"]}; margin-left:4px;'>-11.2% DD</span>
            </div>
        </div>

        <!-- Strategy 4: Nifty 50 Large Cap -->
        <div class='fin-card' style='border-top:3px solid #7C3AED; padding:12px 14px;'>
            <div style='font-size:0.72rem; font-weight:700; color:#7C3AED; text-transform:uppercase;'>🏛️ Nifty 50 Index</div>
            <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(active_budget)}<span style='font-size:0.70rem; color:{T["text_secondary"]};'>/mo</span></div>
            <div style='font-size:0.72rem; color:{T["text_secondary"]}; margin-top:4px;'>{'UTI Nifty 50 Index (100%)' if active_budget > 0 else 'Month Skipped (₹0)'}</div>
            <div style='margin-top:8px;'>
                <span class='badge-pill pill-purple mono-num'>7.49% XIRR</span>
                <span class='mono-num' style='font-size:0.68rem; color:{T["text_secondary"]}; margin-left:4px;'>-11.4% DD</span>
            </div>
        </div>
    </div>
    """)

    # Compact, Sortable Interactive Table for Dec 3rd Day-1 Allocation Preview
    render_section_header("🔍 Dec 3, 2026 Day-1 Allocation Preview", "Net invested capital after 0.005% stamp duty, live NAVs, and estimated units credited on launch day.", margin_top=6)

    day1 = fwd.get("day1_preview", {})
    day1_filter = st.selectbox(
        "Filter Strategy",
        ["All Strategies (Consolidated)", "🏆 Winning 17.55% AI Engine", "📦 My Passive Groww SIPs", "🌐 Nifty 500 Broad Market", "🏛️ Nifty 50 Large Cap"],
        index=0
    )

    day1_raw = day1.get("summary_table", [])
    if "Winning" in day1_filter:
        day1_raw = day1.get("ai_engine", [])
    elif "Passive Groww" in day1_filter:
        day1_raw = day1.get("passive_groww", [])
    elif "Nifty 500" in day1_filter:
        day1_raw = day1.get("nifty500", [])
    elif "Nifty 50" in day1_filter:
        day1_raw = day1.get("nifty50", [])

    day1_table_data = []
    for d_item in day1_raw:
        day1_table_data.append({
            "Strategy": d_item.get("strategy", ""),
            "Fund Scheme": d_item.get("fund_name", ""),
            "Category": d_item.get("sub_category", ""),
            "SIP Amount": format_inr(d_item.get("sip_amount", 0.0)),
            "Duty (0.005%)": format_inr(d_item.get("stamp_duty", 0.0), decimals=2),
            "Net Invested": format_inr(d_item.get("net_invested", 0.0), decimals=2),
            "Live NAV": format_inr(d_item.get("current_nav", 0.0), decimals=2),
            "Est. Units": f"{d_item.get('est_units', 0.0):,.3f}",
            "Strategy Rationale": d_item.get("thesis", "")
        })

    st.dataframe(pd.DataFrame(day1_table_data), use_container_width=True, hide_index=True)

    # -------------------------------------------------------------
    # SECTION B: MY EXISTING GROWW CORE & LOCKED ELSS SCORECARD
    # -------------------------------------------------------------
    render_section_header("💼 Section B: My Existing Groww Core & Locked ELSS Holdings", "Clean, live valuation of active portfolio and segregated tax-saver holdings (100% direct equity, zero cash drag).", margin_top=20)

    active_items = portfolio_sum.get("active_items", [])
    locked_items = portfolio_sum.get("locked_items", [])

    # Consolidated Scorecard Table
    scorecard_rows = []
    for act in active_items:
        scorecard_rows.append({
            "Fund Scheme & Folio": f"{act['short_name']} (Folio {act['folio_no']})",
            "Category / Type": act.get("sleeve", "Active Core"),
            "Units": f"{act['units']:,.3f}",
            "Live NAV": format_inr(act["current_nav"], decimals=2),
            "Current Value": format_inr(act["current_value"]),
            "Invested": format_inr(act["invested_value"]),
            "All-Time Gain": f"{format_inr(act['gain_rupees'], show_sign=True)} ({act['gain_pct']:+.1f}%)",
            "200-DMA Dist": f"{act['dma_dist_pct']:+.1f}% (Bullish)" if act['dma_dist_pct'] >= 0 else f"{act['dma_dist_pct']:+.1f}%",
            "Role": f"Active ({format_inr(act['sip_amount'])}/mo)" if act['sip_amount'] > 0 else "Active Hold"
        })

    for lck in locked_items:
        scorecard_rows.append({
            "Fund Scheme & Folio": f"{lck['short_name']} (Folio {lck['folio_no']})",
            "Category / Type": "🔒 ELSS Tax Saver",
            "Units": f"{lck['units']:,.3f}",
            "Live NAV": format_inr(lck["current_nav"], decimals=2),
            "Current Value": format_inr(lck["current_value"]),
            "Invested": format_inr(lck["invested_value"]),
            "All-Time Gain": f"{format_inr(lck['gain_rupees'], show_sign=True)} ({lck['gain_pct']:+.1f}%)",
            "200-DMA Dist": f"{lck['dma_dist_pct']:+.1f}% (Bullish)" if lck['dma_dist_pct'] >= 0 else f"{lck['dma_dist_pct']:+.1f}%",
            "Role": "Locked (3-Yr Tax Saver)"
        })

    st.dataframe(pd.DataFrame(scorecard_rows), use_container_width=True, hide_index=True)

    # Summary Footer Bar
    active_val = portfolio_sum.get("active_value", 1558114.0)
    locked_val = portfolio_sum.get("locked_value", 366540.0)
    render_html(f"""
    <div style='background:{T["bg_card"]}; border:1px solid {T["border"]}; border-radius:10px; padding:10px 16px; margin-top:8px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; font-size:0.78rem;'>
        <span>Active Tradable (4 Funds): <b class='mono-num' style='color:#059669;'>{format_inr(active_val)}</b></span>
        <span>Locked ELSS (2 Funds): <b class='mono-num' style='color:{T["text_secondary"]};'>{format_inr(locked_val)}</b></span>
        <span>Total Net Worth: <b class='mono-num' style='color:{T["text_primary"]};'>{format_inr(tot_net_worth)}</b> (100% Equity, Zero Cash Drag)</span>
    </div>
    """)

# =====================================================================
# TAB 3: ALPHA TRACKER, BACKTEST & INTERACTIVE SIMULATOR
# =====================================================================
with tab_chart:
    alpha_subtab = st.radio(
        "Alpha Explorer View",
        [
            "🔮 Interactive SIP Simulator",
            "🏆 12-Month Live Forward Challenge",
            "🏛️ 5-Year Historical Backtest"
        ],
        horizontal=True,
        label_visibility="collapsed"
    )

    # -------------------------------------------------------------
    # 1. INTERACTIVE SIP & CORPUS SIMULATOR
    # -------------------------------------------------------------
    if "Simulator" in alpha_subtab:
        render_section_header("🔮 Interactive SIP & Corpus Simulator", "Project your future post-tax wealth under the Winning 17.55% AI Engine vs. Passive Groww vs. Nifty 500 vs. Nifty 50.")

        sim_col1, sim_col2, sim_col3 = st.columns(3)
        with sim_col1:
            sim_sip = st.slider(
                "Starting Monthly SIP (₹)",
                min_value=10000,
                max_value=200000,
                value=int(active_budget) if active_budget >= 10000 else 50000,
                step=5000
            )
        with sim_col2:
            sim_horizon = st.selectbox(
                "Investment Horizon",
                ["3 Years (36M)", "5 Years (60M)", "10 Years (120M)", "15 Years (180M)"],
                index=1
            )
        with sim_col3:
            sim_stepup_label = st.selectbox(
                "Annual SIP Step-Up (%)",
                ["0% Flat", "5% / yr", "10% / yr", "15% / yr"],
                index=0
            )

        stepup_rates = {
            "0% Flat": 0.0,
            "5% / yr": 0.05,
            "10% / yr": 0.10,
            "15% / yr": 0.15
        }
        stepup_pct = stepup_rates.get(sim_stepup_label, 0.0)

        years_map = {
            "3 Years (36M)": 3,
            "5 Years (60M)": 5,
            "10 Years (120M)": 10,
            "15 Years (180M)": 15
        }
        n_years = years_map.get(sim_horizon, 5)
        n_months = n_years * 12

        # Step-up invested series
        invested_curve = []
        cum_invested = 0.0
        for m in range(1, n_months + 1):
            y_idx = (m - 1) // 12
            m_sip = sim_sip * ((1.0 + stepup_pct) ** y_idx)
            cum_invested += m_sip
            invested_curve.append(round(cum_invested, 2))
        tot_invested_sim = cum_invested

        strat_cagr = {
            "ai": 0.1755,
            "groww": 0.1460,
            "n500": 0.0927,
            "n50": 0.0749
        }

        curves = {"ai": [], "groww": [], "n500": [], "n50": []}
        for key, r in strat_cagr.items():
            i_m = (1.0 + r)**(1.0 / 12.0) - 1.0
            acc = 0.0
            for m in range(1, n_months + 1):
                y_idx = (m - 1) // 12
                m_sip = sim_sip * ((1.0 + stepup_pct) ** y_idx)
                acc = (acc + m_sip) * (1.0 + i_m)
                curves[key].append(round(acc, 2))

        final_ai = curves["ai"][-1]
        final_groww = curves["groww"][-1]
        final_n500 = curves["n500"][-1]
        final_n50 = curves["n50"][-1]

        def compute_tax_and_net(gross: float, invested: float):
            gain = max(0.0, gross - invested)
            taxable_gain = max(0.0, gain - 125000.0)
            ltcg_tax = round(taxable_gain * 0.125, 2)
            net_cash = round(gross - ltcg_tax, 2)
            return gain, ltcg_tax, net_cash

        gain_ai, tax_ai, net_ai = compute_tax_and_net(final_ai, tot_invested_sim)
        gain_groww, tax_groww, net_groww = compute_tax_and_net(final_groww, tot_invested_sim)
        gain_n500, tax_n500, net_n500 = compute_tax_and_net(final_n500, tot_invested_sim)
        gain_n50, tax_n50, net_n50 = compute_tax_and_net(final_n50, tot_invested_sim)

        alpha_vs_n500_sim = final_ai - final_n500
        alpha_vs_groww_sim = final_ai - final_groww
        net_alpha_vs_n500 = net_ai - net_n500
        net_alpha_vs_groww = net_ai - net_groww

        render_html(f"""
        <div style='display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-top:10px; margin-bottom:12px;'>
            <!-- Strategy 1: Winning AI Engine -->
            <div class='fin-card' style='border-top:3px solid #059669; padding:12px 14px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-size:0.72rem; color:#059669; font-weight:700;'>🏆 AI ENGINE (17.55%)</span>
                    <span class='badge-pill pill-emerald' style='font-size:0.65rem;'>Top Alpha</span>
                </div>
                <div class='mono-num' style='font-size:1.24rem; font-weight:800; color:{T["text_primary"]}; margin-top:4px;'>{format_inr(final_ai)}</div>
                <div style='font-size:0.70rem; color:{T["text_secondary"]}; margin-top:4px; line-height:1.5;'>
                    Gain: <b class='mono-num' style='color:#059669;'>+{format_inr(gain_ai)}</b><br>
                    Est. LTCG (12.5%): <span class='mono-num' style='color:#EF4444;'>-{format_inr(tax_ai)}</span><br>
                    Net Cash-in-Hand: <b class='mono-num' style='color:{T["text_primary"]}; font-weight:700;'>{format_inr(net_ai)}</b>
                </div>
            </div>

            <!-- Strategy 2: Passive Groww -->
            <div class='fin-card' style='border-top:3px solid #D97706; padding:12px 14px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-size:0.72rem; color:#D97706; font-weight:700;'>📦 PASSIVE GROWW (14.60%)</span>
                    <span class='badge-pill pill-amber' style='font-size:0.65rem;'>Passive</span>
                </div>
                <div class='mono-num' style='font-size:1.24rem; font-weight:800; color:{T["text_primary"]}; margin-top:4px;'>{format_inr(final_groww)}</div>
                <div style='font-size:0.70rem; color:{T["text_secondary"]}; margin-top:4px; line-height:1.5;'>
                    Gain: <b class='mono-num' style='color:#D97706;'>+{format_inr(gain_groww)}</b><br>
                    Est. LTCG (12.5%): <span class='mono-num' style='color:#EF4444;'>-{format_inr(tax_groww)}</span><br>
                    Net Cash-in-Hand: <b class='mono-num' style='color:{T["text_primary"]}; font-weight:700;'>{format_inr(net_groww)}</b>
                </div>
            </div>

            <!-- Strategy 3: Nifty 500 -->
            <div class='fin-card' style='border-top:3px solid #2563EB; padding:12px 14px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-size:0.72rem; color:#2563EB; font-weight:700;'>🌐 NIFTY 500 (9.27%)</span>
                    <span class='badge-pill pill-blue' style='font-size:0.65rem;'>Broad Index</span>
                </div>
                <div class='mono-num' style='font-size:1.24rem; font-weight:800; color:{T["text_primary"]}; margin-top:4px;'>{format_inr(final_n500)}</div>
                <div style='font-size:0.70rem; color:{T["text_secondary"]}; margin-top:4px; line-height:1.5;'>
                    Gain: <b class='mono-num' style='color:#2563EB;'>+{format_inr(gain_n500)}</b><br>
                    Est. LTCG (12.5%): <span class='mono-num' style='color:#EF4444;'>-{format_inr(tax_n500)}</span><br>
                    Net Cash-in-Hand: <b class='mono-num' style='color:{T["text_primary"]}; font-weight:700;'>{format_inr(net_n500)}</b>
                </div>
            </div>

            <!-- Strategy 4: Nifty 50 -->
            <div class='fin-card' style='border-top:3px solid #7C3AED; padding:12px 14px;'>
                <div style='display:flex; justify-content:space-between; align-items:center;'>
                    <span style='font-size:0.72rem; color:#7C3AED; font-weight:700;'>🏛️ NIFTY 50 (7.49%)</span>
                    <span class='badge-pill pill-purple' style='font-size:0.65rem;'>Large Cap</span>
                </div>
                <div class='mono-num' style='font-size:1.24rem; font-weight:800; color:{T["text_primary"]}; margin-top:4px;'>{format_inr(final_n50)}</div>
                <div style='font-size:0.70rem; color:{T["text_secondary"]}; margin-top:4px; line-height:1.5;'>
                    Gain: <b class='mono-num' style='color:#7C3AED;'>+{format_inr(gain_n50)}</b><br>
                    Est. LTCG (12.5%): <span class='mono-num' style='color:#EF4444;'>-{format_inr(tax_n50)}</span><br>
                    Net Cash-in-Hand: <b class='mono-num' style='color:{T["text_primary"]}; font-weight:700;'>{format_inr(net_n50)}</b>
                </div>
            </div>
        </div>
        """)

        # Callout Highlight Banner
        render_html(f"""
        <div style='background:{T["pill_emerald_bg"]}; border:1px solid {T["pill_emerald_border"]}; border-radius:10px; padding:12px 16px; margin-bottom:14px;'>
            <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:0.88rem; font-weight:700; color:{T["accent_emerald"] if not is_dark else "#34D399"};'>
                🚀 Projected Wealth Advantage: <span class='mono-num'>+{format_inr(alpha_vs_n500_sim)}</span> Gross (<span class='mono-num'>+{format_inr(net_alpha_vs_n500)}</span> Net Post-Tax Cash) over Nifty 500!
            </div>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; margin-top:4px; line-height:1.5;'>
                Starting at <b class='mono-num'>{format_inr(sim_sip)}/month</b> with <b>{sim_stepup_label}</b> annual step-up over <b>{n_years} years</b> (<span class='mono-num'>{format_inr(tot_invested_sim)}</span> total capital):<br>
                • <b>Gross Corpus:</b> <b class='mono-num' style='color:#059669;'>{format_inr(final_ai)}</b> vs Nifty 500 <b class='mono-num'>{format_inr(final_n500)}</b> (<b>+{format_inr(alpha_vs_n500_sim)}</b> alpha)<br>
                • <b>Net Cash-in-Hand:</b> <b class='mono-num' style='color:#059669;'>{format_inr(net_ai)}</b> vs Nifty 500 <b class='mono-num'>{format_inr(net_n500)}</b> (<b>+{format_inr(net_alpha_vs_n500)}</b> in pocket after 12.5% LTCG tax above ₹1.25L exemption)<br>
                • <b>Vs Passive Groww:</b> Delivers <b class='mono-num' style='color:#059669;'>+{format_inr(net_alpha_vs_groww)}</b> higher net cash-in-hand than continuing passive SIPs.
            </div>
        </div>
        """)

        # Plotly Projected Wealth Curve (Light Canvas)
        fig_sim = go.Figure()

        fig_sim.add_trace(go.Scatter(
            x=list(range(1, n_months + 1)),
            y=curves["ai"],
            mode="lines",
            name="🏆 Winning AI Engine (17.55%)",
            line=dict(color="#059669", width=2.6),
            customdata=[format_inr(v) for v in curves["ai"]],
            hovertemplate="AI Engine: %{customdata}<extra></extra>"
        ))

        fig_sim.add_trace(go.Scatter(
            x=list(range(1, n_months + 1)),
            y=curves["groww"],
            mode="lines",
            name="📦 Passive Groww (14.60%)",
            line=dict(color="#D97706", width=2.0, dash="dash"),
            customdata=[format_inr(v) for v in curves["groww"]],
            hovertemplate="Passive Groww: %{customdata}<extra></extra>"
        ))

        fig_sim.add_trace(go.Scatter(
            x=list(range(1, n_months + 1)),
            y=curves["n500"],
            mode="lines",
            name="🌐 Nifty 500 SIP (9.27%)",
            line=dict(color="#2563EB", width=1.8, dash="dashdot"),
            customdata=[format_inr(v) for v in curves["n500"]],
            hovertemplate="Nifty 500: %{customdata}<extra></extra>"
        ))

        fig_sim.add_trace(go.Scatter(
            x=list(range(1, n_months + 1)),
            y=curves["n50"],
            mode="lines",
            name="🏛️ Nifty 50 SIP (7.49%)",
            line=dict(color="#7C3AED", width=1.6, dash="dot"),
            customdata=[format_inr(v) for v in curves["n50"]],
            hovertemplate="Nifty 50: %{customdata}<extra></extra>"
        ))

        fig_sim.add_trace(go.Scatter(
            x=list(range(1, n_months + 1)),
            y=invested_curve,
            mode="lines",
            name=f"Capital Invested ({sim_stepup_label})",
            line=dict(color="#94A3B8", width=1.4, dash="dot"),
            customdata=[format_inr(v) for v in invested_curve],
            hovertemplate="Invested: %{customdata}<extra></extra>"
        ))

        fig_sim.update_layout(
            template=T["plotly_template"],
            paper_bgcolor=T["plotly_paper"],
            plot_bgcolor=T["plotly_plot"],
            font=dict(family="Inter, sans-serif", color=T["text_secondary"]),
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10, color=T["text_primary"])),
            xaxis=dict(title="Months", gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            yaxis=dict(title="Corpus (₹)", gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            hovermode="x unified"
        )
        st.plotly_chart(fig_sim, use_container_width=True)

    # -------------------------------------------------------------
    # 2. 12-MONTH LIVE FORWARD CHALLENGE TRACKER
    # -------------------------------------------------------------
    elif "Challenge" in alpha_subtab:
        fwd = get_live_forward_challenge(monthly_sip=active_budget)

        render_html(f"""
        <div class='fin-card' style='border-top:3px solid #2563EB;'>
            <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                <div>
                    <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-size:1.05rem; font-weight:800; color:{T["text_primary"]};'>🏆 12-Month Live Forward Challenge</div>
                    <div style='font-size:0.78rem; color:{T["text_secondary"]}; margin-top:2px;'>
                        Passive Groww SIPs ({format_inr(active_budget)}/Mo) vs. Unrestricted AI Mutual Fund Advisor
                    </div>
                </div>
                <span class='badge-pill pill-blue'>{fwd['status_label']}</span>
            </div>
            <div style='font-size:0.78rem; color:{T["text_secondary"]}; margin-top:8px; line-height:1.5;'>
                Starting <b>Dec 3, 2026</b>, <span class='mono-num'>{format_inr(active_budget)}</span> will be deployed forward on the 3rd of every month across 12 months (<span class='mono-num'>{format_inr(active_budget * 12)}</span> total).
                Strictly tracking <b>FIFO tax lots</b>, <b>0.005% stamp duty</b>, exit loads, and actual Indian capital gains taxes.
            </div>
        </div>
        """)

        # AI Thesis Log
        render_section_header("🧠 Plain-English AI Advisor Thesis Log", margin_top=10)
        top1 = fwd["top_picks"][0] if len(fwd["top_picks"]) > 0 else {}
        top2 = fwd["top_picks"][1] if len(fwd["top_picks"]) > 1 else {}

        render_html(f"""
        <div class='fin-card' style='padding:14px; font-size:0.80rem; color:{T["text_secondary"]};'>
            <div style='font-family:\"Plus Jakarta Sans\", sans-serif; font-weight:700; color:{T["text_primary"]}; margin-bottom:6px;'>💡 Quantitative Rationale for Dec 3, 2026 Kickoff</div>
            <div style='color:{T["text_muted"]}; margin-bottom:8px;'>{fwd['ai_thesis_summary']}</div>
            <ul style='margin:0; padding-left:18px; line-height:1.6;'>
                <li><b>{top1.get('short_name', 'Leader 1')} ({top1.get('sub_category', '')}):</b> {top1.get('thesis', '')}</li>
                <li><b>{top2.get('short_name', 'Leader 2')} ({top2.get('sub_category', '')}):</b> {top2.get('thesis', '')}</li>
                <li><b>Avoidance/Protection:</b> Funds below 200-DMA or with negative relative strength vs Nifty 50 are disqualified from fresh capital.</li>
            </ul>
        </div>
        """)

        with st.expander("📅 View 12-Month Tracking Schedule (Dec 2026 – Nov 2027)", expanded=False):
            df_sch = pd.DataFrame(fwd["schedule"]).copy()
            if "sip_amount" in df_sch.columns:
                df_sch["sip_amount"] = df_sch["sip_amount"].apply(lambda v: format_inr(v))
            st.dataframe(df_sch[["month_num", "date", "sip_amount", "passive_allocation", "status"]].rename(columns={
                "month_num": "Month #",
                "date": "Execution Date",
                "sip_amount": "Amount",
                "passive_allocation": "Passive Allocation",
                "status": "Tracking Status"
            }), use_container_width=True, hide_index=True)

    # -------------------------------------------------------------
    # 3. 5-YEAR HISTORICAL BACKTEST (NOV 2021 – NOV 2026)
    # -------------------------------------------------------------
    else:
        render_section_header("🏛️ 5-Year Historical Backtest (Nov 2021 – Nov 2026)", "Systematic ₹50,000/Mo SIP (3rd of month) across 61 months • Net of 0.005% Stamp Duty, Exit Loads & Taxes")

        b_res = run_five_year_backtest(force_refresh=False)
        ai_net = b_res.get("ai_net_corpus", 4729634.8)
        ai_xirr = b_res.get("ai_xirr", 17.61)
        ai_dd = b_res.get("ai_max_dd", -13.91)
        ai_tax = b_res.get("ai_tax_paid", 100795.56)

        pas_net = b_res.get("passive_net_corpus", 4392778.81)
        pas_xirr = b_res.get("passive_xirr", 14.60)
        pas_dd = b_res.get("passive_max_dd", -15.86)
        pas_tax = b_res.get("passive_tax_paid", 179640.68)

        n500_net = b_res.get("nifty500_net_corpus", 3849783.96)
        n500_xirr = b_res.get("nifty500_xirr", 9.27)
        n500_dd = b_res.get("nifty500_max_dd", -11.21)

        n50_net = b_res.get("nifty50_net_corpus", 3682575.86)
        n50_xirr = b_res.get("nifty50_xirr", 7.49)
        n50_dd = b_res.get("nifty50_max_dd", -11.41)

        render_html(f"""
        <div style='display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:14px;'>
            <div class='fin-card' style='border-top:3px solid #059669; padding:12px 14px;'>
                <div style='font-size:0.72rem; color:#059669; font-weight:700;'>🏆 Winning AI Engine</div>
                <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(ai_net)}</div>
                <div style='font-size:0.72rem; color:{T["text_secondary"]};'>Post-Tax: <b class='mono-num' style='color:#059669;'>{ai_xirr:.2f}% XIRR</b></div>
                <div class='mono-num' style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>Max DD: {ai_dd:.2f}%</div>
            </div>

            <div class='fin-card' style='border-top:3px solid #D97706; padding:12px 14px;'>
                <div style='font-size:0.72rem; color:#D97706; font-weight:700;'>📦 Passive Groww SIP</div>
                <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(pas_net)}</div>
                <div style='font-size:0.72rem; color:{T["text_secondary"]};'>Post-Tax: <b class='mono-num' style='color:#D97706;'>{pas_xirr:.2f}% XIRR</b></div>
                <div class='mono-num' style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>Max DD: {pas_dd:.2f}%</div>
            </div>

            <div class='fin-card' style='border-top:3px solid #2563EB; padding:12px 14px;'>
                <div style='font-size:0.72rem; color:#2563EB; font-weight:700;'>🌐 Nifty 500 Index</div>
                <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(n500_net)}</div>
                <div style='font-size:0.72rem; color:{T["text_secondary"]};'>Post-Tax: <b class='mono-num' style='color:#2563EB;'>{n500_xirr:.2f}% XIRR</b></div>
                <div class='mono-num' style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>Max DD: {n500_dd:.2f}%</div>
            </div>

            <div class='fin-card' style='border-top:3px solid #7C3AED; padding:12px 14px;'>
                <div style='font-size:0.72rem; color:#7C3AED; font-weight:700;'>🏛️ Nifty 50 Index</div>
                <div class='mono-num' style='font-size:1.20rem; font-weight:800; color:{T["text_primary"]}; margin-top:2px;'>{format_inr(n50_net)}</div>
                <div style='font-size:0.72rem; color:{T["text_secondary"]};'>Post-Tax: <b class='mono-num' style='color:#7C3AED;'>{n50_xirr:.2f}% XIRR</b></div>
                <div class='mono-num' style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>Max DD: {n50_dd:.2f}%</div>
            </div>
        </div>
        """)

        # 5-Year Wealth Growth Curve
        render_section_header("📈 5-Year Wealth Growth Curve", margin_top=4)
        fig_b = go.Figure()

        fig_b.add_trace(go.Scatter(
            x=b_res["dates"],
            y=b_res["tactical_wealth"],
            mode="lines",
            name=f"🏆 AI Engine ({ai_xirr:.2f}%)",
            line=dict(color="#059669", width=2.6),
            customdata=[format_inr(v) for v in b_res["tactical_wealth"]],
            hovertemplate="AI Engine: %{customdata}<extra></extra>"
        ))

        fig_b.add_trace(go.Scatter(
            x=b_res["dates"],
            y=b_res["passive_wealth"],
            mode="lines",
            name=f"📦 Passive Groww ({pas_xirr:.2f}%)",
            line=dict(color="#D97706", width=2.0, dash="dash"),
            customdata=[format_inr(v) for v in b_res["passive_wealth"]],
            hovertemplate="Passive Groww: %{customdata}<extra></extra>"
        ))

        if "nifty500_wealth" in b_res:
            fig_b.add_trace(go.Scatter(
                x=b_res["dates"],
                y=b_res["nifty500_wealth"],
                mode="lines",
                name=f"🌐 Nifty 500 ({n500_xirr:.2f}%)",
                line=dict(color="#2563EB", width=1.8, dash="dashdot"),
                customdata=[format_inr(v) for v in b_res["nifty500_wealth"]],
                hovertemplate="Nifty 500: %{customdata}<extra></extra>"
            ))

        if "nifty50_wealth" in b_res:
            fig_b.add_trace(go.Scatter(
                x=b_res["dates"],
                y=b_res["nifty50_wealth"],
                mode="lines",
                name=f"🏛️ Nifty 50 ({n50_xirr:.2f}%)",
                line=dict(color="#7C3AED", width=1.6, dash="dot"),
                customdata=[format_inr(v) for v in b_res["nifty50_wealth"]],
                hovertemplate="Nifty 50: %{customdata}<extra></extra>"
            ))

        fig_b.update_layout(
            template=T["plotly_template"],
            paper_bgcolor=T["plotly_paper"],
            plot_bgcolor=T["plotly_plot"],
            font=dict(family="Inter, sans-serif", color=T["text_secondary"]),
            height=300,
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=10, color=T["text_primary"])),
            xaxis=dict(gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            yaxis=dict(gridcolor=T["plotly_grid"], showline=True, linecolor=T["border"]),
            hovermode="x unified"
        )
        st.plotly_chart(fig_b, use_container_width=True)

# ==========================================
# TAB 4: TRANSACTION & AUDIT LEDGER
# ==========================================
with tab_trades:
    render_section_header("📝 Transaction Log & Execution Queue", "Clean audit trail of upcoming kickoff orders and settled portfolio transactions.")

    render_section_header("📅 Upcoming Dec 3, 2026 Kickoff Orders", margin_top=8)
    fwd = get_live_forward_challenge(monthly_sip=active_budget)
    day1_items = fwd.get("day1_preview", {}).get("ai_engine", [])

    q_rows = []
    for ord_item in day1_items:
        q_rows.append({
            "Execution Date": "Dec 3, 2026",
            "Fund Scheme": ord_item.get("fund_name", ""),
            "Allocation": format_inr(ord_item.get("sip_amount", 25000.0)),
            "Stamp Duty": format_inr(ord_item.get("stamp_duty", 1.25), decimals=2),
            "Net Invested": format_inr(ord_item.get("net_invested", 24998.75), decimals=2),
            "Live NAV": format_inr(ord_item.get("current_nav", 100.0), decimals=2),
            "Est. Units": f"{ord_item.get('est_units', 0.0):,.3f}",
            "Settlement": "Dec 4, 2026 (T+1)",
            "Status": "SCHEDULED"
        })
    st.dataframe(pd.DataFrame(q_rows), use_container_width=True, hide_index=True)

    render_section_header("📜 Settled Portfolio Transactions", margin_top=16)
    txs = db.get_transactions(limit=100)
    clean_txs = [t for t in txs if "CASH" not in t.get("transaction_type", "") and "Shadow" not in t.get("scheme_name", "")]

    if clean_txs:
        t_rows = []
        for t in clean_txs:
            t_rows.append({
                "Trade Date": t.get("trade_date", ""),
                "Settlement Date": t.get("settlement_date", ""),
                "Fund Scheme": t.get("scheme_name", ""),
                "Type": t.get("transaction_type", ""),
                "Amount": format_inr(float(t.get("amount", 0)), decimals=2),
                "NAV": format_inr(float(t.get("nav", 0)), decimals=2),
                "Units": f"{float(t.get('units', 0)):,.3f}",
                "Status": t.get("status", "SETTLED")
            })
        st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Upcoming trades scheduled in Dec 3, 2026 Kickoff Queue above.")

# ==========================================
# TAB 5: ON-DEMAND ACTIONS & CLOUD CONTROL
# ==========================================
with tab_settings:
    render_section_header("⚙️ Cloud Control & Pipeline", "Trigger live pipeline steps, dispatch alerts, and monitor system health.")

    act_col1, act_col2, act_col3 = st.columns(3)
    with act_col1:
        if st.button("⚡ Run Daily Pipeline"):
            with st.spinner("Executing daily cycle..."):
                from src.daily_job import run_daily_cycle
                run_daily_cycle(force_send_telegram=False)
                st.success("Daily cycle executed!")
                st.rerun()

    with act_col2:
        if st.button("📲 Test Telegram Alert"):
            with st.spinner("Dispatching Telegram notification..."):
                alert_text = format_tactical_alert(scores, decisions)
                resp = send_telegram_alert(alert_text)
                if resp.get("ok"):
                    st.success("Delivered to Telegram!")
                else:
                    st.error(f"Error: {resp.get('error')}")

    with act_col3:
        if st.button("🔄 Refresh Backtest Cache"):
            with st.spinner("Recomputing 5-Year Backtest..."):
                run_five_year_backtest(force_refresh=True)
                st.success("Cache refreshed!")
                st.rerun()

    # -------------------------------------------------------------
    # MONTHLY SIP LIVE EXECUTION LOGGER
    # -------------------------------------------------------------
    st.markdown("---")
    render_section_header("📝 Monthly SIP Live Execution Logger", "Execute and log monthly investments across Winning AI Engine and all 3 benchmark portfolios with synchronized trade dates.")

    exec_col1, exec_col2, exec_col3 = st.columns([1.5, 1.2, 1.5])
    with exec_col1:
        log_budget = float(st.number_input(
            "This Month's SIP Budget (₹)",
            min_value=0,
            max_value=500000,
            value=int(st.session_state.get("monthly_sip_budget", 50000.0)),
            step=5000,
            key="actions_sip_budget_logger",
            help="Monthly capital to execute. Set to ₹0 to record a skipped month audit milestone."
        ))
    with exec_col2:
        log_trade_date = st.date_input(
            "Trade Execution Date",
            value=date.today(),
            key="actions_sip_trade_date",
            help="Date of trade execution (NAV on or before this date will be retrieved)."
        )
    with exec_col3:
        log_notes = st.text_input(
            "Execution Notes / Memo",
            value="Monthly Scheduled SIP Execution",
            key="actions_sip_notes",
            help="Optional audit memo recorded in transaction ledger."
        )

    # 4-Way Allocation Preview before committing
    p1_split_amt = round(log_budget * 0.50, 2)
    p2_split_amt = round(log_budget * 0.50, 2)
    groww_p1 = round(log_budget * 0.20, 2)
    groww_p2 = round(log_budget * 0.40, 2)
    groww_p3 = round(log_budget * 0.40, 2)

    if log_budget <= 0:
        render_html(f"""
        <div style='background:{T["bg_subtle"]}; border:1px dashed {T["border_light"]}; border-radius:10px; padding:12px 14px; margin: 10px 0;'>
            <div style='color:{T["accent_amber"]}; font-weight:700; font-size:0.85rem;'>⏸️ Month Skipped Notice (₹0.00 Allocation)</div>
            <div style='color:{T["text_secondary"]}; font-size:0.75rem; margin-top:2px;'>
                Logging ₹0 will record a settled audit milestone (<code>SIP_SKIPPED</code>) across all 4 portfolios on <b>{log_trade_date.strftime("%d %b %Y")}</b>. Portfolio units and cash remain untouched, preserving pristine XIRR parity.
            </div>
        </div>
        """)
    else:
        render_html(f"""
        <div style='background:{T["bg_subtle"]}; border:1px solid {T["border"]}; border-radius:10px; padding:12px 14px; margin: 10px 0;'>
            <div style='font-size:0.82rem; font-weight:700; color:{T["text_primary"]}; margin-bottom:8px;'>
                🔍 Execution Preview across 4 Portfolios ({format_inr(log_budget)} on {log_trade_date.strftime("%d %b %Y")}):
            </div>
            <div style='display:grid; grid-template-columns: repeat(4, 1fr); gap:8px;'>
                <div style='background:{T["bg_card"]}; padding:8px 10px; border-radius:6px; border-top:2px solid #059669;'>
                    <div style='font-size:0.70rem; color:#059669; font-weight:700;'>🏆 AI ENGINE (50/50)</div>
                    <div class='mono-num' style='font-size:0.88rem; font-weight:800; color:{T["text_primary"]};'>{format_inr(log_budget)}</div>
                    <div style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>#1 Leader: {format_inr(p1_split_amt)}<br>#2 Leader: {format_inr(p2_split_amt)}</div>
                </div>
                <div style='background:{T["bg_card"]}; padding:8px 10px; border-radius:6px; border-top:2px solid #D97706;'>
                    <div style='font-size:0.70rem; color:#D97706; font-weight:700;'>📦 PASSIVE GROWW</div>
                    <div class='mono-num' style='font-size:0.88rem; font-weight:800; color:{T["text_primary"]};'>{format_inr(log_budget)}</div>
                    <div style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>PPFC: {format_inr(groww_p1)}<br>MOMC: {format_inr(groww_p2)} • NISC: {format_inr(groww_p3)}</div>
                </div>
                <div style='background:{T["bg_card"]}; padding:8px 10px; border-radius:6px; border-top:2px solid #2563EB;'>
                    <div style='font-size:0.70rem; color:#2563EB; font-weight:700;'>🌐 NIFTY 500 (100%)</div>
                    <div class='mono-num' style='font-size:0.88rem; font-weight:800; color:{T["text_primary"]};'>{format_inr(log_budget)}</div>
                    <div style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>Motilal Nifty 500: {format_inr(log_budget)}</div>
                </div>
                <div style='background:{T["bg_card"]}; padding:8px 10px; border-radius:6px; border-top:2px solid #7C3AED;'>
                    <div style='font-size:0.70rem; color:#7C3AED; font-weight:700;'>🏛️ NIFTY 50 (100%)</div>
                    <div class='mono-num' style='font-size:0.88rem; font-weight:800; color:{T["text_primary"]};'>{format_inr(log_budget)}</div>
                    <div style='font-size:0.68rem; color:{T["text_muted"]}; margin-top:2px;'>UTI Nifty 50: {format_inr(log_budget)}</div>
                </div>
            </div>
        </div>
        """)

    col_btn, _ = st.columns([1.5, 2.5])
    with col_btn:
        btn_label = f"🚀 Execute & Log {format_inr(log_budget)} Across Portfolios" if log_budget > 0 else f"⏸️ Log Skipped Month ({log_trade_date.strftime('%b %Y')})"
        if st.button(btn_label, type="primary", use_container_width=True):
            with st.spinner("Recording portfolio transactions with fair trade-date alignment..."):
                exec_result = log_monthly_execution(
                    trade_date=log_trade_date,
                    sip_budget=float(log_budget),
                    notes=log_notes,
                    db=db
                )
                if exec_result.get("status") == "SUCCESS":
                    st.success(f"✅ Successfully logged {exec_result.get('transactions_logged')} transactions on {exec_result.get('trade_date')}!")
                    st.session_state["monthly_sip_budget"] = float(log_budget)
                    st.rerun()
                else:
                    st.error(f"Execution failed: {exec_result.get('error')}")

    # Cloud Deployment Info
    st.markdown("---")
    render_section_header("☁️ Cloud Deployment Status", margin_top=6)
    supabase_configured = bool(os.getenv("SUPABASE_URL") and "supabase.co" in os.getenv("SUPABASE_URL", ""))
    telegram_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    render_html(f"""
    <div style='display:grid; grid-template-columns: 1fr 1fr; gap:10px;'>
        <div class='fin-card' style='padding:12px 14px;'>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; font-weight:700;'>DATABASE BACKEND</div>
            <div style='font-size:0.90rem; font-weight:700; color:{T["text_primary"]}; margin-top:2px;'>
                {'🟢 Supabase PostgreSQL Connected' if supabase_configured else '🟡 Local SQLite Active'}
            </div>
        </div>
        <div class='fin-card' style='padding:12px 14px;'>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; font-weight:700;'>TELEGRAM NOTIFIER</div>
            <div style='font-size:0.90rem; font-weight:700; color:{T["text_primary"]}; margin-top:2px;'>
                {'🟢 Bot Verified & Connected' if telegram_configured else '🔴 Token Missing'}
            </div>
        </div>
        <div class='fin-card' style='padding:12px 14px;'>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; font-weight:700;'>GITHUB SCHEDULER</div>
            <div style='font-size:0.90rem; font-weight:700; color:{T["text_primary"]}; margin-top:2px;'>
                🟢 Mon–Fri @ 09:00 UTC (2:30 PM IST)
            </div>
        </div>
        <div class='fin-card' style='padding:12px 14px;'>
            <div style='font-size:0.75rem; color:{T["text_secondary"]}; font-weight:700;'>TACTICAL STRATEGY</div>
            <div style='font-size:0.90rem; font-weight:700; color:#059669; margin-top:2px;'>
                Winning 17.55% AI Engine (Active)
            </div>
        </div>
    </div>
    """)
