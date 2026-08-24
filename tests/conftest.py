"""Put the repo root on sys.path so `custom_components.emeraldenergy` imports."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
