import unittest
from datetime import datetime
from market_data import (SHANGHAI, quote_code, parse_stock_quotes, quote_is_fresh,
                         comparable_quotes, queued_news)


class DeliveryTests(unittest.TestCase):
    def test_stock_code_mapping_and_no_query_injection(self):
        for market, symbol, code in [('A股', '600519', 'sh600519'), ('A股', '300750', 'sz300750'),
                                     ('A股', '920001', 'bj920001'), ('港股', '700', 'r_hk00700'), ('美股', 'NVDA', 'usNVDA')]:
            self.assertEqual(quote_code(dict(market=market, symbol=symbol)), code)
        for symbol in ['AAPL,usTSLA', '../x', 'AAPL?x=1']:
            with self.assertRaises(ValueError):
                quote_code(dict(market='美股', symbol=symbol))

    def test_real_stock_quotes_cannot_fall_back_to_demo(self):
        stock = dict(market='港股', symbol='00700', name='腾讯控股', price=100)
        fields = [''] * 33
        fields[3], fields[4], fields[30], fields[32] = '420', '400', '2026/10/15 10:00:00', '5'
        row = parse_stock_quotes('v_r_hk00700="' + '~'.join(fields) + '";', [stock])[0]
        self.assertEqual(row['price'], 420)
        self.assertEqual(row['key'], '港股:00700')
        self.assertFalse(row['demo'])
        with self.assertRaises(ValueError):
            parse_stock_quotes('v_pv_none_match="1";', [stock])

    def test_freshness_rejects_old_future_and_unknown_times(self):
        now = datetime(2026, 10, 15, 10, 0, tzinfo=SHANGHAI)
        previous = dict(market='A股', timestamp='20261015095900')
        current = dict(market='A股', timestamp='20261015100000')
        self.assertTrue(quote_is_fresh(previous, now))
        self.assertTrue(comparable_quotes(previous, current, now))
        self.assertFalse(comparable_quotes(current, previous, now))
        for stamp in ['20261014150000', '20261015100100', '', 'not a timestamp']:
            self.assertFalse(quote_is_fresh(dict(market='A股', timestamp=stamp), now))

    def test_us_exchange_times_handle_daylight_saving(self):
        summer = dict(market='美股', timestamp='2026-10-15 09:30:00')
        winter = dict(market='美股', timestamp='2026-12-15 09:30:00')
        self.assertTrue(quote_is_fresh(summer, datetime(2026, 10, 15, 21, 31, tzinfo=SHANGHAI)))
        self.assertTrue(quote_is_fresh(winter, datetime(2026, 12, 15, 22, 31, tzinfo=SHANGHAI)))

    def test_queue_expires_and_bounds_waiting_without_duplicate_ids(self):
        items = [dict(id='expired', _queued_at=1), dict(id='a', _queued_at=99),
                 dict(id='a', _queued_at=100), dict(id='b', _queued_at=100),
                 dict(id='c', _queued_at=100), dict(id='d', _queued_at=100)]
        self.assertEqual([r['id'] for r in queued_news(items, now=100)], ['b', 'c', 'd'])
        self.assertEqual(queued_news(items, now=200), [])


if __name__ == '__main__':
    unittest.main()
