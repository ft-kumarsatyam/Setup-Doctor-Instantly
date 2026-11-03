"""ESP DKIM selector packs.

DKIM selectors cannot be enumerated from DNS. These packs prepend common
provider selectors before DEFAULT_DKIM_SELECTORS. Custom selectors still
override via --dkim-selector / API field. DKIM_NOT_FOUND confidence is lower
when only guessed packs were tried (evidence.limitation stays explicit).
"""
from __future__ import annotations

ESP_SELECTOR_PACKS: dict[str, tuple[str, ...]] = {
    "google": ("google",),
    "microsoft": ("selector1", "selector2"),
    "instantly": ("instantly", "s1", "s2", "default"),
    "mailgun": ("mailo", "krs", "smtp", "pic"),
    "sendgrid": ("s1", "s2", "smtpapi"),
    "amazon_ses": ("xxxxxx",),  # SES uses account-specific; treat as hint only
    "zoho": ("zoho", "zmail"),
    "fastmail": ("fm1", "fm2", "fm3"),
}

KNOWN_PACK_NAMES = frozenset(ESP_SELECTOR_PACKS)


def resolve_selectors(
    *,
    explicit: tuple[str, ...] = (),
    packs: tuple[str, ...] = (),
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    """Build ordered unique selector list: explicit, then pack members, then defaults."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(items: tuple[str, ...] | list[str]) -> None:
        for s in items:
            key = s.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)

    _add(explicit)
    for pack in packs:
        name = pack.strip().lower()
        if name not in ESP_SELECTOR_PACKS:
            raise ValueError(
                f"unknown ESP selector pack {pack!r}; "
                f"known: {', '.join(sorted(ESP_SELECTOR_PACKS))}"
            )
        _add(ESP_SELECTOR_PACKS[name])
    _add(defaults)
    return tuple(out)
