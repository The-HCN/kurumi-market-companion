"""Separate exchange session state from quote freshness and transport errors."""
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data import SHANGHAI, quote_datetime, quote_is_fresh
from app_paths import BASE

@lru_cache(maxsize=1)
def calendars():
    try:
        return json.loads((BASE/'assets/market-calendar.json').read_text(encoding='utf-8'))['markets']
    except (OSError, ValueError, KeyError):
        return {}

def market_session(market, now=None):
    now = now or datetime.now(SHANGHAI)
    zone = ZoneInfo('America/New_York') if market == '美股' else SHANGHAI
    date = now.astimezone(zone).date().isoformat()
    calendar = calendars().get(market)
    if not calendar or not calendar['start'] <= date <= calendar['end']:
        return '交易日历待更新'
    row = calendar['sessions'].get(date)
    if row is None:
        return '休市'
    opened, closed = (datetime.fromisoformat(row[key]) for key in ('open', 'close'))
    if now < opened:
        return '未开盘'
    if now >= closed:
        return '已收盘'
    if row.get('break_start') and row.get('break_end'):
        if datetime.fromisoformat(row['break_start']) <= now < datetime.fromisoformat(row['break_end']):
            return '午间休市'
    return '交易中'

def quote_status(market, quote=None, error=None, now=None):
    now = now or datetime.now(SHANGHAI)
    session = market_session(market, now)
    stamp = quote_datetime(quote) if quote else None
    if error:
        state = '连接失败' if error is True else '获取失败'
    elif not quote:
        state = '等待行情'
    elif stamp is None:
        state = '时间无效'
    elif (stamp-now).total_seconds() > 10:
        state = '时间异常'
    elif quote_is_fresh(quote, now):
        state = '近期快照'
    elif session == '交易中':
        state = '数据延迟'
    else:
        state = '最近快照'
    if stamp:
        source_time = stamp.strftime('%m-%d %H:%M:%S') + (' 美东' if market == '美股' else ' 北京')
    else:
        source_time = '暂无有效时间'
    return dict(session=session, data=state, source_time=source_time,
                active=state == '近期快照' and session == '交易中')
