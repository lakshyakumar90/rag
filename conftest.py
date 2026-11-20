"""Make the FastAPI app's top-level modules importable from tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "apps" / "api"))
