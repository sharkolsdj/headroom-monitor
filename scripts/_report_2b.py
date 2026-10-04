"""Report for Phase 2B stop-and-report (corrected bridge)."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from config import settings
from engine._forecast import run_forecast

eng = sa.create_engine(settings.role_dsn("hm_analyst"))
r = run_forecast(
    "S2_big_customer", eng,
    scenarios=["expected"],
    include_bridge=True,
    include_assumptions=True,
    include_stress=True,
    dep_annual=250000.0,
    threshold=509538.0,
)
exp = r["expected"]

print("=== S2 Profit-vs-Cash Bridge (corrected) ===")
print(f"{'Month':12}  {'Profit':>10}  {'Dep':>7}  {'ΔAR':>10}  {'ΔAP':>10}  {'VATpaid':>9}  {'TaxPaid':>8}  {'Inv/Other':>10}  {'Cash':>10}  {'Err':>6}")
for row in (exp.bridge or []):
    print(
        f"{str(row['month']):12}  {row['profit']:>10,.0f}  {row['depreciation']:>7,.0f}"
        f"  {row['delta_ar']:>10,.0f}  {row['delta_ap']:>10,.0f}"
        f"  {row['vat_paid']:>9,.0f}  {row['tax_paid']:>8,.0f}"
        f"  {row['inventory_other']:>10,.0f}  {row['cash_change']:>10,.0f}"
        f"  {row['reconciliation_error']:>6.2f}"
    )
print()
print("Sentences:")
for row in (exp.bridge or []):
    print(f"  {row['sentence']}")

print()
print("=== First 15 Assumptions ===")
for a in (exp.assumptions or [])[:15]:
    v = a["value"]
    if isinstance(v, list): v = f"[{len(v)} values]"
    desc = a["description"][:60]
    print(f"{a['id']}  {desc:60s}  value={v}  ({a['source']})")
