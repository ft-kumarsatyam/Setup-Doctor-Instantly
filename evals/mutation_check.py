"""Prove the evals can fail. Entry point — mutants defined in evals.mutations."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evals.mutations.mutation_check import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
