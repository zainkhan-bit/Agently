"""The client IP never comes from a header value the client controls."""

import pytest

from app.core.client_ip import resolve_client_ip, throttle_network

PEER = "10.0.0.5"


@pytest.mark.parametrize(
    ("forwarded", "hops", "expected"),
    [
        ([], 0, PEER),
        (["1.1.1.1"], 0, PEER),  # spoofed header ignored when no proxy is trusted
        (["1.1.1.1, 9.9.9.9"], 1, "9.9.9.9"),
        (["1.1.1.1", "9.9.9.9"], 1, "9.9.9.9"),  # repeated headers are one list
        (["1.1.1.1, 9.9.9.9, 10.0.0.9"], 2, "9.9.9.9"),
        (["9.9.9.9"], 2, PEER),  # shorter than the trusted chain
        (["not-an-ip\nforged log line"], 1, PEER),
        ([" 2001:db8::1 "], 1, "2001:db8::1"),
    ],
)
def test_resolve_client_ip(forwarded: list[str], hops: int, expected: str) -> None:
    assert resolve_client_ip(forwarded, PEER, hops) == expected


@pytest.mark.parametrize("peer", ["", "x event=login_succeeded", "fe80::1%x event=y"])
def test_invalid_peer_is_never_returned(peer: str) -> None:
    assert resolve_client_ip([], peer, 0) == "unknown"


@pytest.mark.parametrize(
    ("ip", "network"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::"),
        ("unknown", "unknown"),
    ],
)
def test_throttle_network_groups_one_ipv6_customer(ip: str, network: str) -> None:
    assert throttle_network(ip) == network
