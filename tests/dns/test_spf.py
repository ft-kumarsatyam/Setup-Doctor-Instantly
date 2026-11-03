from evals.fixtures import CASES

from setup_doctor import FixtureResolver
from setup_doctor.dns.spf import (
    all_qualifier,
    count_lookups,
    count_void_lookups,
    find_spf_records,
    has_redirect,
    uses_ptr,
)

BY_NAME = {c["name"]: c for c in CASES}


def lookups(name):
    c = BY_NAME[name]
    return count_lookups(c["domain"], FixtureResolver(c["records"]))


def test_boundary_ten_is_allowed_eleven_is_not():
    assert lookups("spf_exactly_10_lookups") == (10, False)
    assert lookups("spf_11_lookups") == (11, False)


def test_nested_includes_are_counted_recursively():
    # hand-counted: root 3 (include, a, mx) + n1 12 = 15
    assert lookups("spf_nested_lookups") == (15, False)


def test_include_loop_terminates_and_is_reported():
    count, loop = lookups("spf_include_loop")
    assert loop is True and count < 100


def test_same_include_twice_is_charged_twice():
    r = FixtureResolver({
        "d.test": {"TXT": ["v=spf1 include:x.test include:x.test -all"]},
        "x.test": {"TXT": ["v=spf1 a -all"]},
    })
    assert count_lookups("d.test", r) == (4, False)  # 2 includes + 2 inner 'a'


def test_free_mechanisms_cost_nothing():
    r = FixtureResolver({"d.test": {"TXT": ["v=spf1 ip4:192.0.2.1 ip6:2001:db8::/32 -all"]}})
    assert count_lookups("d.test", r) == (0, False)


def test_a_and_mx_variants_are_counted():
    r = FixtureResolver({"d.test": {"TXT": ["v=spf1 a a:foo.test a/24 mx mx:bar.test mx/24 -all"]}})
    assert count_lookups("d.test", r)[0] == 6


def test_all_qualifier_defaults_to_plus():
    assert all_qualifier("v=spf1 all") == "+"
    assert all_qualifier("v=spf1 -all") == "-"
    assert all_qualifier("v=spf1 ~all") == "~"
    assert all_qualifier("v=spf1 ?all") == "?"
    assert all_qualifier("v=spf1 include:x.test") is None


def test_helpers_ignore_case_and_whitespace():
    assert find_spf_records(["  V=SPF1 -all  ", "google-site-verification=abc"]) == ["V=SPF1 -all"]
    assert has_redirect("v=spf1 REDIRECT=x.test")
    assert uses_ptr("v=spf1 -ptr -all") and uses_ptr("v=spf1 ptr:foo.test -all")
    assert not uses_ptr("v=spf1 include:ptr.test -all")  # 'ptr' inside a domain name is not the mechanism


def test_void_lookup_boundary_two_ok_three_flagged():
    c2 = BY_NAME["spf_void_exactly_2"]
    c3 = BY_NAME["spf_void_3_includes"]
    assert count_void_lookups(c2["domain"], FixtureResolver(c2["records"])) == 2
    assert count_void_lookups(c3["domain"], FixtureResolver(c3["records"])) == 3


def test_void_lookups_count_empty_a_and_mx():
    r = FixtureResolver({
        "d.test": {"TXT": ["v=spf1 a mx include:gone.test -all"], "MX": [], "A": []},
    })
    # a void + mx void + include void = 3
    assert count_void_lookups("d.test", r) == 3
