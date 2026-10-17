"""Package the existing Kurumi portrait as a multi-resolution Windows icon."""
from pathlib import Path
from PIL import Image, ImageDraw
from character import load_frames

base = Path(__file__).resolve().parent
face = load_frames(base / 'assets' / 'kurumi-sheet-v3.png')[0].crop((25, 10, 487, 370))
face.thumbnail((238, 224), Image.Resampling.LANCZOS)
icon = Image.new('RGBA', (256, 256))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((3, 3, 253, 253), radius=56, fill='#252737', outline='#f3a6c6', width=6)
icon.alpha_composite(face, ((256-face.width)//2, (256-face.height)//2+4))
icon.save(base / 'assets' / 'kurumi-icon.png')
icon.save(base / 'assets' / 'kurumi.ico', sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
print('Created Kurumi PNG and Windows ICO (16–256 px).')
