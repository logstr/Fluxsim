from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

from .config import BASE_SUBNET_START, CLIENT_RESOLV_DEFAULT

NETWORKS: dict[str, Net] = {}
BASE_SUBNET_OCTET = BASE_SUBNET_START
CLIENT_RESOLV = dict(CLIENT_RESOLV_DEFAULT)
REGISTRY_PATH = "monitoring/registry.json"


@dataclass
class Net:
    name: str
    kind: str  # "normal" | "flux" | "lb" | "cdn"
    subnet_octet: int
    subnet: str
    size: int = 1
    ttl: int = 60
    flux_interval: int = 5
    flux_selector: str = "random"
    lb_algo: str = "round_robin"


def reset():
    global NETWORKS, BASE_SUBNET_OCTET, CLIENT_RESOLV
    NETWORKS.clear()
    BASE_SUBNET_OCTET = BASE_SUBNET_START
    CLIENT_RESOLV = dict(CLIENT_RESOLV_DEFAULT)


def _ensure_monitoring_dir():
    os.makedirs("monitoring", exist_ok=True)


def write_registry(networks: dict[str, Net]):
    """
    Persist a minimal, monitoring-friendly snapshot.
    Called after any network add/remove/modify/deploy/stop.
    """
    _ensure_monitoring_dir()
    payload = {
        "updated_at": int(time.time()),
        "networks": {
            name: {
                "name": name,
                "kind": net.kind,
                "subnet_octet": net.subnet_octet,
                "subnet": net.subnet,
                "size": net.size,
                "ttl": net.ttl,
                "flux_interval": net.flux_interval,
                "flux_selector": net.flux_selector,
                "fqdn": f"{name}.sim.local",
                "dns_ip": f"172.{net.subnet_octet}.0.53",
            }
            for name, net in networks.items()
        },
    }
    with open(REGISTRY_PATH, "w") as f:
        json.dump(payload, f, indent=2)


def clear_state():
    """Reset shared state WITHOUT rebinding the dict object."""
    global BASE_SUBNET_OCTET
    NETWORKS.clear()  # <-- mutate in place
    BASE_SUBNET_OCTET = 60
