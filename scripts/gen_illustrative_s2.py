"""
Generate data/illustrative/S2/ — a one-minute-readable snapshot of S2_big_customer:
  README.md with opening balance, top-10 customers, open invoices, planned payments.
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from config import settings
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset

DATASET_ID = "S2_big_customer"
THRESHOLD = 509_538.0
DEP_ANNUAL = 250_000.0


def generate(out_dir: Path | None = None) -> Path:
    eng = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)
    if out_dir is None:
        out_dir = ROOT / "data" / "illustrative" / "S2"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = load_dataset(eng, DATASET_ID)
    as_of: date = data["as_of"]
    opening = data["opening_balance"]
    beh = SimpleBehaviour(eng, DATASET_ID, as_of)

    # ── Top-10 customers by open AR ───────────────────────────────────────────
    ar_by_cust: dict[str, float] = {}
    seg_by_cust: dict[str, str] = {}
    for inv in data["open_ar"]:
        c = inv["cust_code"]
        ar_by_cust[c] = ar_by_cust.get(c, 0.0) + float(inv["outstanding_amount"])
        seg_by_cust[c] = inv.get("segment", "")

    top10 = sorted(ar_by_cust.items(), key=lambda kv: -kv[1])[:10]

    # ── Open invoices for top-10 customers, due within horizon ───────────────
    horizon_end = as_of + __import__("datetime").timedelta(weeks=13)
    open_inv: list[dict] = [
        inv for inv in data["open_ar"]
        if inv["cust_code"] in {c for c, _ in top10}
        and inv["due_date"] <= horizon_end
    ]
    open_inv_sorted = sorted(open_inv, key=lambda x: x["due_date"])[:25]

    # ── Planned payments > 50k + payroll/VAT/tax/rent ─────────────────────────
    recurring = data["recurring"]
    big_ap = sorted(
        [inv for inv in data["open_ap"] if float(inv["outstanding_amount"]) >= 50_000],
        key=lambda x: x["due_date"],
    )

    # ── Build README.md ────────────────────────────────────────────────────────
    lines: list[str] = [
        "# S2 — Big Customer (Illustrative Dataset)",
        "",
        f"As-of date: {as_of}  |  Opening balance: €{opening:,.0f}  |  Safety threshold: €{THRESHOLD:,.0f}",
        "",
        "---",
        "",
        "## Opening position",
        "",
        f"| Item | Value |",
        f"|------|-------|",
        f"| Opening cash balance | €{opening:,.0f} |",
        f"| Safety threshold (4 × weekly fixed costs) | €{THRESHOLD:,.0f} |",
        f"| Headroom above threshold | €{max(0, opening - THRESHOLD):,.0f} |",
        f"| Total open AR | €{sum(float(i['outstanding_amount']) for i in data['open_ar']):,.0f} |",
        f"| Total open AP | €{sum(float(i['outstanding_amount']) for i in data['open_ap']):,.0f} |",
        "",
        "---",
        "",
        "## Top 10 customers by open receivables",
        "",
        "| Customer | Segment | Open AR (€) | Avg delay (days) | Delay source |",
        "|----------|---------|-------------|-----------------|--------------|",
    ]

    for cust, ar in top10:
        delay = beh.expected_delay(cust)
        src = beh.source(cust)
        seg = seg_by_cust.get(cust, "")
        lines.append(f"| {cust} | {seg} | {ar:,.0f} | {delay:.1f} | {src} |")

    lines += [
        "",
        "---",
        "",
        "## Open invoices (top-10 customers, due within 13-week horizon)",
        "",
        "| Invoice ID | Customer | Due date | Outstanding (€) | Overdue? |",
        "|------------|----------|----------|-----------------|----------|",
    ]

    for inv in open_inv_sorted:
        overdue = "Yes" if inv["due_date"] < as_of else "No"
        lines.append(
            f"| {inv['invoice_id']} | {inv['cust_code']} | {inv['due_date']} "
            f"| {float(inv['outstanding_amount']):,.0f} | {overdue} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Planned payments above €50k",
        "",
        "| Supplier | Due date | Amount (€) |",
        "|----------|----------|------------|",
    ]

    for inv in big_ap:
        lines.append(
            f"| {inv['supp_code']} | {inv['due_date']} "
            f"| {float(inv['outstanding_amount']):,.0f} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Recurring outflows",
        "",
        "| Kind | Rule | Monthly amount (€) |",
        "|------|------|-------------------|",
    ]

    for rec in recurring:
        rule = rec['rule']
        if isinstance(rule, dict):
            rule_str = ", ".join(f"{k}={v}" for k, v in rule.items())
        else:
            rule_str = str(rule)
        lines.append(f"| {rec['kind']} | {rule_str} | {rec['amount']:,.0f} |")

    lines += [
        "",
        "---",
        "",
        f"*Generated from hm_analyst as of {as_of}.*",
        "",
    ]

    readme = out_dir / "README.md"
    readme.write_text("\n".join(lines), encoding="utf-8")
    return readme


if __name__ == "__main__":
    path = generate()
    print(f"Wrote {path}")
