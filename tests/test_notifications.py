import os
import unittest
from uuid import uuid4
from desktop import SingleInstance
from notifications import should_announce


class NotificationTests(unittest.TestCase):
    def test_modes_keep_manual_reading_separate(self):
        ordinary = {'id': 'normal', 'source': '财联社电报'}
        important = dict(ordinary, important=True)
        alert = {'source': '真实到价提醒 · 腾讯快照'}
        self.assertTrue(should_announce(ordinary, {'notification_mode': 'all'}))
        self.assertFalse(should_announce(ordinary, {'notification_mode': 'important'}))
        self.assertTrue(should_announce(important, {'notification_mode': 'important'}))
        self.assertTrue(should_announce(alert, {'notification_mode': 'important'}))
        self.assertFalse(should_announce(important, {'notification_mode': 'manual'}))
        self.assertFalse(should_announce(alert, {'notification_mode': 'all', 'muted': True}))

    @unittest.skipUnless(os.name == 'nt', 'Windows named kernel objects')
    def test_second_instance_signals_first_and_shutdown_releases_guard(self):
        scope = 'Kurumi.Test.'+uuid4().hex
        first = SingleInstance(scope)
        try:
            self.assertTrue(first.primary)
            second = SingleInstance(scope)
            self.assertFalse(second.primary)
            self.assertTrue(first.activated())
            self.assertFalse(first.activated())
        finally:
            first.close()
        reopened = SingleInstance(scope)
        try:
            self.assertTrue(reopened.primary)
        finally:
            reopened.close()
