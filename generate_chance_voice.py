"""One-time neural speech asset generation; never called by the desktop app."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE/'.runtime'))

async def main():
    import edge_tts
    import imageio_ffmpeg

    raw = BASE/'artifacts/chance-nanami.mp3'
    raw.parent.mkdir(exist_ok=True)
    request = edge_tts.Communicate('チャンス！', 'ja-JP-NanamiNeural',
                                   rate='+10%', pitch='+45Hz', volume='-5%')
    await asyncio.wait_for(request.save(str(raw)), timeout=45)
    output = BASE/'assets/audio/chance-ai.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-hide_banner', '-loglevel', 'error',
                    '-i', str(raw), '-af',
                    'silenceremove=start_periods=1:start_duration=0.015:start_threshold=-45dB:'
                    'stop_periods=1:stop_duration=0.12:stop_threshold=-45dB,'
                    'afade=t=in:st=0:d=0.008,alimiter=limit=0.8,apad=pad_dur=0.08',
                    '-ar', '44100', '-ac', '1', '-c:a', 'pcm_s16le', str(output)], check=True)
    metadata = {'text': 'チャンス！', 'meaning': '机会！', 'voice': 'ja-JP-NanamiNeural',
                'rate': '+10%', 'pitch': '+45Hz', 'volume': '-5%',
                'type': 'AI synthesized Japanese female voice',
                'generated': '2026-10-17', 'generator': 'edge-tts',
                'generation_only_online': True, 'playback': 'local WAV',
                'note': 'Generic bright female voice; no original performer audio used.'}
    output.with_suffix('.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output)

if __name__ == '__main__':
    asyncio.run(main())
