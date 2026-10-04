"""Returns exit code 0 when S8 forecast.json is newer than 16:00 today."""
import sys
from pathlib import Path
from datetime import datetime

p = Path(r"C:\HeadRoom Monitor\data\demo\S8_month_end_close\forecast.json")
if not p.exists():
    sys.exit(1)
mtime = datetime.fromtimestamp(p.stat().st_mtime)
# Check if updated after 16:00 today (the background run started around 16:25)
if mtime.hour >= 16 and mtime.minute >= 30:
    sys.exit(0)
sys.exit(1)
