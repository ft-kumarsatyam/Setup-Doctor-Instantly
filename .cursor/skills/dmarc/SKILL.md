---
name: dmarc
description: >-
  DMARC-focused Setup Doctor findings. Use for /dmarc. Run diagnose; filter DMARC_* ids.
disable-model-invocation: true
---

# /dmarc

```bash
python -m setup_doctor DOMAIN --json
```

Present only `DMARC_*` findings and fixes. Do not invent policy recommendations beyond the engine fix text.
