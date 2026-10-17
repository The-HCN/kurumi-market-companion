"""Lightweight sprite playback. Mouth frames are driven by typewriter state."""
import math
import time
import random
import tkinter as tk
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageTk, ImageDraw


@lru_cache(maxsize=4)
def load_frames(asset):
    sheet = Image.open(asset).convert('RGBA')
    cell_w = sheet.width // 2
    alpha = sheet.getchannel('A')
    # Generated atlas rows can be a few pixels off the mathematical grid.
    # Slice at actual transparent gutters so the next head never bleeds in.
    cuts = [0]
    for row in (1, 2):
        expected = sheet.height * row // 3
        gaps = [y for y in range(expected-55, expected+35)
                if alpha.crop((0, y, sheet.width, y+1)).getextrema()[1] < 96]
        cuts.append(round(sum(gaps)/len(gaps)) if gaps else expected)
    cuts.append(sheet.height)
    frames = []
    for row in range(3):
        for col in range(2):
            frame = sheet.crop((col*cell_w, cuts[row], (col+1)*cell_w, cuts[row+1]))
            bounds = frame.getchannel('A').point(lambda value: 255 if value >= 96 else 0).getbbox()
            if bounds:
                frame = frame.crop(bounds)
            # Windows color-key windows cannot preserve soft alpha. Keep the
            # connected character silhouette, excluding stray atlas pixels.
            mask = frame.getchannel('A').point(lambda value: 255 if value >= 96 else 0)
            seed = (frame.width//2, frame.height//2)
            if mask.getpixel(seed) == 255:
                ImageDraw.floodfill(mask, seed, 128)
                frame.putalpha(mask.point(lambda value: 255 if value == 128 else 0))
            frame.thumbnail((cell_w-36, cell_w-36), Image.Resampling.LANCZOS)
            normalized = Image.new('RGBA', (cell_w, cell_w))
            normalized.paste(frame, ((cell_w-frame.width)//2, cell_w-18-frame.height))
            frames.append(normalized)
    return frames


class CharacterView(tk.Canvas):
    def __init__(self, parent, asset: Path, bg, chroma_key=False, **kwargs):
        super().__init__(parent, bg=bg, highlightthickness=0, width=1, height=1, **kwargs)
        self.frames = load_frames(asset)
        self.mood = 'neutral'
        self.talking = False
        self.mouth_open = False
        self.speech_motion = None
        self.chroma_key = chroma_key
        self.last_mood = self.mood
        self.reaction_started = time.monotonic()
        self.sizes = {}
        self.item = self.create_image(0, 0, anchor='center')
        self.next_blink = time.monotonic() + random.uniform(3.5, 6)
        self.blink_started = None
        # Vector eyelids follow the existing neutral face; no new bitmap assets.
        self.eyelids = [self.create_polygon(0, 0, 0, 0, fill='#ffeddf', outline='', smooth=True, state='hidden') for _ in range(2)]
        self.blinking = False
        self.after(60, self.tick)

    def tick(self):
        if not self.winfo_viewable():
            self.after(150, self.tick)
            return
        width, height = self.winfo_width(), self.winfo_height()
        if width > 10 and height > 10:
            size = max(8, min(300, width-16, height-20))
            if size not in self.sizes:
                if len(self.sizes) > 3:
                    self.sizes.clear()
                resized = [frame.resize((size, size), Image.Resampling.LANCZOS) for frame in self.frames]
                if self.chroma_key:
                    # At final display size, eliminate semi-transparent pixels
                    # that Tk's Windows color-key compositor turns into a fringe.
                    for frame in resized:
                        frame.putalpha(frame.getchannel('A').point(lambda value: 255 if value >= 128 else 0))
                self.sizes[size] = [ImageTk.PhotoImage(frame) for frame in resized]
            now = time.monotonic()
            if self.speech_motion is not None:
                self.mouth_open = self.talking and self.speech_motion.mouth_open(now)
            if self.last_mood != self.mood:
                self.last_mood = self.mood
                self.reaction_started = now
            mouth = int(self.mouth_open) if self.talking else 0
            row = {'neutral': 0, 'happy': 1, 'sad': 2}[self.mood]
            photo = self.sizes[size][row*2 + mouth]
            self.itemconfigure(self.item, image=photo)
            elapsed = now-self.reaction_started
            bob = -3 * math.sin(math.pi*elapsed/.8) if self.mood == 'happy' and elapsed < .8 else 0
            breath = .8 * math.sin(now*2*math.pi/4.5)
            cx, cy = width/2, height/2+bob+breath
            self.coords(self.item, cx, cy)
            self.animate_blink(now, size, cx, cy)
        self.after(33, self.tick)

    def animate_blink(self, now, size, cx, cy):
        if self.mood != 'neutral' or self.talking:
            self.blink_started = None
            self.next_blink = max(self.next_blink, now+1)
        elif self.blink_started is None and now >= self.next_blink:
            self.blink_started = now
        if self.blink_started is not None and now-self.blink_started >= .14:
            self.blink_started = None
            self.next_blink = now+random.uniform(3.5, 6.5)
        self.blinking = self.blink_started is not None
        points = [((140, 229), (212, 230), (222, 255), (214, 278), (194, 285), (161, 282), (141, 266), (137, 246)),
                  ((281, 234), (352, 237), (360, 259), (349, 284), (321, 290), (293, 280), (279, 258), (278, 242))]
        for item, polygon in zip(self.eyelids, points):
            coords = [value for x, y in polygon for value in (cx+(x/512-.5)*size, cy+(y/512-.5)*size)]
            self.coords(item, *coords)
            self.itemconfigure(item, state='normal' if self.blinking else 'hidden')
