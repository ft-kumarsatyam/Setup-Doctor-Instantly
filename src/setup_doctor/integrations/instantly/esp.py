"""Map Instantly account metadata → ESP selector packs (guesses only).

When Instantly does not expose a provider, keep ``instantly`` pack + explicit
limitation text — never claim DKIM absence is proven.
"""
from __future__ import annotations

from typing import Any

from setup_doctor.checks.selectors import ESP_SELECTOR_PACKS, KNOWN_PACK_NAMES

# Instantly / mailbox provider strings → our ESP pack names.
_PROVIDER_ALIASES: dict[str, str] = {
    "google": "google",
    "gmail": "google",
    "google_workspace": "google",
    "gsuite": "google",
    "microsoft": "microsoft",
    "outlook": "microsoft",
    "office365": "microsoft",
    "o365": "microsoft",
    "azure": "microsoft",
    "airmail": "instantly",  # Instantly AirMail / custom — use instantly selectors
    "instantly": "instantly",
    "mailgun": "mailgun",
    "sendgrid": "sendgrid",
    "ses": "amazon_ses",
    "amazon_ses": "amazon_ses",
    "amazon": "amazon_ses",
    "zoho": "zoho",
    "fastmail": "fastmail",
}


def normalize_provider(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if not text:
        return None
    if text in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[text]
    if text in KNOWN_PACK_NAMES:
        return text
    # substring hints
    for key, pack in _PROVIDER_ALIASES.items():
        if key in text:
            return pack
    return None


def provider_from_account(account: dict[str, Any]) -> str | None:
    """Best-effort provider from Instantly account object fields."""
    for key in (
        "provider",
        "provider_code",
        "email_provider",
        "mailbox_provider",
        "esp",
        "type",
    ):
        pack = normalize_provider(account.get(key))
        if pack:
            return pack
    # Nested
    meta = account.get("meta") or account.get("metadata") or {}
    if isinstance(meta, dict):
        for key in ("provider", "provider_code", "esp"):
            pack = normalize_provider(meta.get(key))
            if pack:
                return pack
    return None


def esp_packs_for_accounts(accounts: list[dict[str, Any]]) -> tuple[str, ...]:
    """Ordered unique ESP packs: instantly first, then providers seen on accounts."""
    packs: list[str] = ["instantly"]
    seen = {"instantly"}
    for account in accounts:
        pack = provider_from_account(account)
        if pack and pack in ESP_SELECTOR_PACKS and pack not in seen:
            seen.add(pack)
            packs.append(pack)
    return tuple(packs)


def esp_limitation_note(packs: tuple[str, ...]) -> str:
    extras = [p for p in packs if p != "instantly"]
    if not extras:
        return (
            "DKIM selectors from Instantly guess pack only; "
            "provider metadata not exposed — not proof of absence."
        )
    return (
        f"DKIM selectors merged from Instantly account providers: {', '.join(extras)}. "
        "Still a guess pack when Instantly does not publish the live selector."
    )
