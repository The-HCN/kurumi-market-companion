"""Offline notification audio. One worker, one clip at a time, no model calls."""
from __future__ import annotations
import ctypes
import hashlib
import math
from pathlib import Path
import shutil
import struct
import threading
import time
import wave
from uuid import uuid4

SOUND_MODES = {'normal': '普通提示音', 'voice': '久留美语音', 'off': '关闭声音'}
MAX_CLIP_MS = 8000


def build_chime(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate, duration = 44100, .65
    samples = []
    for index in range(round(sample_rate*duration)):
        t = index/sample_rate
        # One bell strike: a clear onset and freely decaying metallic overtones.
        attack = min(1.0, t/.003)
        fade = min(1.0, (duration-t)/.08)
        value = attack * fade * (
            .55 * math.exp(-6*t) * math.sin(2*math.pi*1568*t)
            + .17 * math.exp(-16*t) * math.sin(2*math.pi*1568*2.76*t)
            + .05 * math.exp(-24*t) * math.sin(2*math.pi*1568*5.4*t))
        samples.append(round(max(-1, min(1, value))*32767))
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(struct.pack('<'+'h'*len(samples), *samples))
    return path


def import_voice(source, audio_dir):
    source = Path(source)
    if source.suffix.lower() not in ('.wav', '.mp3') or not source.is_file():
        raise ValueError('请选择本地 WAV 或 MP3 音频文件。')
    if not 16 <= source.stat().st_size <= 20_000_000:
        raise ValueError('音频文件为空或超过 20 MB。建议使用 1–5 秒短片段。')
    data = source.read_bytes()
    if source.suffix.lower() == '.wav':
        if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
            raise ValueError('该文件不是可识别的 WAV 音频。')
    elif not (data[:3] == b'ID3' or (data[0] == 0xff and data[1] & 0xe0 == 0xe0)):
        raise ValueError('该文件不是可识别的 MP3 音频。')
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    target = audio_dir / ('kurumi-'+hashlib.sha256(data).hexdigest()[:16]+source.suffix.lower())
    if target.resolve() != source.resolve() and not target.exists():
        shutil.copy2(source, target)
    return target


class WinMCI:
    def __init__(self):
        self.lib = ctypes.WinDLL('winmm')
        self.lib.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        self.lib.mciSendStringW.restype = ctypes.c_uint
        self.lib.mciGetErrorStringW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
        self.alias = 'kurumi_'+uuid4().hex
        self.opened = False

    def command(self, command, ignore_error=False):
        buffer = ctypes.create_unicode_buffer(512)
        result = self.lib.mciSendStringW(command, buffer, len(buffer), None)
        if result and not ignore_error:
            error = ctypes.create_unicode_buffer(256)
            self.lib.mciGetErrorStringW(result, error, len(error))
            raise RuntimeError(error.value or 'Windows 音频播放失败')
        return buffer.value

    def play(self, path, volume):
        self.stop()
        self.command(f'open "{Path(path).resolve()}" type mpegvideo alias {self.alias}')
        self.opened = True
        try:
            self.command(f'set {self.alias} time format milliseconds')
            duration = int(self.command(f'status {self.alias} length'))
            if duration <= 0:
                raise ValueError('音频长度无效')
            self.command(f'setaudio {self.alias} volume to {int(volume)*10}')
            self.command(f'play {self.alias} from 0 to {min(duration, MAX_CLIP_MS)}')
            return min(duration, MAX_CLIP_MS)
        except Exception:
            self.stop()
            raise

    def stop(self):
        if self.opened:
            self.command(f'stop {self.alias}', ignore_error=True)
            self.command(f'close {self.alias}', ignore_error=True)
            self.opened = False


class AudioPlayer:
    def __init__(self, base, report=None, backend_factory=WinMCI):
        self.base = Path(base)
        self.report = report or (lambda message: None)
        self.backend_factory = backend_factory
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.thread = None
        self.last_automatic = -float('inf')

    def play(self, settings, preview=False):
        mode = settings.get('sound_mode', 'normal')
        volume = max(0, min(100, settings.get('sound_volume', 60)))
        if mode == 'off' or volume == 0 or (not preview and settings.get('muted')):
            return False
        now = time.monotonic()
        if not preview and now-self.last_automatic < 3:
            return False
        if not preview:
            self.last_automatic = now
        normal = self.base/'assets'/'audio'/'normal.wav'
        selected = normal
        notice = '普通提示音'
        if mode == 'voice':
            voice = Path(settings.get('voice_file') or '')
            if not voice.is_absolute():
                voice = self.base/voice
            if voice.is_file() and voice.suffix.lower() in ('.wav', '.mp3'):
                selected, notice = voice, '久留美音频片段'
            else:
                notice = '尚未导入久留美语音，暂用普通提示音'
        with self.condition:
            if self.closed:
                return False
            self.pending = ('play', selected, volume, notice)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.worker, daemon=True)
                self.thread.start()
            self.condition.notify()
        return True

    def stop(self):
        with self.condition:
            self.pending = ('stop',)
            self.condition.notify()

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify()

    def worker(self):
        backend = None
        try:
            backend = self.backend_factory()
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.closed or self.pending is not None)
                    if self.closed:
                        return
                    request, self.pending = self.pending, None
                if request[0] == 'stop':
                    backend.stop()
                    continue
                _, path, volume, notice = request
                try:
                    duration = backend.play(path, volume)
                    self.report(notice + f' · {duration/1000:.1f}秒')
                except Exception:
                    normal = self.base/'assets'/'audio'/'normal.wav'
                    if Path(path).resolve() != normal.resolve():
                        try:
                            backend.play(normal, volume)
                            self.report('语音无法播放，已使用普通提示音；可换用 PCM WAV 片段')
                            continue
                        except Exception:
                            pass
                    self.report('音频播放失败，请检查输出设备或使用 PCM WAV 文件')
        except Exception:
            self.report('Windows 音频组件不可用，文字提醒继续工作')
        finally:
            if backend is not None:
                backend.stop()
