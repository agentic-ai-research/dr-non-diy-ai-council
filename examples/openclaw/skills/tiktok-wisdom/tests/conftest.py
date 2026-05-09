"""Add the skill's scripts/ dir to sys.path so tests can import build.py
and lib/* without packaging gymnastics."""
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILL_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))
