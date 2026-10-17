"""Read-only live integration probe; no authentication or trading."""
import json
from pathlib import Path
from market_data import fetch_cls, fetch_indices, fetch_stock_quotes
from app import DEFAULTS

output = Path('artifacts')
output.mkdir(exist_ok=True)
for name, fetch in [('cls', fetch_cls), ('indices', fetch_indices), ('stocks', lambda: fetch_stock_quotes(DEFAULTS['stocks']))]:
    try:
        rows = fetch()
        (output / (name + '-live.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name, 'OK', len(rows))
        for row in rows[:2]:
            print({key: row.get(key) for key in ('source', 'title', 'published', 'name', 'change', 'timestamp')})
    except Exception as exc:
        print(name, 'FAILED', str(exc))
