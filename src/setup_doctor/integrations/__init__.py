"""External adapters that emit signals — never fabricated health."""
from .reputation import (
    NullReputationProvider,
    ReputationProvider,
    ReputationSignal,
    StaticListProvider,
    check_reputation,
    get_reputation_provider,
)

__all__ = [
    "NullReputationProvider",
    "ReputationProvider",
    "ReputationSignal",
    "StaticListProvider",
    "check_reputation",
    "get_reputation_provider",
]
