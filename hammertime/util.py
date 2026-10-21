"""Small helpers ported from ``util.js``."""

import ipaddress
import socket
from typing import Optional

import psutil


def get_host_ip() -> Optional[str]:
    """First non-internal IPv4 address, like ``os.networkInterfaces()`` in util.js.

    Node skips ``internal`` (loopback) entries; psutil has no such flag, so loopback
    addresses are filtered explicitly. Returns ``None`` when only loopback exists.
    """
    for _name, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            if address.family != socket.AF_INET:
                continue
            try:
                if ipaddress.ip_address(address.address).is_loopback:
                    continue
            except ValueError:  # pragma: no cover - malformed address from the OS
                continue
            return address.address
    return None
