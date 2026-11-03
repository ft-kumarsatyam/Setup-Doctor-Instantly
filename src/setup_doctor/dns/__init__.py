"""DNS access and SPF parsing (deterministic, injectable Resolver)."""
from .resolver import FixtureResolver, LiveResolver, Resolver, ResolverError
from .spf import (
    all_qualifier,
    count_lookups,
    count_void_lookups,
    find_spf_records,
    has_redirect,
    uses_ptr,
)

__all__ = [
    "FixtureResolver",
    "LiveResolver",
    "Resolver",
    "ResolverError",
    "all_qualifier",
    "count_lookups",
    "count_void_lookups",
    "find_spf_records",
    "has_redirect",
    "uses_ptr",
]
