"""Export the FastAPI OpenAPI document for the web client's generated types.

Run from anywhere: `python apps/api/export_openapi.py`.
"""

import json
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(API_DIR))

from main import app  # noqa: E402

TARGET = API_DIR.parent / "web" / "lib" / "api" / "openapi.json"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"Wrote {TARGET}")


if __name__ == "__main__":
    main()
