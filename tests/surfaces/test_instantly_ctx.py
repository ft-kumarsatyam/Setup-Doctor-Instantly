"""Instantly key resolution — never invent signals when key missing."""
from __future__ import annotations

import pytest

from setup_doctor.integrations.instantly import InstantlyClient
from setup_doctor.surfaces.auth import Tenant
from setup_doctor.surfaces.instantly_ctx import (
    extract_instantly_header,
    fingerprint_instantly_key,
    make_request_instantly_factory,
    resolve_instantly_api_key,
    resolve_instantly_client,
)


def test_extract_instantly_header_case_insensitive():
    assert extract_instantly_header({"X-Instantly-Api-Key": " secret "}) == "secret"
    assert extract_instantly_header({"x-instantly-api-key": "k"}) == "k"
    assert extract_instantly_header({"Authorization": "Bearer x"}) is None
    assert extract_instantly_header(None) is None


def test_fingerprint_does_not_contain_full_key():
    key = "sk_live_super_secret_instantly_key"
    fp = fingerprint_instantly_key(key)
    assert key not in fp
    assert "sk_l" in fp or fp.startswith("k_")


def test_resolve_prefers_header_over_vault_and_factory(monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY", raising=False)
    called = {"factory": False}

    def factory():
        called["factory"] = True
        return InstantlyClient(api_key="from-factory")

    vault = {"acme": "from-vault"}
    client = resolve_instantly_client(
        header_value="from-header",
        tenant=Tenant(api_key_id="k_test", tenant_id="acme"),
        vault=lambda tid: vault.get(tid),
        factory=factory,
    )
    assert client._api_key == "from-header"
    assert called["factory"] is False


def test_resolve_uses_vault_when_no_header(monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY", raising=False)
    client = resolve_instantly_client(
        tenant=Tenant(api_key_id="k_test", tenant_id="acme"),
        vault=lambda tid: "vault-key" if tid == "acme" else None,
        env_fallback=False,
    )
    assert client._api_key == "vault-key"


def test_resolve_factory_when_no_request_key(monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY", raising=False)
    client = resolve_instantly_client(
        factory=lambda: InstantlyClient(api_key="factory-key"),
        env_fallback=False,
    )
    assert client._api_key == "factory-key"


def test_resolve_raises_without_any_source(monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY", raising=False)
    with pytest.raises(ValueError, match="Instantly API key"):
        resolve_instantly_client(env_fallback=False)


def test_resolve_api_key_order():
    assert resolve_instantly_api_key(explicit=" a ", header_value="b") == "a"
    assert resolve_instantly_api_key(header_value="b") == "b"
    assert resolve_instantly_api_key() is None


def test_make_request_factory_closes_over_header(monkeypatch):
    monkeypatch.delenv("INSTANTLY_API_KEY", raising=False)
    factory = make_request_instantly_factory(
        header_value="hdr",
        base_factory=lambda: InstantlyClient(api_key="base"),
    )
    assert factory()._api_key == "hdr"

    factory2 = make_request_instantly_factory(
        header_value=None,
        base_factory=lambda: InstantlyClient(api_key="base"),
    )
    assert factory2()._api_key == "base"
