"""Groww Mutual Fund Tactical Engine package."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in [_REPO_ROOT, _SRC_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from src.regime_engine import (
        SLEEVE_CONFIG,
        UNRESTRICTED_UNIVERSE,
        score_unrestricted_universe,
        score_variant_b,
        get_or_create_monthly_signal,
        check_smart_ltcg_switches,
        get_fund_chart_data,
        format_inr,
        update_all_regimes,
        compute_sleeve_regime,
        compute_fund_volatility_90d,
        fetch_universe_navs,
        get_universe_nav_on
    )
except (ImportError, ModuleNotFoundError):
    from regime_engine import (
        SLEEVE_CONFIG,
        UNRESTRICTED_UNIVERSE,
        score_unrestricted_universe,
        score_variant_b,
        get_or_create_monthly_signal,
        check_smart_ltcg_switches,
        get_fund_chart_data,
        format_inr,
        update_all_regimes,
        compute_sleeve_regime,
        compute_fund_volatility_90d,
        fetch_universe_navs,
        get_universe_nav_on
    )

try:
    from src.paper_ledger import (
        evaluate_tactical_decisions,
        calculate_friction_and_drag,
        get_dual_ledger_holdings,
        get_live_portfolio_summary,
        get_live_forward_challenge,
        get_tactical_holdings_lots,
        log_monthly_execution,
        fetch_scheme_nav_history,
        get_nav_on_or_before
    )
except (ImportError, ModuleNotFoundError):
    from paper_ledger import (
        evaluate_tactical_decisions,
        calculate_friction_and_drag,
        get_dual_ledger_holdings,
        get_live_portfolio_summary,
        get_live_forward_challenge,
        get_tactical_holdings_lots,
        log_monthly_execution,
        fetch_scheme_nav_history,
        get_nav_on_or_before
    )

try:
    from src.db import get_db
except (ImportError, ModuleNotFoundError):
    from db import get_db

__all__ = [
    # Regime Engine
    "SLEEVE_CONFIG",
    "UNRESTRICTED_UNIVERSE",
    "score_unrestricted_universe",
    "score_variant_b",
    "get_or_create_monthly_signal",
    "check_smart_ltcg_switches",
    "get_fund_chart_data",
    "format_inr",
    "update_all_regimes",
    "compute_sleeve_regime",
    "compute_fund_volatility_90d",
    "fetch_universe_navs",
    "get_universe_nav_on",
    # Paper Ledger
    "evaluate_tactical_decisions",
    "calculate_friction_and_drag",
    "get_dual_ledger_holdings",
    "get_live_portfolio_summary",
    "get_live_forward_challenge",
    "get_tactical_holdings_lots",
    "log_monthly_execution",
    "fetch_scheme_nav_history",
    "get_nav_on_or_before",
    # Database
    "get_db"
]
