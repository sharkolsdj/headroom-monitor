"""Write SimResult to the database and export CSV files."""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
from config import settings  # noqa: E402

from .simulation import SimResult

SYNTHETIC_DIR = ROOT / "data" / "synthetic"


def write_to_db(result: SimResult, verbose: bool = True) -> dict:
    """Bulk-write all tables for one dataset as hm_admin."""
    engine = sa.create_engine(settings.role_dsn("hm_admin"), pool_pre_ping=True)

    with engine.begin() as conn:
        # Clear any existing data for this dataset
        conn.execute(text(
            "DELETE FROM hm.datasets WHERE dataset_id = :did"
        ), {"did": result.dataset_id})

        # Also clear eval tables (no FK cascade from hm)
        for tbl in ("eval.scenario_truth", "eval.future_bank_balances",
                    "eval.future_ar_receipts", "eval.future_ap_payments"):
            conn.execute(text(f"DELETE FROM {tbl} WHERE dataset_id = :did"),
                         {"did": result.dataset_id})
        conn.execute(text(
            "DELETE FROM vault.identity_map WHERE dataset_id = :did"
        ), {"did": result.dataset_id})

    row_counts: dict[str, int] = {}

    with engine.begin() as conn:
        # ── hm.datasets ────────────────────────────────────────────────────────
        conn.execute(text("""
            INSERT INTO hm.datasets (dataset_id, description, seed, as_of_date)
            VALUES (:did, :desc, :seed, :aod)
            ON CONFLICT (dataset_id) DO NOTHING
        """), {
            "did": result.dataset_id,
            "desc": f"Synthetic dataset {result.dataset_id}",
            "seed": result.seed,
            "aod": result.as_of_date,
        })

        # ── hm.bank_accounts ───────────────────────────────────────────────────
        conn.execute(text("""
            INSERT INTO hm.bank_accounts (dataset_id, account_code, currency)
            VALUES (:did, 'ACC_MAIN', 'EUR')
            ON CONFLICT DO NOTHING
        """), {"did": result.dataset_id})

        # ── hm.credit_facilities ──────────────────────────────────────────────
        conn.execute(text("""
            INSERT INTO hm.credit_facilities
                (dataset_id, facility_code, limit_amount, drawn, rate_ref)
            VALUES (:did, :fcode, :limit, 0, :rref)
            ON CONFLICT DO NOTHING
        """), {
            "did": result.dataset_id,
            "fcode": "FAC_REVOLVING",
            "limit": 1_000_000,
            "rref": "euribor_3m",
        })

    # Bulk-load remaining tables with BULK_LOAD GUC
    _bulk_insert(engine, result.dataset_id, "hm.counterparties",
                 result.counterparties_hm, verbose)
    row_counts["counterparties"] = len(result.counterparties_hm)

    _bulk_insert(engine, result.dataset_id, "hm.ar_invoices",
                 result.ar_invoices, verbose)
    row_counts["ar_invoices"] = len(result.ar_invoices)

    _bulk_insert(engine, result.dataset_id, "hm.ar_receipts",
                 result.ar_receipts_hist, verbose)
    row_counts["ar_receipts"] = len(result.ar_receipts_hist)

    _bulk_insert(engine, result.dataset_id, "hm.ap_invoices",
                 result.ap_invoices, verbose)
    row_counts["ap_invoices"] = len(result.ap_invoices)

    _bulk_insert(engine, result.dataset_id, "hm.ap_payments",
                 result.ap_payments_hist, verbose)
    row_counts["ap_payments"] = len(result.ap_payments_hist)

    _bulk_insert(engine, result.dataset_id, "hm.bank_transactions",
                 result.bank_transactions, verbose)
    row_counts["bank_transactions"] = len(result.bank_transactions)

    # Bank balances: use date column from row (end-of-week Sunday)
    _bulk_insert_bank_balances(engine, result.bank_balances, verbose)
    row_counts["bank_balances"] = len(result.bank_balances)

    _bulk_insert_recurring(engine, result.recurring_outflows, verbose)
    row_counts["recurring_outflows"] = len(result.recurring_outflows)

    _bulk_insert(engine, result.dataset_id, "hm.month_closes",
                 result.month_closes, verbose)
    row_counts["month_closes"] = len(result.month_closes)

    if result.close_adjustments:
        _bulk_insert(engine, result.dataset_id, "hm.close_adjustments",
                     result.close_adjustments, verbose)
    row_counts["close_adjustments"] = len(result.close_adjustments)

    # ── eval schema ────────────────────────────────────────────────────────────
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO eval.scenario_truth (dataset_id, truth)
            VALUES (:did, CAST(:truth AS jsonb))
            ON CONFLICT (dataset_id) DO UPDATE SET truth = EXCLUDED.truth
        """), {"did": result.dataset_id,
               "truth": json.dumps(result.scenario_truth)})

    _bulk_insert_eval_receipts(engine, result.future_ar_receipts, verbose)
    row_counts["future_ar_receipts"] = len(result.future_ar_receipts)

    _bulk_insert_eval_payments(engine, result.future_ap_payments, verbose)
    row_counts["future_ap_payments"] = len(result.future_ap_payments)

    _bulk_insert_eval_balances(engine, result.future_bank_balances, verbose)
    row_counts["future_bank_balances"] = len(result.future_bank_balances)

    # ── vault ──────────────────────────────────────────────────────────────────
    _write_vault(engine, result.vault_entries, verbose)
    row_counts["vault_entries"] = len(result.vault_entries)

    if verbose:
        print(f"  DB rows written: { {k: v for k, v in row_counts.items() if v > 0} }")
    return row_counts


def export_csvs(result: SimResult, checks_result: dict, verbose: bool = True) -> Path:
    """Export per-dataset CSV files and README."""
    dataset_dir = SYNTHETIC_DIR / result.dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    # README
    (dataset_dir / "README.txt").write_text(
        "SYNTHETIC DATA\n\n"
        "All records in this directory are entirely fictional and computer-generated.\n"
        "They do not represent any real company, person, or transaction.\n"
        f"Dataset: {result.dataset_id}\n"
        f"As-of date: {result.as_of_date}\n",
        encoding="utf-8",
    )

    # checks.json
    (dataset_dir / "checks.json").write_text(
        json.dumps(checks_result, indent=2, default=str),
        encoding="utf-8",
    )

    # ar_invoices.csv
    _write_csv(dataset_dir / "ar_invoices.csv",
               result.ar_invoices,
               ["invoice_id", "cust_code", "issue_date", "due_date",
                "amount_net", "vat", "amount_gross", "status"])

    # ar_receipts.csv (history only)
    _write_csv(dataset_dir / "ar_receipts.csv",
               result.ar_receipts_hist,
               ["receipt_id", "invoice_id", "date", "amount"])

    # ap_invoices.csv
    _write_csv(dataset_dir / "ap_invoices.csv",
               result.ap_invoices,
               ["invoice_id", "supp_code", "issue_date", "due_date",
                "amount_net", "vat", "amount_gross", "status"])

    # bank_balances.csv (weekly history)
    _write_csv(dataset_dir / "bank_balances.csv",
               result.bank_balances,
               ["week_start", "date", "account_code", "closing_balance"])

    # overview.csv — summary for this dataset
    _write_overview(dataset_dir, result)

    if verbose:
        print(f"  CSVs written to {dataset_dir}")
    return dataset_dir


def export_global_overview(dataset_ids: list[str] | None = None) -> None:
    """Write data/synthetic/overview_all.csv by aggregating per-dataset overview.csv files."""
    from ingestion.generator.scenarios import SCENARIO_IDS
    ids = dataset_ids or SCENARIO_IDS
    SYNTHETIC_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for did in ids:
        overview_path = SYNTHETIC_DIR / did / "overview.csv"
        if not overview_path.exists():
            continue
        metrics: dict[str, str] = {}
        with overview_path.open(encoding="utf-8") as f:
            for rec in csv.DictReader(f):
                metrics[rec["metric"]] = rec["value"]
        rows.append({
            "dataset_id": did,
            "total_revenue":      metrics.get("total_revenue", ""),
            "total_profit":       metrics.get("total_profit", ""),
            "as_of_balance":      metrics.get("as_of_balance", ""),
            "ar_invoice_count":   metrics.get("ar_invoice_count", ""),
            "top20_revenue_share": metrics.get("top20_revenue_share", ""),
        })
    _write_csv(SYNTHETIC_DIR / "overview_all.csv", rows,
               ["dataset_id", "total_revenue", "total_profit", "as_of_balance",
                "ar_invoice_count", "top20_revenue_share"])


# ── internal bulk writers ─────────────────────────────────────────────────────

def _bulk_insert(engine: sa.Engine, dataset_id: str, table: str,
                 rows: list[dict], verbose: bool) -> None:
    if not rows:
        return

    with engine.begin() as conn:
        conn.execute(text("SET hm.bulk_load = 'on'"))
        conn.execute(text(f"SET hm.bulk_row_count = '{len(rows)}'"))

        if table == "hm.ar_invoices":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.ar_invoices
                        (dataset_id, invoice_id, cust_code, issue_date, due_date,
                         amount_net, vat, amount_gross, status)
                    VALUES (:did, :inv_id, :cust, :iss, :due, :net, :vat, :gross, :status)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "inv_id": r["invoice_id"],
                       "cust": r["cust_code"], "iss": r["issue_date"],
                       "due": r["due_date"], "net": r["amount_net"],
                       "vat": r["vat"], "gross": r["amount_gross"],
                       "status": r.get("status", "open")})

        elif table == "hm.ar_receipts":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.ar_receipts
                        (dataset_id, receipt_id, invoice_id, date, amount)
                    VALUES (:did, :rid, :iid, :dt, :amt)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "rid": r["receipt_id"],
                       "iid": r["invoice_id"], "dt": r["date"], "amt": r["amount"]})

        elif table == "hm.ap_invoices":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.ap_invoices
                        (dataset_id, invoice_id, supp_code, issue_date, due_date,
                         amount_net, vat, amount_gross, status)
                    VALUES (:did, :inv_id, :supp, :iss, :due, :net, :vat, :gross, :status)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "inv_id": r["invoice_id"],
                       "supp": r["supp_code"], "iss": r["issue_date"],
                       "due": r["due_date"], "net": r["amount_net"],
                       "vat": r["vat"], "gross": r["amount_gross"],
                       "status": r.get("status", "open")})

        elif table == "hm.ap_payments":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.ap_payments
                        (dataset_id, payment_id, invoice_id, date, amount)
                    VALUES (:did, :pid, :iid, :dt, :amt)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "pid": r["payment_id"],
                       "iid": r["invoice_id"], "dt": r["date"], "amt": r["amount"]})

        elif table == "hm.bank_transactions":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.bank_transactions
                        (dataset_id, txn_id, account_code, date, amount,
                         category, ref_type, ref_id)
                    VALUES (:did, :tid, :acc, :dt, :amt, :cat, :rtype, :rid)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "tid": r["txn_id"],
                       "acc": r["account_code"], "dt": r["date"], "amt": r["amount"],
                       "cat": r["category"], "rtype": r["ref_type"], "rid": r["ref_id"]})

        elif table == "hm.counterparties":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.counterparties
                        (dataset_id, code, kind, nace, segment,
                         size_band, payment_terms_days, onboarded_on)
                    VALUES (:did, :code, :kind, :nace, :seg, :band, :terms, :ood)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "code": r["code"], "kind": r["kind"],
                       "nace": r.get("nace"), "seg": r.get("segment"),
                       "band": r.get("size_band"), "terms": r.get("payment_terms_days"),
                       "ood": r.get("onboarded_on")})

        elif table == "hm.month_closes":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.month_closes
                        (dataset_id, month, close_booked_on,
                         revenue_booked, cogs, opex, profit)
                    VALUES (:did, :mon, :cbo, :rev, :cogs, :opex, :profit)
                    ON CONFLICT DO NOTHING
                """), {"did": r["dataset_id"], "mon": r["month"],
                       "cbo": r["close_booked_on"], "rev": r["revenue_booked"],
                       "cogs": r["cogs"], "opex": r["opex"], "profit": r["profit"]})

        elif table == "hm.close_adjustments":
            for r in rows:
                conn.execute(text("""
                    INSERT INTO hm.close_adjustments
                        (dataset_id, month, kind, ref_id, amount, note)
                    VALUES (:did, :mon, :kind, :rid, :amt, :note)
                """), {"did": r["dataset_id"], "mon": r["month"], "kind": r["kind"],
                       "rid": r.get("ref_id"), "amt": r["amount"],
                       "note": r.get("note", "")})

        conn.execute(text("RESET hm.bulk_load"))
        conn.execute(text("RESET hm.bulk_row_count"))


def _bulk_insert_bank_balances(engine: sa.Engine, rows: list[dict],
                                verbose: bool) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(text("SET hm.bulk_load = 'on'"))
        conn.execute(text(f"SET hm.bulk_row_count = '{len(rows)}'"))
        for r in rows:
            conn.execute(text("""
                INSERT INTO hm.bank_balances
                    (dataset_id, account_code, date, closing_balance)
                VALUES (:did, :acc, :dt, :bal)
                ON CONFLICT DO NOTHING
            """), {"did": r["dataset_id"], "acc": r["account_code"],
                   "dt": r["date"], "bal": r["closing_balance"]})
        conn.execute(text("RESET hm.bulk_load"))
        conn.execute(text("RESET hm.bulk_row_count"))


def _bulk_insert_recurring(engine: sa.Engine, rows: list[dict],
                            verbose: bool) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(text("SET hm.bulk_load = 'on'"))
        conn.execute(text(f"SET hm.bulk_row_count = '{len(rows)}'"))
        for r in rows:
            conn.execute(text("""
                INSERT INTO hm.recurring_outflows (dataset_id, kind, rule, amount)
                VALUES (:did, :kind, CAST(:rule AS jsonb), :amt)
            """), {"did": r["dataset_id"], "kind": r["kind"],
                   "rule": json.dumps(r["rule"]), "amt": r["amount"]})
        conn.execute(text("RESET hm.bulk_load"))
        conn.execute(text("RESET hm.bulk_row_count"))


def _bulk_insert_eval_receipts(engine: sa.Engine, rows: list[dict],
                                verbose: bool) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO eval.future_ar_receipts
                    (dataset_id, receipt_id, invoice_id, date, amount)
                VALUES (:did, :rid, :iid, :dt, :amt)
                ON CONFLICT DO NOTHING
            """), {"did": r["dataset_id"], "rid": r["receipt_id"],
                   "iid": r["invoice_id"], "dt": r["date"], "amt": r["amount"]})


def _bulk_insert_eval_payments(engine: sa.Engine, rows: list[dict],
                                verbose: bool) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO eval.future_ap_payments
                    (dataset_id, payment_id, invoice_id, date, amount)
                VALUES (:did, :pid, :iid, :dt, :amt)
                ON CONFLICT DO NOTHING
            """), {"did": r["dataset_id"], "pid": r["payment_id"],
                   "iid": r["invoice_id"], "dt": r["date"], "amt": r["amount"]})


def _bulk_insert_eval_balances(engine: sa.Engine, rows: list[dict],
                                verbose: bool) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO eval.future_bank_balances
                    (dataset_id, account_code, week_start, closing_balance)
                VALUES (:did, :acc, :ws, :bal)
                ON CONFLICT DO NOTHING
            """), {"did": r["dataset_id"], "acc": r["account_code"],
                   "ws": r["week_start"], "bal": r["closing_balance"]})


def _write_vault(engine: sa.Engine, entries: list[dict], verbose: bool) -> None:
    if not entries:
        return
    vault_key = settings.hm_vault_key
    if not vault_key:
        if verbose:
            print("  WARNING: HM_VAULT_KEY not set; vault entries skipped")
        return

    with engine.begin() as conn:
        for e in entries:
            conn.execute(text("""
                INSERT INTO vault.identity_map
                    (dataset_id, code, display_name_enc, iban_enc)
                VALUES (
                    :did, :code,
                    pgp_sym_encrypt(:name, :key),
                    pgp_sym_encrypt(:iban, :key)
                )
                ON CONFLICT (dataset_id, code) DO UPDATE
                    SET display_name_enc = EXCLUDED.display_name_enc,
                        iban_enc         = EXCLUDED.iban_enc
            """), {
                "did":  e["dataset_id"],
                "code": e["code"],
                "name": e["display_name"],
                "iban": e["iban"],
                "key":  vault_key,
            })


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_overview(dataset_dir: Path, result: SimResult) -> None:
    """Per-dataset overview.csv with revenue, profit, balances, top-20, segment breakdown."""
    # Revenue metrics use history period only (issue_date < as_of_date = trailing 52 weeks)
    hist_invoices = [inv for inv in result.ar_invoices
                     if inv["issue_date"] < result.as_of_date]
    total_revenue = sum(float(inv["amount_net"]) for inv in hist_invoices)
    total_profit  = sum(float(c["profit"]) for c in result.month_closes)
    as_of_bal = result.weekly_balances.get(result.as_of_date, 0.0)
    n_invoices = len(hist_invoices)
    top20 = _top20_codes(result, hist_invoices)
    top20_rev = sum(float(inv["amount_net"]) for inv in hist_invoices
                    if inv["cust_code"] in top20)
    top20_share = top20_rev / total_revenue if total_revenue else 0

    # Revenue and avg delay by segment
    from collections import defaultdict
    from datetime import date as date_type
    cp_by_code = {r["code"]: r for r in result.counterparties_hm}
    all_receipts = result.ar_receipts_hist + result.future_ar_receipts
    inv_by_id = {inv["invoice_id"]: inv for inv in hist_invoices}

    seg_revenue: dict[str, float] = defaultdict(float)
    seg_delays: dict[str, list[float]] = defaultdict(list)

    for rec in all_receipts:
        inv = inv_by_id.get(rec["invoice_id"])
        if inv is None:
            continue
        cust = cp_by_code.get(inv.get("cust_code", ""))
        if cust is None:
            continue
        seg = cust.get("segment", "unknown")
        seg_revenue[seg] += float(inv.get("amount_net", 0))
        delay = (rec["date"] - inv["due_date"]).days if isinstance(inv.get("due_date"), date_type) else 0
        seg_delays[seg].append(float(delay))

    rows = []

    # Summary row
    rows.append({
        "metric": "total_revenue",       "value": round(total_revenue, 2)})
    rows.append({
        "metric": "total_profit",        "value": round(total_profit, 2)})
    rows.append({
        "metric": "as_of_balance",       "value": round(as_of_bal, 2)})
    rows.append({
        "metric": "ar_invoice_count",    "value": n_invoices})
    rows.append({
        "metric": "top20_revenue_share", "value": round(top20_share, 4)})

    # Per-segment
    for seg in sorted(seg_revenue):
        delays_list = seg_delays[seg]
        avg_delay = sum(delays_list) / len(delays_list) if delays_list else 0.0
        rows.append({"metric": f"seg_{seg}_revenue", "value": round(seg_revenue[seg], 2)})
        rows.append({"metric": f"seg_{seg}_avg_delay_days", "value": round(avg_delay, 1)})

    # Top-20 customers with share
    cust_rev: dict[str, float] = defaultdict(float)
    for inv in hist_invoices:
        cust_rev[inv["cust_code"]] += float(inv["amount_net"])
    sorted_custs = sorted(cust_rev.items(), key=lambda x: x[1], reverse=True)[:20]
    for i, (code, rev) in enumerate(sorted_custs, 1):
        rows.append({
            "metric": f"top{i:02d}_customer",
            "value": f"{code}:{round(rev/total_revenue*100, 2)}%",
        })

    _write_csv(dataset_dir / "overview.csv", rows, ["metric", "value"])


def _top20_codes(result: SimResult, invoices: list[dict] | None = None) -> set[str]:
    from collections import defaultdict
    source = invoices if invoices is not None else result.ar_invoices
    cust_rev: dict[str, float] = defaultdict(float)
    for inv in source:
        cust_rev[inv["cust_code"]] += float(inv["amount_net"])
    sorted_custs = sorted(cust_rev.items(), key=lambda x: x[1], reverse=True)[:20]
    return {code for code, _ in sorted_custs}
