---
name: diagnose
description: >-
  Full Setup Doctor DNS diagnosis for a domain (SPF/DKIM/DMARC/MX). Use for
  /diagnose or when asked to check cold-email DNS health. Never invent findings.
disable-model-invocation: true
---

# /diagnose

## Steps

1. Parse domain (and optional `--dkim-selector` / `--esp-pack` / `--advisory`).
2. From the repo root (or with `setup-doctor` on PATH), run:

```bash
python -m setup_doctor DOMAIN --json
# optional:
python -m setup_doctor DOMAIN --json --advisory
python -m setup_doctor DOMAIN --json --esp-pack google --dkim-selector myselector
```

3. Present `findings` and the markdown `report` from the JSON (`schema_version` should be `1.0`).
4. If exit code 2: report resolver/NXDOMAIN error — do **not** invent SPF_MISSING etc.

## Do not

- Add finding ids that are not in the JSON.
- Claim DKIM is proven absent for custom selectors not passed in.
