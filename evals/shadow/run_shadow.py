"""Shadow corpus runner — reports separately; never invents labels."""
from __future__ import annotations

import json
from pathlib import Path

SHADOW_FILE = Path(__file__).resolve().parent / "shadow_cases.json"


def load_shadow_cases() -> list[dict]:
    if not SHADOW_FILE.exists():
        return []
    return json.loads(SHADOW_FILE.read_text())


def eval_shadow() -> dict:
    cases = load_shadow_cases()
    if not cases:
        return {"status": "skipped", "cases": 0, "note": "no shadow_cases.json"}
    # Live DNS + labels are operator-supplied; CI stays offline.
    return {
        "status": "present_not_run_in_ci",
        "cases": len(cases),
        "note": "Shadow file present; run manually against LiveResolver — not scored in CI.",
    }
