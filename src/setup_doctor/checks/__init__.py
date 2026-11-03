"""Deterministic finding producers + registry. Source of truth for what is wrong."""
from .engine import (
    DEFAULT_DKIM_SELECTORS,
    check_bimi,
    check_dkim,
    check_dmarc,
    check_mta_sts,
    check_mx,
    check_spf,
    check_tls_rpt,
    dkim_rsa_key_bits,
    run_checks,
)
from .registry import ALL_DNS_PACKS, DEFAULT_PACKS, CheckRegistry, CheckSpec, get_default_registry
from .selectors import ESP_SELECTOR_PACKS, KNOWN_PACK_NAMES, resolve_selectors

__all__ = [
    "DEFAULT_DKIM_SELECTORS",
    "DEFAULT_PACKS",
    "ALL_DNS_PACKS",
    "ESP_SELECTOR_PACKS",
    "KNOWN_PACK_NAMES",
    "CheckRegistry",
    "CheckSpec",
    "check_bimi",
    "check_dkim",
    "check_dmarc",
    "check_mta_sts",
    "check_mx",
    "check_spf",
    "check_tls_rpt",
    "dkim_rsa_key_bits",
    "get_default_registry",
    "resolve_selectors",
    "run_checks",
]
