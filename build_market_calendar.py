"""Build a bundled calendar; the desktop app only reads JSON, never pandas."""
import json
from pathlib import Path
import sys
from importlib.metadata import version

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE/'.runtime'))

if __name__ == '__main__':
    import exchange_calendars as xcals
    import pandas as pd
    data = {'provider': 'exchange_calendars', 'version': version('exchange-calendars'),
            'source': 'https://github.com/gerrymanoim/exchange_calendars', 'markets': {}}
    for market, name in [('A股', 'XSHG'), ('港股', 'XHKG'), ('美股', 'XNYS')]:
        end = '2027-12-31'
        try:
            calendar = xcals.get_calendar(name, start='2026-01-01', end=end, side='left')
        except ValueError:
            end = '2026-12-31'
            calendar = xcals.get_calendar(name, start='2026-01-01', end=end, side='left')
        sessions = {}
        for date, row in calendar.schedule.iterrows():
            sessions[date.strftime('%Y-%m-%d')] = {
                key: None if pd.isna(value) else value.isoformat()
                for key, value in row.items()}
        data['markets'][market] = dict(exchange=name, start='2026-01-01', end=end, sessions=sessions)
        print(market, end, len(sessions))
    target = BASE/'assets/market-calendar.json'
    target.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
