"""Read-only Instantly API v2 client.

Endpoints and scopes (documented; no inventing):
- GET  /accounts                         scopes: accounts:read | …
- POST /accounts/warmup-analytics        scopes: accounts:read | …
- GET  /inbox-placement-tests            scopes: inbox_placement_tests:read | …
- POST /inbox-placement-analytics/stats-by-test-id
  scopes: inbox_placement_analytics:read | …
- POST /accounts/test/vitals             scopes: accounts:read | …
- GET  /accounts/ctd/status              scopes: accounts:read | …
- POST /inbox-placement-analytics/deliverability-insights
- GET  /inbox-placement-reports          scopes: inbox_placement_reports:read | … (requires test_id)
- GET  /ai-agents/deliverability/state
- GET  /ai-agents/deliverability/{id}/feed-items
- GET  /campaigns/{id}/sending-status

Auth: Authorization Bearer — https://developer.instantly.ai/getting-started/authorization
Rate limits / 429: https://developer.instantly.ai/getting-started/rate-limit
Mock base: https://developer.instantly.ai/_mock/api/v2
Live base: https://api.instantly.ai/api/v2

The API key must come from INSTANTLY_API_KEY (or an explicit constructor arg for tests).
It is never logged. No write/mutation endpoints.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

LIVE_BASE = "https://api.instantly.ai/api/v2"
MOCK_BASE = "https://developer.instantly.ai/_mock/api/v2"

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes, dict[str, str]]]


class InstantlyError(RuntimeError):
    """Non-retryable Instantly API failure."""

    def __init__(self, status: int, path: str, body: str):
        self.status = status
        self.path = path
        # Body may contain account emails; keep it for callers but never log the key.
        super().__init__(f"Instantly API HTTP {status} on {path}")
        self.body = body


def _stdlib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return int(resp.status), raw, {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp else b""
        return int(exc.code), raw, {k.lower(): v for k, v in (exc.headers or {}).items()}


def api_key_from_env() -> str:
    key = os.environ.get("INSTANTLY_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "Set INSTANTLY_API_KEY to a read-scoped Instantly API v2 key "
            "(accounts:read, inbox_placement_tests:read, inbox_placement_analytics:read)."
        )
    return key


def base_url_from_env() -> str:
    if os.environ.get("INSTANTLY_USE_MOCK", "").strip().lower() in ("1", "true", "yes"):
        return MOCK_BASE
    return (os.environ.get("INSTANTLY_BASE_URL") or LIVE_BASE).rstrip("/")


class InstantlyClient:
    """Minimal read-only client with 429 backoff."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 5,
        as_workspace: str | None = None,
    ):
        self._api_key = api_key if api_key is not None else api_key_from_env()
        self._base = (base_url or base_url_from_env()).rstrip("/")
        self._transport = transport or _stdlib_transport
        self._sleep = sleep
        self._max_retries = max_retries
        # Agency workspace-group: call Instantly "as" a sub-workspace.
        # https://developer.instantly.ai/guides/workspace-group
        self._as_workspace = (as_workspace or "").strip() or None

    def with_workspace(self, workspace_id: str | None) -> InstantlyClient:
        """Return a client that sends x-as-workspace for sub-workspace calls."""
        return InstantlyClient(
            api_key=self._api_key,
            base_url=self._base,
            transport=self._transport,
            sleep=self._sleep,
            max_retries=self._max_retries,
            as_workspace=workspace_id,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "setup-doctor/0.1",
        }
        if self._as_workspace:
            headers["x-as-workspace"] = self._as_workspace
        return headers

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                json_body: Any | None = None) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{self._base}{path}" + (f"?{query}" if query else "")
        body = None if json_body is None else json.dumps(json_body).encode("utf-8")
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            status, raw, headers = self._transport(method.upper(), url, self._headers(), body)
            if status == 429 and attempt < self._max_retries:
                retry_after = headers.get("retry-after")
                try:
                    wait = float(retry_after) if retry_after else delay
                except ValueError:
                    wait = delay
                self._sleep(max(wait, 0.1))
                delay = min(delay * 2, 30.0)
                continue
            text = raw.decode("utf-8", "replace")
            if status >= 400:
                raise InstantlyError(status, path, text)
            if not text.strip():
                return None
            return json.loads(text)
        raise InstantlyError(429, path, "rate limit retries exhausted")

    def list_accounts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Paginate GET /accounts. Fields of interest: email, stat_warmup_score."""
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        while True:
            data = self.request(
                "GET", "/accounts",
                params={"limit": limit, "starting_after": starting_after},
            )
            batch = data.get("items") if isinstance(data, dict) else data
            if not isinstance(batch, list):
                break
            items.extend(batch)
            starting_after = data.get("next_starting_after") if isinstance(data, dict) else None
            if not starting_after or not batch:
                break
        return items

    def warmup_analytics(self, emails: list[str]) -> dict[str, Any]:
        """POST /accounts/warmup-analytics — aggregate health_score per email."""
        if not emails:
            return {"aggregate_data": {}, "email_date_data": {}}
        # API allows 1–100 emails per call.
        out: dict[str, Any] = {"aggregate_data": {}, "email_date_data": {}}
        for i in range(0, len(emails), 100):
            chunk = emails[i:i + 100]
            data = self.request("POST", "/accounts/warmup-analytics", json_body={"emails": chunk})
            if isinstance(data, dict):
                out["aggregate_data"].update(data.get("aggregate_data") or {})
                out["email_date_data"].update(data.get("email_date_data") or {})
        return out

    def list_inbox_placement_tests(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Paginate GET /inbox-placement-tests. Fields: id, emails (sending accounts)."""
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        while True:
            data = self.request(
                "GET", "/inbox-placement-tests",
                params={"limit": limit, "starting_after": starting_after},
            )
            batch = data.get("items") if isinstance(data, dict) else data
            if not isinstance(batch, list):
                break
            items.extend(batch)
            starting_after = data.get("next_starting_after") if isinstance(data, dict) else None
            if not starting_after or not batch:
                break
        return items

    def inbox_placement_stats_by_test_ids(self, test_ids: list[str]) -> list[dict[str, Any]]:
        """POST /inbox-placement-analytics/stats-by-test-id."""
        if not test_ids:
            return []
        results: list[dict[str, Any]] = []
        for i in range(0, len(test_ids), 50):
            chunk = test_ids[i:i + 50]
            data = self.request(
                "POST", "/inbox-placement-analytics/stats-by-test-id",
                json_body={"test_ids": chunk},
            )
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict) and isinstance(data.get("items"), list):
                results.extend(data["items"])
        return results

    def test_account_vitals(self, accounts: list[str] | None = None) -> dict[str, Any]:
        """POST /accounts/test/vitals — boolean mx/spf/dkim/dmarc per domain.

        https://developer.instantly.ai/api-reference/account/test-account-vitals
        """
        body: dict[str, Any] = {}
        if accounts:
            body["accounts"] = accounts
        data = self.request("POST", "/accounts/test/vitals", json_body=body)
        return data if isinstance(data, dict) else {"status": "unknown", "raw": data}

    def custom_tracking_domain_status(self, host: str) -> dict[str, Any]:
        """GET /accounts/ctd/status?host= — success/ssl/cname for a tracking host.

        https://developer.instantly.ai/api-reference/account/get-custom-tracking-domain-status
        """
        data = self.request("GET", "/accounts/ctd/status", params={"host": host})
        return data if isinstance(data, dict) else {"host": host, "raw": data}

    def inbox_placement_deliverability_insights(
        self,
        test_id: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """POST /inbox-placement-analytics/deliverability-insights."""
        body: dict[str, Any] = {"test_id": test_id}
        if extra:
            body.update(extra)
        data = self.request(
            "POST", "/inbox-placement-analytics/deliverability-insights",
            json_body=body,
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        return []

    def list_inbox_placement_blacklist_reports(
        self,
        test_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginate GET /inbox-placement-reports (requires test_id)."""
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        while True:
            data = self.request(
                "GET", "/inbox-placement-reports",
                params={
                    "test_id": test_id,
                    "limit": limit,
                    "starting_after": starting_after,
                },
            )
            batch = data.get("items") if isinstance(data, dict) else data
            if not isinstance(batch, list):
                break
            items.extend(batch)
            starting_after = data.get("next_starting_after") if isinstance(data, dict) else None
            if not starting_after or not batch:
                break
        return items

    def get_default_deliverability_agent_state(self) -> dict[str, Any]:
        """GET /ai-agents/deliverability/state — default agent state (read-only).

        Missing agent is reported as agent=null by Instantly — never invent health.
        """
        data = self.request("GET", "/ai-agents/deliverability/state")
        return data if isinstance(data, dict) else {"raw": data}

    def list_deliverability_agent_feed(
        self,
        agent_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginate GET /ai-agents/deliverability/{id}/feed-items."""
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        path = f"/ai-agents/deliverability/{agent_id}/feed-items"
        while True:
            data = self.request(
                "GET", path,
                params={"limit": limit, "starting_after": starting_after},
            )
            batch = data.get("items") if isinstance(data, dict) else data
            if not isinstance(batch, list):
                break
            items.extend(batch)
            starting_after = data.get("next_starting_after") if isinstance(data, dict) else None
            if not starting_after or not batch:
                break
        return items

    def get_campaign_sending_status(self, campaign_id: str) -> dict[str, Any]:
        """GET /campaigns/{id}/sending-status — why a campaign may not be sending."""
        data = self.request("GET", f"/campaigns/{campaign_id}/sending-status")
        return data if isinstance(data, dict) else {"campaign_id": campaign_id, "raw": data}

    def get_current_workspace(self) -> dict[str, Any]:
        """GET /workspaces/current — scopes: workspaces:read | …"""
        data = self.request("GET", "/workspaces/current")
        return data if isinstance(data, dict) else {"raw": data}

    def list_workspace_group_members(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Paginate GET /workspace-group-members (admin workspace → sub-workspaces).

        Requires agency workspace-group. Missing/unauthorized ⇒ InstantlyError;
        callers should report unknown / not_checked — never invent sub-workspaces.
        """
        items: list[dict[str, Any]] = []
        starting_after: str | None = None
        while True:
            data = self.request(
                "GET", "/workspace-group-members",
                params={"limit": limit, "starting_after": starting_after},
            )
            batch = data.get("items") if isinstance(data, dict) else data
            if not isinstance(batch, list):
                break
            items.extend(batch)
            starting_after = data.get("next_starting_after") if isinstance(data, dict) else None
            if not starting_after or not batch:
                break
        return items

    def sub_workspace_ids(self) -> list[str]:
        """Extract accepted sub_workspace_id values from workspace-group members."""
        out: list[str] = []
        seen: set[str] = set()
        for row in self.list_workspace_group_members():
            if not isinstance(row, dict):
                continue
            wid = row.get("sub_workspace_id") or row.get("workspace_id")
            if isinstance(wid, str) and wid.strip() and wid not in seen:
                seen.add(wid)
                out.append(wid.strip())
        return out


class RecordingTransport:
    """Map method+path → recorded (status, body) for tests. No network."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, Any]]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []
        self.last_headers: dict[str, str] = {}

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, bytes, dict[str, str]]:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if path.startswith("/api/v2"):
            path = path[len("/api/v2"):] or "/"
        key = (method.upper(), path.rstrip("/") or "/")
        self.calls.append(key)
        self.last_headers = {k.lower(): v for k, v in headers.items()}
        # Authorization must be present; never log the secret value.
        if "authorization" not in {k.lower() for k in headers}:
            return 401, b'{"message":"Missing Authorization header"}', {}
        if key not in self.routes:
            return 404, json.dumps({"message": f"no fixture for {key}"}).encode(), {}
        status, payload = self.routes[key]
        raw = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
        hdrs: dict[str, str] = {}
        if status == 429:
            hdrs["retry-after"] = "0"
        return status, raw, hdrs
