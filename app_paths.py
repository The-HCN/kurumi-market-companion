"""Paths for source checkout and the portable Windows folder."""
from pathlib import Path
import sys

BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
