"""Generate the JSON Schema used by editors for terrain configuration files."""

from __future__ import annotations

import json
from pathlib import Path

from terrain_layers.config.json_io import terrain_config_json_schema


REPO_ROOT = Path(__file__).resolve().parent
OUTPUT_PATH = REPO_ROOT / "terrain_layers" / "terrain_config.schema.json"


def main() -> None:
    schema = terrain_config_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
