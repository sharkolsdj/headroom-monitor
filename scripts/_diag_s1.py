"""Diagnostic: compare engine estimated delays vs eval truth for S1_normal."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from config import settings
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset

eng_eval = sa.create_engine(settings.role_dsn("hm_evaluator"), pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

# --- truth from eval ---
with eng_eval.connect() as c:
    row = c.execute(
        sa.text("SELECT truth FROM eval.scenario_truth WHERE dataset_id=:d"),
        {"d": "S1_normal"}
    ).fetchone()
raw = row[0]
truth = raw if isinstance(raw, dict) else json.loads(raw)
print("Truth top keys:", list(truth.keys()))

# --- engine behaviour ---
data = load_dataset(eng_analyst, "S1_normal")
beh = SimpleBehaviour(eng_analyst, "S1_normal", data["as_of"])

# Find archetype delays in truth
archetypes = truth.get("customer_archetypes") or truth.get("customers") or {}
print(f"\nArchetype sample (first 5): {dict(list(archetypes.items())[:5])}")
print(f"Total archetypes: {len(archetypes)}")

# Compare engine estimated delay vs archetype true delay
diffs = []
for code, arch in archetypes.items():
    true_delay = arch if isinstance(arch, (int, float)) else arch.get("mean_delay") or arch.get("delay") or arch.get("payment_delay")
    if true_delay is None:
        continue
    engine_delay = beh.expected_delay(code)
    diffs.append((code, true_delay, engine_delay, engine_delay - true_delay))

if diffs:
    diffs.sort(key=lambda x: abs(x[3]), reverse=True)
    print(f"\n{'Code':12s}  {'True':>8s}  {'Engine':>8s}  {'Diff':>8s}")
    for code, t, e, d in diffs[:20]:
        print(f"  {code:12s}  {t:8.1f}  {e:8.1f}  {d:+8.1f}")
    avg_diff = sum(d for _, _, _, d in diffs) / len(diffs)
    print(f"\nN={len(diffs)}  avg diff (engine - true): {avg_diff:+.1f} days")
else:
    print("\nNo archetype data found — printing full truth structure:")
    print(json.dumps(truth, indent=2)[:3000])
