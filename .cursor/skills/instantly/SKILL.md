---
name: instantly
description: >-
  Instantly warmup vs inbox-placement compare (read-only). Use for /instantly.
  Missing scores are unknown — never report healthy when data is absent.
disable-model-invocation: true
---

# /instantly

Requires `INSTANTLY_API_KEY`.

```bash
python -m setup_doctor --instantly-compare
python -m setup_doctor --instantly-compare --json
# or attach to a domain diagnosis:
python -m setup_doctor DOMAIN --with-instantly --json
```

When presenting: quote `verdict` and `note` from the engine. **unknown** means data missing — do not soften to healthy.
