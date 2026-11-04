"""Domain age advisory — failures stay unknown."""
from __future__ import annotations

import json

from setup_doctor.integrations.whois_age import lookup_domain_age


def test_domain_age_ok_from_rdap_transport():
    payload = {
        "events": [
            {"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
        ],
    }

    def transport(url: str):
        assert "example.com" in url
        return 200, json.dumps(payload).encode()

    sig = lookup_domain_age("example.com", transport=transport)
    assert sig.status == "ok"
    assert sig.age_days is not None and sig.age_days >= 0
    assert sig.created_at is not None


def test_domain_age_unknown_on_http_error():
    def transport(url: str):
        return 404, b"{}"

    sig = lookup_domain_age("missing.test", transport=transport)
    assert sig.status == "unknown"
    assert sig.age_days is None
