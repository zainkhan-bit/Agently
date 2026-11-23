"""Resolve the client IP without trusting header values the client controls."""

from collections.abc import Sequence
from ipaddress import IPv6Address, ip_address, ip_network

from starlette.requests import Request

from app.core.config import get_settings


def resolve_client_ip(forwarded_for: Sequence[str], peer: str, hops: int) -> str:
    """Return the address the outermost of ``hops`` trusted proxies saw, else the socket peer.

    Each trusted proxy appends one entry to X-Forwarded-For, so only the last ``hops`` entries
    are trustworthy. Never returns text that is not an IP address (it is written to logs).

    Run uvicorn with --no-proxy-headers: by default it replaces the socket peer with
    X-Forwarded-For for connections from this machine, before this code sees it.
    """
    peer = _valid_ip(peer) or "unknown"
    entries = [entry.strip() for value in forwarded_for for entry in value.split(",")]
    if hops <= 0 or len(entries) < hops:
        return peer
    return _valid_ip(entries[-hops]) or peer


def throttle_network(ip: str) -> str:
    """The part of an address one customer controls: an IPv4 address, or an IPv6 /64."""
    if _valid_ip(ip) is None:
        return ip
    address = ip_address(ip)
    if not isinstance(address, IPv6Address):
        return str(address)
    if address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(ip_network((address, 64), strict=False).network_address)


def _valid_ip(value: str) -> str | None:
    if "%" in value:  # an IPv6 scope id may hold any text
        return None
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = get_settings().trusted_proxy_hops or 0
    return resolve_client_ip(request.headers.getlist("x-forwarded-for"), peer, hops)
