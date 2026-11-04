"""Optional outbound notifications (Slack). Failures never invent Findings."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def slack_webhook_url() -> str | None:
    url = os.environ.get("SETUP_DOCTOR_SLACK_WEBHOOK_URL", "").strip()
    return url or None


def notify_slack(
    text: str,
    *,
    webhook_url: str | None = None,
    transport=None,
) -> dict[str, Any]:
    """POST a simple Slack incoming-webhook message. Returns status dict."""
    url = webhook_url if webhook_url is not None else slack_webhook_url()
    if not url:
        return {"status": "not_checked", "note": "SETUP_DOCTOR_SLACK_WEBHOOK_URL unset"}
    body = json.dumps({"text": text}).encode("utf-8")
    try:
        if transport is not None:
            status, _raw = transport(url, body)
        else:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "setup-doctor/0.2"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                status = int(resp.status)
                _raw = resp.read()
        if 200 <= status < 300:
            return {"status": "ok"}
        return {"status": "unknown", "note": f"Slack HTTP {status}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "unknown", "note": f"Slack notify failed: {type(exc).__name__}"}
