import tempfile
import json
import unittest
from pathlib import Path

from app import crossed, load_settings, parse_feed, safe_url


class CoreTests(unittest.TestCase):
    def test_rss_and_unsafe_link(self):
        rows = parse_feed(b'<rss><channel><item><guid>1</guid><title>Hello &amp; world</title><link>https://example.com/a</link><pubDate>today</pubDate></item><item><title>bad link</title><link>javascript:alert(1)</link></item></channel></rss>')
        self.assertEqual(rows[0]['title'], 'Hello & world')
        self.assertEqual(rows[0]['published'], 'today')
        self.assertEqual(rows[1]['url'], '')

    def test_atom_namespace(self):
        rows = parse_feed(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>News</title><link href="https://example.com/news"/><updated>2026-10-15</updated></entry></feed>')
        self.assertEqual(rows[0]['url'], 'https://example.com/news')
        self.assertEqual(rows[0]['published'], '2026-10-15')

    def test_crossing_once_and_both_directions(self):
        self.assertTrue(crossed(99, 100, 100, 'above'))
        self.assertFalse(crossed(100, 101, 100, 'above'))
        self.assertTrue(crossed(101, 99, 100, 'below'))
        self.assertFalse(crossed(99, 98, 100, 'below'))

    def test_settings_fallback_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            self.assertEqual(len(load_settings(path)['stocks']), 6)
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(load_settings(path)['rss'], '')
            path.write_text('{"muted":true,"rss":"https://example.com/feed"}', encoding='utf-8')
            self.assertTrue(load_settings(path)['muted'])
            self.assertEqual(load_settings(path)['rss'], 'https://example.com/feed')

    def test_urls(self):
        for value in ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:pass@example.com']:
            self.assertFalse(safe_url(value))

    def test_font_sizes_migrate_old_presets_and_keep_numeric_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            for saved, expected in [({'news_text_size': 'large', 'bubble_text_size': 'extra'}, (21, 26)),
                                    ({'news_text_size': 32, 'bubble_text_size': 16}, (32, 16)),
                                    ({'news_text_size': 'bad', 'bubble_text_size': 100}, (18, 40)),
                                    ({'news_text_size': -1, 'bubble_text_size': True}, (12, 20))]:
                saved['muted'] = True
                path.write_text(json.dumps(saved), encoding='utf-8')
                result = load_settings(path)
                self.assertEqual((result['news_text_size'], result['bubble_text_size']), expected)
                self.assertTrue(result['muted'])


if __name__ == '__main__':
    unittest.main()
