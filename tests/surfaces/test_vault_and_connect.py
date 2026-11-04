"""Encrypted Instantly key vault + /connect/instantly."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from setup_doctor.dns.resolver import FixtureResolver
from setup_doctor.surfaces.api import create_app
from setup_doctor.surfaces.auth import ApiKeyAuth
from setup_doctor.surfaces.vault import EncryptedTenantVault, seal, unseal


def test_seal_roundtrip():
    token = seal("master-secret", "instantly-key-abc")
    assert "instantly-key-abc" not in token
    assert unseal("master-secret", token) == "instantly-key-abc"
    with pytest.raises(ValueError):
        unseal("wrong", token)


def test_vault_put_get_delete(tmp_path: Path):
    path = tmp_path / "vault.json"
    vault = EncryptedTenantVault(master_key="m", path=path)
    fp = vault.put("acme", "sk_live_secret")
    assert "sk_live_secret" not in fp
    assert vault.get("acme") == "sk_live_secret"
    assert vault.status("acme")["connected"] is True
    # reload from disk
    vault2 = EncryptedTenantVault(master_key="m", path=path)
    assert vault2.get("acme") == "sk_live_secret"
    assert vault.delete("acme") is True
    assert vault.get("acme") is None


def test_connect_endpoint_stores_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SETUP_DOCTOR_VAULT_KEY", "test-master")
    monkeypatch.setenv("SETUP_DOCTOR_VAULT_PATH", str(tmp_path / "v.json"))
    auth = ApiKeyAuth(keys={"k1": "tenant-a"})
    app = create_app(
        resolver_factory=lambda: FixtureResolver({}),
        auth=auth,
    )
    client = TestClient(app)
    r = client.post(
        "/connect/instantly",
        json={"instantly_api_key": "instantly-secret-key"},
        headers={"X-API-Key": "k1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["tenant_id"] == "tenant-a"
    assert "instantly-secret-key" not in str(body)
    st = client.get("/connect/instantly", headers={"X-API-Key": "k1"})
    assert st.json()["connected"] is True
    # Vault lookup works for Instantly resolution
    assert app.state.instantly_vault("tenant-a") == "instantly-secret-key"
