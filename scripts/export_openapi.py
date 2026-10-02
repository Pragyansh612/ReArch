"""Write the API contract: docs/openapi.json (the source for web/src/lib/api-types.ts).   python scripts/export_openapi.py"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from api.app.main import create_app
from api.app.settings import ROOT, Settings


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:  # a throwaway database: exporting must not touch real data
        app = create_app(Settings(data_dir=Path(tmp), seed_demo_on_start=False), seed=False)
        spec = app.openapi()
    target = ROOT / "docs" / "openapi.json"
    target.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target}: {len(spec['paths'])} paths, {len(spec['components']['schemas'])} schemas")


if __name__ == "__main__":
    main()
