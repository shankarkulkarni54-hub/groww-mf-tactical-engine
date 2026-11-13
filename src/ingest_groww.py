"""Groww holdings Excel file ingestion, filtering, and database seeding."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from typing import List, Dict, Any, Tuple
from src.db import get_db

# Active tradable universe configuration
ACTIVE_UNIVERSE = {
    "Motilal Oswal Midcap Fund Direct Growth": {
        "scheme_code": 127042,
        "sleeve": "MID_SMALL",
        "benchmark_ticker": "^NSEMDCP50",
        "sip_amount": 20000.0,
        "sip_day": 3,
        "tax_category": "DOMESTIC_EQUITY",
        "exit_load_rules": {
            "description": "1% for redemption within 365 days; Nil thereafter",
            "tiers": [
                {"max_days": 365, "load_pct": 1.0},
                {"max_days": 99999, "load_pct": 0.0}
            ]
        }
    },
    "Nippon India Small Cap Fund Direct Growth": {
        "scheme_code": 118778,
        "sleeve": "MID_SMALL",
        "benchmark_ticker": "^CNXSC",
        "sip_amount": 20000.0,
        "sip_day": 3,
        "tax_category": "DOMESTIC_EQUITY",
        "exit_load_rules": {
            "description": "1% for redemption within 365 days; Nil thereafter",
            "tiers": [
                {"max_days": 365, "load_pct": 1.0},
                {"max_days": 99999, "load_pct": 0.0}
            ]
        }
    },
    "Parag Parikh Flexi Cap Fund Direct Growth": {
        "scheme_code": 122639,
        "sleeve": "NIFTY_500",
        "benchmark_ticker": "^CRSLDX",
        "sip_amount": 10000.0,
        "sip_day": 3,
        "tax_category": "DOMESTIC_EQUITY",
        "exit_load_rules": {
            "description": "2% within 365 days; 1% between 365-730 days; Nil thereafter",
            "tiers": [
                {"max_days": 365, "load_pct": 2.0},
                {"max_days": 730, "load_pct": 1.0},
                {"max_days": 99999, "load_pct": 0.0}
            ]
        }
    },
    "Edelweiss US Technology Equity FoF Direct Growth": {
        "scheme_code": 148063,
        "sleeve": "NASDAQ_100",
        "benchmark_ticker": "^NDX",
        "sip_amount": 0.0,
        "sip_day": 3,
        "tax_category": "FOREIGN_FOF",
        "exit_load_rules": {
            "description": "1% within 30 days; Nil thereafter. 24-month LTCG rule applies.",
            "tiers": [
                {"max_days": 30, "load_pct": 1.0},
                {"max_days": 99999, "load_pct": 0.0}
            ]
        }
    }
}


def find_excel_file() -> str:
    """Finds groww_holdings.xlsx or groww_holdings.xlsx.xlsx in data/ directory."""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    candidates = [
        os.path.join(data_dir, "groww_holdings.xlsx"),
        os.path.join(data_dir, "groww_holdings.xlsx.xlsx")
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("Could not find groww_holdings.xlsx in data/ directory")


def parse_groww_excel(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Parses Groww holdings Excel file cleanly:
    - Extracts summary metrics (Total Invested, Current Value, Profit)
    - Dynamically discovers header row (Row 21)
    - Returns list of parsed holding records and summary dictionary.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    sheet = wb.active

    # Extract summary if present
    summary = {}
    for r in range(1, sheet.max_row + 1):
        c1 = sheet.cell(r, 1).value
        if c1 and "Total Investments" in str(c1):
            summary["invested"] = sheet.cell(r + 1, 1).value
            summary["current"] = sheet.cell(r + 1, 2).value
            summary["profit"] = sheet.cell(r + 1, 3).value
            summary["returns_pct"] = sheet.cell(r + 1, 4).value
            summary["xirr"] = sheet.cell(r + 1, 5).value
            break

    # Find holdings table header
    header_row_idx = None
    headers = []
    for r in range(1, sheet.max_row + 1):
        vals = [sheet.cell(r, c).value for c in range(1, sheet.max_column + 1)]
        if any(v and "Scheme Name" in str(v) for v in vals):
            header_row_idx = r
            headers = [str(v).strip() if v is not None else "" for v in vals]
            break

    if not header_row_idx:
        raise ValueError("Could not find table header 'Scheme Name' in Excel")

    holdings = []
    for r in range(header_row_idx + 1, sheet.max_row + 1):
        vals = [sheet.cell(r, c).value for c in range(1, len(headers) + 1)]
        if not vals or not vals[0]:
            continue
        row_dict = {headers[i]: vals[i] for i in range(len(headers)) if i < len(vals) and headers[i]}
        holdings.append(row_dict)

    return holdings, summary


def seed_holdings_to_db(file_path: str = None) -> Dict[str, Any]:
    """
    Ingests Groww Excel file, classifies active tradable universe vs excluded locked funds,
    and seeds database.
    """
    if not file_path:
        file_path = find_excel_file()

    raw_holdings, summary = parse_groww_excel(file_path)
    db = get_db()

    active_records = []
    locked_records = []

    for item in raw_holdings:
        scheme_name = str(item.get("Scheme Name", "")).strip()
        category = str(item.get("Category", "")).strip()
        sub_category = str(item.get("Sub-category", "")).strip()
        amc = str(item.get("AMC", "")).strip()
        folio_no = str(item.get("Folio No.", "")).strip()

        units = float(item.get("Units", 0) or 0)
        invested = float(str(item.get("Invested Value", 0) or 0).replace(",", ""))
        current_val = float(str(item.get("Current Value", 0) or 0).replace(",", ""))
        current_nav = (current_val / units) if units > 0 else 0.0

        # Check if in Active Tradable Universe
        matched_key = None
        for active_name in ACTIVE_UNIVERSE:
            if active_name.lower() in scheme_name.lower() or scheme_name.lower() in active_name.lower():
                matched_key = active_name
                break

        is_elss_or_locked = "elss" in scheme_name.lower() or "elss" in sub_category.lower() or "mirae" in scheme_name.lower()

        if matched_key and not is_elss_or_locked:
            conf = ACTIVE_UNIVERSE[matched_key]
            rec = {
                "scheme_name": matched_key,
                "scheme_code": conf["scheme_code"],
                "amc": amc,
                "category": category,
                "sub_category": sub_category,
                "folio_no": folio_no,
                "units": round(units, 4),
                "invested_value": round(invested, 2),
                "current_nav": round(current_nav, 4),
                "current_value": round(current_val, 2),
                "benchmark_ticker": conf["benchmark_ticker"],
                "sleeve": conf["sleeve"],
                "sip_amount": conf["sip_amount"],
                "sip_day": conf["sip_day"],
                "exit_load_rules": conf["exit_load_rules"],
                "tax_category": conf["tax_category"],
                "is_active": True,
                "is_locked": False
            }
            active_records.append(rec)
        else:
            rec = {
                "scheme_name": scheme_name,
                "scheme_code": 0,
                "amc": amc,
                "category": category,
                "sub_category": sub_category,
                "folio_no": folio_no,
                "units": round(units, 4),
                "invested_value": round(invested, 2),
                "current_nav": round(current_nav, 4),
                "current_value": round(current_val, 2),
                "benchmark_ticker": "EXCLUDED",
                "sleeve": "LOCKED_EXCLUDED",
                "sip_amount": 0.0,
                "sip_day": 0,
                "exit_load_rules": {"note": "Locked ELSS / Non-tradable. Excluded from tactical engine."},
                "tax_category": "DOMESTIC_EQUITY",
                "is_active": False,
                "is_locked": True
            }
            locked_records.append(rec)

    # Upsert all to DB
    all_to_save = active_records + locked_records
    db.upsert_holdings(all_to_save)

    # Save summary state
    db.set_app_state("groww_excel_summary", {
        "raw_summary": summary,
        "active_funds_count": len(active_records),
        "locked_funds_count": len(locked_records),
        "total_active_invested": sum(r["invested_value"] for r in active_records),
        "total_active_current": sum(r["current_value"] for r in active_records),
        "total_locked_invested": sum(r["invested_value"] for r in locked_records),
        "total_locked_current": sum(r["current_value"] for r in locked_records),
    })

    print(f"✅ Ingestion Complete!")
    print(f"   Active Tradable Funds: {len(active_records)}")
    for a in active_records:
        print(f"   - {a['scheme_name']}: ₹{a['current_value']:,.2f} ({a['units']} units) | SIP: ₹{a['sip_amount']:,.0f}")
    print(f"   Excluded Locked Funds: {len(locked_records)}")
    for l in locked_records:
        print(f"   - [LOCKED] {l['scheme_name']}: ₹{l['current_value']:,.2f} ({l['units']} units)")

    return {
        "active": active_records,
        "locked": locked_records,
        "summary": summary
    }


if __name__ == "__main__":
    seed_holdings_to_db()
