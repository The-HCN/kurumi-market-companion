import unittest
from datetime import datetime
from market_data import SHANGHAI
from market_status import market_session, quote_status

def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=SHANGHAI)

class MarketStatusTests(unittest.TestCase):
    def test_mainland_session_boundaries_and_holidays(self):
        for clock, expected in [('09:29', '未开盘'), ('09:30', '交易中'), ('11:30', '午间休市'),
                                ('12:59', '午间休市'), ('13:00', '交易中'), ('15:00', '已收盘')]:
            self.assertEqual(market_session('A股', at('2026-10-15T'+clock)), expected)
        for day in ['2026-10-01', '2026-10-17']:
            self.assertEqual(market_session('A股', at(day+'T10:00')), '休市')
        self.assertEqual(market_session('A股', at('2027-01-05T10:00')), '交易日历待更新')

    def test_hongkong_lunch_and_half_day(self):
        self.assertEqual(market_session('港股', at('2026-10-15T11:45')), '交易中')
        self.assertEqual(market_session('港股', at('2026-10-15T12:00')), '午间休市')
        self.assertEqual(market_session('港股', at('2026-12-24T12:30')), '已收盘')

    def test_us_dst_overnight_and_early_close(self):
        self.assertEqual(market_session('美股', at('2026-10-16T02:00')), '交易中')
        self.assertEqual(market_session('美股', at('2026-12-15T22:00')), '未开盘')
        self.assertEqual(market_session('美股', at('2026-12-15T22:30')), '交易中')
        self.assertEqual(market_session('美股', at('2026-11-27T23:00')), '交易中')
        self.assertEqual(market_session('美股', at('2026-11-28T02:00')), '已收盘')

    def test_closure_does_not_turn_old_quote_into_connection_failure(self):
        q = dict(market='A股', timestamp='20261015150000')
        self.assertEqual(quote_status('A股', q, now=at('2026-10-15T15:10'))['data'], '最近快照')
        self.assertEqual(quote_status('A股', q, now=at('2026-10-16T10:00'))['data'], '数据延迟')
        self.assertEqual(quote_status('A股', q, True, now=at('2026-10-17T10:00'))['data'], '连接失败')
        q['timestamp'] = 'bad'
        self.assertEqual(quote_status('A股', q)['data'], '时间无效')
        q['timestamp'] = '20261016100100'
        self.assertEqual(quote_status('A股', q, now=at('2026-10-16T10:00'))['data'], '时间异常')

if __name__ == '__main__':
    unittest.main()
