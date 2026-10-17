import tempfile
import threading
import unittest
import wave
from pathlib import Path
from sound_engine import AudioPlayer, build_chime, import_voice


class FakeBackend:
    def __init__(self):
        self.played = []
        self.play_event = threading.Event()
        self.stop_event = threading.Event()

    def play(self, path, volume):
        self.played.append((Path(path), volume))
        self.play_event.set()
        return 420

    def stop(self):
        self.stop_event.set()


class SoundTests(unittest.TestCase):
    def test_chime_is_valid_short_pcm_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = build_chime(Path(directory)/'notice.wav')
            with wave.open(str(path), 'rb') as clip:
                self.assertEqual((clip.getnchannels(), clip.getsampwidth()), (1, 2))
                self.assertAlmostEqual(clip.getnframes()/clip.getframerate(), .65, places=2)
                self.assertEqual(clip.readframes(1), b'\x00\x00')

    def test_import_preserves_source_and_rejects_disguised_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = build_chime(folder/'original.wav')
            original = source.read_bytes()
            imported = import_voice(source, folder/'assets')
            self.assertNotEqual(source, imported)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(imported.read_bytes(), original)
            self.assertEqual(import_voice(source, folder/'assets'), imported)
            fake = folder/'fake.mp3'
            fake.write_bytes(b'This is not an audio file')
            with self.assertRaises(ValueError):
                import_voice(fake, folder/'assets')

    def test_off_zero_volume_and_pause_never_start_playback(self):
        backend = FakeBackend()
        player = AudioPlayer('.', backend_factory=lambda: backend)
        try:
            self.assertFalse(player.play({'sound_mode': 'off'}))
            self.assertFalse(player.play({'sound_volume': 0}))
            self.assertFalse(player.play({'muted': True}))
            self.assertIsNone(player.thread)
        finally:
            player.close()

    def test_missing_voice_falls_back_and_close_stops_worker(self):
        backend = FakeBackend()
        reports = []
        player = AudioPlayer('.', report=reports.append, backend_factory=lambda: backend)
        try:
            self.assertTrue(player.play({'sound_mode': 'voice', 'voice_file': 'not-here.wav', 'sound_volume': 37}))
            self.assertTrue(backend.play_event.wait(1))
            self.assertEqual(backend.played[0][0].name, 'normal.wav')
            self.assertEqual(backend.played[0][1], 37)
            self.assertFalse(player.play({'sound_mode': 'normal'}))  # Automatic cooldown.
            player.stop()
            self.assertTrue(backend.stop_event.wait(1))
        finally:
            player.close()
            player.thread.join(timeout=1)
        self.assertFalse(player.thread.is_alive())
        self.assertFalse(player.play({'sound_mode': 'normal'}, preview=True))
        self.assertTrue(any('尚未导入' in message for message in reports))

    def test_unsupported_voice_codec_falls_back_without_blocking(self):
        class RejectVoice(FakeBackend):
            def play(self, path, volume):
                if Path(path).name == 'voice.wav':
                    raise RuntimeError('unsupported codec')
                return super().play(path, volume)
        with tempfile.TemporaryDirectory() as directory:
            voice = build_chime(Path(directory)/'voice.wav')
            backend = RejectVoice()
            reports = []
            player = AudioPlayer('.', report=reports.append, backend_factory=lambda: backend)
            try:
                self.assertTrue(player.play({'sound_mode': 'voice', 'voice_file': str(voice)}))
                self.assertTrue(backend.play_event.wait(1))
            finally:
                player.close()
                player.thread.join(timeout=1)
            self.assertEqual(backend.played[0][0].name, 'normal.wav')
            self.assertTrue(any('已使用普通提示音' in message for message in reports))
