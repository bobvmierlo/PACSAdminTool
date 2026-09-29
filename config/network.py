"""
Sender allowlists for the built-in DICOM and HL7 listeners.

An allowlist is a list of IP addresses and/or CIDR networks
(e.g. ``["10.1.2.3", "10.20.0.0/16"]``). An empty list means
"accept every sender", which keeps the listeners open by default.
"""

import ipaddress
import logging

logger = logging.getLogger(__name__)


def validate_host_entry(entry: str) -> str | None:
    """Return an error message if *entry* is not an IP address or CIDR network."""
    if not isinstance(entry, str) or not entry.strip():
        return "must be a non-empty string"
    try:
        ipaddress.ip_network(entry.strip(), strict=False)
    except ValueError:
        return f"'{entry}' is not a valid IP address or CIDR network"
    return None


def parse_host_allowlist(entries) -> list:
    """Turn config entries into ip_network objects, skipping invalid ones."""
    networks = []
    for entry in entries or []:
        try:
            networks.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError:
            logger.warning("Ignoring invalid allowlist entry: %r", entry)
    return networks


def address_allowed(address: str, networks: list) -> bool:
    """True when *address* is covered by *networks*, or when the list is empty."""
    if not networks:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    # An IPv4 client on a dual-stack socket shows up as ::ffff:a.b.c.d
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in networks)
