"""Diagnose MC band vs expected line, and bridge cash_change."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from sqlalchemy import text
from config import settings
from engine._forecast import run_forecast
from engine._loader import load_dataset
from engine._behaviour import SimpleBehaviour
from engine._overrides import apply_overrides, load_active_overrides

eng = sa.create_engine(settings.role_dsn("hm_analyst"))
did = "S2_big_customer"

# ── 1. P50 vs expected per week ───────────────────────────────────────────────
r = run_forecast(did, eng, scenarios=["expected"], include_mc=True, mc_seed=42, mc_n_runs=1000, threshold=509538.0)
exp = r["expected"]
print("=== P50 vs Expected (S2, 1000 runs) ===")
print(f"{'Wk':>3}  {'expected':>12}  {'p10':>12}  {'p50':>12}  {'p90':>12}  {'inside?':>8}")
for wk in exp.weeks:
    k = wk["week"]
    e = wk["closing"]
    b = exp.mc_band[k]
    inside = "YES" if b["p10"] <= e <= b["p90"] else "NO"
    print(f"{k:>3}  {e:>12,.0f}  {b['p10']:>12,.0f}  {b['p50']:>12,.0f}  {b['p90']:>12,.0f}  {inside:>8}")

# ── 2. Delay distribution for top customers ───────────────────────────────────
print()
print("=== Delay distribution (S2 top customers) ===")
data = load_dataset(eng, did)
beh = SimpleBehaviour(eng, did, data["as_of"])
all_cust = beh.all_customer_sources()
sorted_cust = sorted(all_cust.items(), key=lambda kv: -kv[1][0])[:8]
for code, (mean_d, src) in sorted_cust:
    sample = beh.delay_sample(code)
    if not sample:
        continue
    s_sorted = sorted(sample)
    n = len(s_sorted)
    median = s_sorted[n//2]
    neg = sum(1 for x in sample if x < 0)
    print(f"  {code}  mean={mean_d:>6.1f}  median={median:>6.1f}  n={n:>4}  neg={neg:>3}  src={src}")

# ── 3. Bridge components for July 2026 ───────────────────────────────────────
print()
print("=== Bridge components July 2026 (S2) ===")
from engine._profitcash import load_profitcash_data, build_bridge_historical
from datetime import date
pc = load_profitcash_data(eng, did)

# Show vat_paid and tax_paid for July explicitly
from collections import defaultdict
from engine._profitcash import _balance_on_or_before, _ar_outstanding_at, _ap_outstanding_at, _month_end
as_of = data["as_of"]
july = date(2026, 7, 1)
july_end = _month_end(2026, 7)
june_end = date(2026, 6, 30)
bal_end = _balance_on_or_before(pc["bank_balances"], july_end)
bal_start = _balance_on_or_before(pc["bank_balances"], june_end)
cash_bal = bal_end - bal_start
# Sum of bank_txns in July
cash_txn = sum(float(t["amount"]) for t in pc["bank_txns"]
               if july <= t["date"] <= july_end)
vat_paid = sum(-float(t["amount"]) for t in pc["bank_txns"]
               if t["category"] == "vat_payment" and july <= t["date"] <= july_end)
tax_paid = sum(-float(t["amount"]) for t in pc["bank_txns"]
               if t["category"] == "tax_advance" and july <= t["date"] <= july_end)
print(f"  Cash from bank_balance diff: {cash_bal:,.2f}")
print(f"  Cash from bank_txn sum:      {cash_txn:,.2f}")
print(f"  vat_paid in July:            {vat_paid:,.2f}")
print(f"  tax_paid in July:            {tax_paid:,.2f}")
