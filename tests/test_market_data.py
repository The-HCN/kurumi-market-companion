import unittest
from market_data import bubble_text, emotion_for, parse_cls, parse_quotes, quote_reaction


class MarketDataTests(unittest.TestCase):
    def test_cls_public_headline_and_time(self):
        rows = parse_cls({'errno': 0, 'data': {'roll_data': [
            {'id': 123, 'title': '<b>市场上涨</b>', 'content': '正文 &amp; 消息', 'ctime': 0, 'level': 'A'}]}})
        self.assertEqual(rows[0]['id'], 'cls-123')
        self.assertEqual(rows[0]['title'], '市场上涨')
        self.assertEqual(rows[0]['content'], '正文 & 消息')
        self.assertEqual(rows[0]['published'], '01-01 08:00:00 北京时间')
        self.assertFalse(rows[0]['demo'])
        self.assertEqual(rows[0]['url'], 'https://www.cls.cn/detail/123')

    def test_source_failure_is_not_fake_news(self):
        for payload in [{'errno': 1}, {'errno': 0, 'data': {}}, {'errno': 0, 'data': {'roll_data': []}}]:
            with self.assertRaises(ValueError):
                parse_cls(payload)

    def test_quote_fields_and_invalid_prices(self):
        fields = [''] * 33
        fields[3], fields[30], fields[32] = '3200.1', '20261015150000', '-1.5'
        row = parse_quotes('v_sh000001="' + '~'.join(fields) + '";')[0]
        self.assertEqual(row['market'], 'A股')
        self.assertEqual(row['change'], -1.5)
        self.assertEqual(quote_reaction(row), 'sad')
        fields[3] = 'NaN'
        with self.assertRaises(ValueError):
            parse_quotes('v_sh000001="' + '~'.join(fields) + '";')

    def test_expressions_handle_negation_mixed_and_macro(self):
        self.assertEqual(emotion_for('恒生指数上涨1%'), 'happy')
        self.assertEqual(emotion_for('纳指下跌2%'), 'sad')
        for title in ['未上涨', '跌幅收窄', '市场上涨后下跌', '明日公布经济数据', 'CPI同比上涨3%']:
            self.assertEqual(emotion_for(title), 'neutral', title)

    def test_bubble_keeps_origin_and_truncation(self):
        text = bubble_text({'title': '测' * 200, 'source': '财联社电报', 'received': '10-15 12:00:00', 'demo': False})
        self.assertIn('…', text)
        self.assertIn('财联社电报 · 12:00:00', text)
        self.assertNotIn('演示', text)


if __name__ == '__main__':
    unittest.main()
