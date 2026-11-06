"""Join frozen public DNS records with hand-written labels.

Records and labels are separate files so a refresh of the snapshot cannot
silently rewrite the expected finding ids.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_public_cases() -> list[dict]:
    corpus = json.loads((HERE / "public_dns.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    by_label = {row["domain"]: row for row in labels}
    cases = []
    for row in corpus["cases"]:
        domain = row["domain"]
        label = by_label.get(domain)
        if label is None:
            raise RuntimeError(f"public corpus: {domain} has records and no label")
        cases.append({
            "name": domain,
            "domain": domain,
            "records": row["records"],
            "expected": sorted(label["expected"]),
            "note": label.get("note", ""),
        })
    extra = sorted(set(by_label) - {c["domain"] for c in cases})
    if extra:
        raise RuntimeError(f"public corpus: labels without records: {extra}")
    return cases
