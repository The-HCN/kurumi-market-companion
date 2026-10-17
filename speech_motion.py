"""Shared, time-based mouth motion, independent of the typewriter speed."""
import time

class SpeechMotion:
    # Slightly varied syllable timing: open / closed, about 3–4 cycles per second.
    PHASES = (.13, .09, .16, .10, .11, .08, .15, .12)
    PUNCTUATION = '。，！？；：、,.!?;:…\n\t '

    def __init__(self):
        self.stop()

    def start(self, now=None):
        self.started = time.monotonic() if now is None else now
        self.running = True
        self.voiced = False
        self.pause_until = self.started

    def stop(self):
        self.running = self.voiced = False
        self.started = self.pause_until = 0.0

    def character(self, character, voiced=True, hold=0.0, now=None):
        now = time.monotonic() if now is None else now
        self.voiced = voiced and character not in self.PUNCTUATION
        if voiced and character in self.PUNCTUATION:
            self.pause_until = max(self.pause_until, now+hold)

    def mouth_open(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.running or not self.voiced or now < self.pause_until:
            return False
        phase = max(0.0, now-self.started) % sum(self.PHASES)
        for index, duration in enumerate(self.PHASES):
            if phase < duration:
                return index % 2 == 0
            phase -= duration
        return False
