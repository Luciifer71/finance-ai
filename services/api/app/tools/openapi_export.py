"""Write the API contract to ``packages/contracts/openapi.json``.

    python -m app.tools.openapi_export          # write the file
    python -m app.tools.openapi_export --check  # exit 1 if the file is stale

The mobile app is built against this file, so a test fails whenever the code
and the committed contract disagree.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.core.config import REPO_ROOT, Settings

CONTRACT_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.json"


def build_openapi() -> dict[str, Any]:
    from app.main import create_app

    # Fixed settings so the output never depends on the local environment.
    app = create_app(Settings(app_env="development", database_url=None, auth_mode="jwks"))
    return app.openapi()


def render_openapi() -> str:
    return json.dumps(build_openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    rendered = render_openapi()
    path: Path = CONTRACT_PATH
    if argv == ["--check"]:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != rendered:
            print(f"{path} is stale: run `python scripts/dev.py export-openapi`", file=sys.stderr)
            return 1
        print("openapi.json is up to date")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
