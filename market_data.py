"""Public news/quote adapters and deterministic character reactions."""
from __future__ import annotations

import html
import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SHANGHAI = timezone(timedelta(hours=8))
CLS_URL = 'https://www.cls.cn/api/cache?rn=20&name=telegraph&lastTime='
QUOTE_URL = 'https://qt.gtimg.cn/q=sh000001,r_hkHSI,usDJI,usIXIC'


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', str(value or '')))).strip()


def read_public(url, limit=2_000_000):
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (KurumiCompanion/0.2)',
                                   'Referer': 'https://www.cls.cn/' if 'cls.cn/' in url else 'https://gu.qq.com/'})
    with urlopen(request, timeout=15) as response:
        if not response.url.startswith('https://'):
            raise ValueError('数据源未使用 HTTPS')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('数据源响应过大')
    return data


def parse_cls(payload):
    if not isinstance(payload, dict) or payload.get('errno', 0) != 0:
        raise ValueError('财联社数据源返回错误')
    rows = payload.get('data', {}).get('roll_data')
    if not isinstance(rows, list):
        raise ValueError('财联社页面数据格式已变化')
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        # Only public text, never premium bodies or attached article content.
        content = plain(row.get('content'))
        title = plain(row.get('title')) or content
        if not title:
            continue
        stamp = row.get('ctime')
        try:
            published = datetime.fromtimestamp(float(stamp), SHANGHAI).strftime('%m-%d %H:%M:%S') + ' 北京时间'
        except (ValueError, TypeError, OverflowError, OSError):
            published = '来源未提供'
        result.append({'id': 'cls-' + str(row['id']), 'title': title[:500],
                       'content': content[:2000], 'url': 'https://www.cls.cn/detail/' + str(row['id']),
                       'market': '全部', 'source': '财联社电报', 'published': published,
                       'demo': False, 'important': row.get('level') in ('A', 'B')})
    if not result:
        raise ValueError('财联社暂无可读快讯')
    return result


def fetch_cls():
    return parse_cls(json.loads(read_public(CLS_URL + str(int(time.time())))))


def parse_quotes(text):
    result = []
    markets = {'sh000001': ('A股', '上证指数'), 'r_hkHSI': ('港股', '恒生指数'),
               'hkHSI': ('港股', '恒生指数'), 'usDJI': ('美股', '道琼斯'), 'usIXIC': ('美股', '纳斯达克')}
    for key, body in re.findall(r'v_([\w]+)="([^"]*)"', text):
        fields = body.split('~')
        if key not in markets or len(fields) < 33:
            continue
        try:
            price, change = float(fields[3]), float(fields[32])
            if not math.isfinite(price) or price <= 0 or not math.isfinite(change):
                continue
        except (ValueError, IndexError):
            continue
        market, name = markets[key]
        result.append(dict(symbol=key, market=market, name=name, price=price, change=change,
                           timestamp=fields[30], source='腾讯公开行情', demo=False))
    if not result:
        raise ValueError('行情源未返回可读指数')
    return result


def fetch_indices():
    return parse_quotes(read_public(QUOTE_URL).decode('gb18030', errors='replace'))


def stock_key(stock):
    return stock['market'] + ':' + stock['symbol']


def quote_code(stock):
    symbol, market = stock['symbol'].upper(), stock['market']
    if market == 'A股' and re.fullmatch(r'\d{6}', symbol):
        return ('sh' if symbol[0] in '569' and not symbol.startswith('92') else 'bj' if symbol[0] in '489' else 'sz') + symbol
    if market == '港股' and re.fullmatch(r'\d{1,5}', symbol):
        return 'r_hk' + symbol.zfill(5)
    if market == '美股' and re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', symbol):
        return 'us' + symbol
    raise ValueError('股票代码格式无效：' + symbol[:30])


def parse_stock_quotes(text, stocks):
    lookup = {}
    for stock in stocks:
        code = quote_code(stock)
        lookup[code] = stock
        if code.startswith('r_hk'):
            lookup[code[2:]] = stock
    records = []
    for code, body in re.findall(r'v_([\w.\-]+)="([^"]*)"', text):
        stock = lookup.get(code)
        fields = body.split('~')
        if stock is None or len(fields) < 33:
            continue
        try:
            price, base, change = float(fields[3]), float(fields[4]), float(fields[32])
            if not all(math.isfinite(value) for value in (price, base, change)) or min(price, base) <= 0:
                continue
        except (ValueError, IndexError):
            continue
        records.append(dict(key=stock_key(stock), symbol=stock['symbol'], market=stock['market'],
                            name=stock['name'], price=price, base=base, change=change,
                            timestamp=fields[30], source='腾讯公开行情', demo=False))
    if not records:
        raise ValueError('行情源未返回可读自选行情')
    return records


def fetch_stock_quotes(stocks):
    if not stocks:
        return []
    codes = ','.join(quote_code(stock) for stock in stocks)
    text = read_public('https://qt.gtimg.cn/q=' + codes).decode('gb18030', errors='replace')
    return parse_stock_quotes(text, stocks)


def quote_datetime(quote):
    """Provider times: A/HK local exchange time, US New York time."""
    value = quote.get('timestamp', '')
    try:
        zone = ZoneInfo('America/New_York') if quote['market'] == '美股' else SHANGHAI
        for pattern in ('%Y%m%d%H%M%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(value, pattern).replace(tzinfo=zone)
            except ValueError:
                continue
    except (ZoneInfoNotFoundError, TypeError):
        pass
    return None


def quote_is_fresh(quote, now=None):
    stamp = quote_datetime(quote)
    if stamp is None:
        return False
    now = now or datetime.now(SHANGHAI)
    age = (now - stamp).total_seconds()
    return -10 <= age <= 180


def comparable_quotes(previous, current, now=None):
    if not previous or not quote_is_fresh(previous, now) or not quote_is_fresh(current, now):
        return False
    return quote_datetime(current) > quote_datetime(previous)


def queued_news(items, now=None, max_age=90, limit=3):
    """Bound waiting time and deduplicate without altering the history list."""
    now = time.monotonic() if now is None else now
    unique = {}
    for item in items:
        if now - item.get('_queued_at', now) <= max_age:
            unique[item['id']] = item
    return list(unique.values())[-limit:]


def emotion_for(text):
    """Conservative word rules, a character expression, never investment analysis."""
    text = plain(text)
    neutralized = ('未上涨', '未下跌', '未亏损', '未盈利', '未增长', '未下降', '未降息',
                   '跌幅收窄', '涨幅收窄', '尚未', '否认', '传闻', '不确定',
                   '消费者价格指数', 'CPI', 'PPI', '失业率', '通胀')
    if any(word in text for word in neutralized):
        return 'neutral'
    positive = ('上涨', '大涨', '走高', '涨超', '涨逾', '涨停', '新高', '扭亏', '盈利增长', '增长', '利好', '上调', '降准')
    negative = ('下跌', '大跌', '走低', '跌超', '跌逾', '跌停', '新低', '亏损', '下滑', '利空', '下调', '下降', '暴跌')
    up = any(word in text for word in positive)
    down = any(word in text for word in negative)
    return 'happy' if up and not down else 'sad' if down and not up else 'neutral'


def quote_reaction(quote):
    if quote['change'] >= .3:
        return 'happy'
    if quote['change'] <= -.3:
        return 'sad'
    return 'neutral'


def bubble_text(item):
    prefix = '【演示】' if item.get('demo') else '【市场快讯】'
    title = plain(item['title'])
    short = title[:110] + ('…' if len(title) > 110 else '')
    return prefix + '\n' + short + '\n\n' + item['source'] + ' · ' + item.get('received', '')[-8:]
