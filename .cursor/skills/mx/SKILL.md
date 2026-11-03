---
name: mx
description: >-
  MX presence check via Setup Doctor. Use for /mx. Run diagnose; report MX_MISSING only if present in findings.
disable-model-invocation: true
---

# /mx

```bash
python -m setup_doctor DOMAIN --json
```

If `MX_MISSING` is in findings, explain using that finding's why/fix. Otherwise state MX check passed (no MX finding).
