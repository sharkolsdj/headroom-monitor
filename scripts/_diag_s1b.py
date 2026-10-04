"""Diagnostic: engine delay bias vs archetype true delay for S1_normal."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlalchemy as sa
from config import settings
from engine._behaviour import SimpleBehaviour
from engine._loader import load_dataset

eng_admin = sa.create_engine(settings.postgres_dsn, pool_pre_ping=True)
eng_analyst = sa.create_engine(settings.role_dsn("hm_analyst"), pool_pre_ping=True)

# Columns
with eng_admin.connect() as c:
    cols = c.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='hm' AND table_name='counterparties' ORDER BY ordinal_position"
    )).fetchall()
    print("counterparties cols:", [r[0] for r in cols])

# archetype_mean stored?
with eng_admin.connect() as c:
    rows = c.execute(sa.text(
        "SELECT code, archetype, archetype_mean, archetype_sd "
        "FROM hm.counterparties WHERE dataset_id='S1_normal' AND code LIKE 'CUST_%' LIMIT 10"
    )).fetchall()
    if rows:
        for r in rows:
            print(r)
    else:
        print("No archetype_mean column or no rows")
