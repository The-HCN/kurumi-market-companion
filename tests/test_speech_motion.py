import unittest
from speech_motion import SpeechMotion

class SpeechMotionTests(unittest.TestCase):
    def test_continuous_mouth_cycles_without_new_characters(self):
        motion = SpeechMotion()
        motion.start(10)
        motion.character('机', now=10)
        frames = [motion.mouth_open(10+i*.02) for i in range(100)]
        transitions = sum(a != b for a, b in zip(frames, frames[1:]))
        self.assertGreaterEqual(transitions, 12)
        self.assertTrue(any(frames))
        self.assertFalse(all(frames))

    def test_typing_speed_does_not_restart_mouth_cycle(self):
        slow, fast = SpeechMotion(), SpeechMotion()
        for motion in (slow, fast):
            motion.start(0)
            motion.character('机', now=0)
        for index in range(100):
            now = index*.02
            fast.character('会', now=now)
            if index % 5 == 0:
                slow.character('会', now=now)
            self.assertEqual(fast.mouth_open(now), slow.mouth_open(now))

    def test_punctuation_metadata_and_stop_close_mouth(self):
        motion = SpeechMotion()
        motion.start(0)
        motion.character('机', now=0)
        self.assertTrue(motion.mouth_open(.04))
        motion.character('，', hold=.3, now=.04)
        self.assertFalse(motion.mouth_open(.05))
        motion.character('会', now=.1)
        self.assertFalse(motion.mouth_open(.2))
        self.assertTrue(motion.mouth_open(.35))
        motion.character('源', voiced=False, now=.4)
        self.assertFalse(motion.mouth_open(.5))
        motion.stop()
        self.assertFalse(motion.mouth_open(2))
        motion.start(5)
        self.assertFalse(motion.mouth_open(5.1))

if __name__ == '__main__':
    unittest.main()
