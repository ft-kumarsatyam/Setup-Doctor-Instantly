---
name: spf
description: >-
  Explain SPF-related Setup Doctor findings for a domain. Use for /spf. Run the
  real diagnose engine; filter to SPF_* ids only when presenting.
disable-model-invocation: true
---

# /spf

```bash
python -m setup_doctor DOMAIN --json
```

Filter `findings` to ids starting with `SPF_`. Present those and their fix text only. If none, say SPF checks found no issues (other records may still be wrong — offer `/diagnose`).
