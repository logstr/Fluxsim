from dataclasses import dataclass

PROJECT_NAME = "multi-flux-sim"
COMPOSE_FILE = "docker-compose.yml"
FLUX_CONTAINER_BASE_NAME = "proxy_agent"
WORKER_CONTAINER_BASE_NAME = "worker"
DNS_ZONE_FILE_PATH_TEMPLATE = "dns_config/db.{network_name}.zone"
FLUX_IPS_FILE_PATH_TEMPLATE = "dns_config/flux_agents_{network_name}.txt"
MAX_AGENTS = 10
BASE_SUBNET_START = 60

DEFAULT_TTL = 60
DEFAULT_FLUX_INTERVAL = 5
DEFAULT_FLUX_SELECTOR = "random"  # random|roundrobin
DEFAULT_LB_ALGO = "round_robin"  # round_robin|ip_hash

DEFAULTS = {
    "ttl": DEFAULT_TTL,
    "flux_interval": DEFAULT_FLUX_INTERVAL,
    "flux_selector": DEFAULT_FLUX_SELECTOR,
    "lb_algo": DEFAULT_LB_ALGO,
}

CLIENT_RESOLV_DEFAULT = {
    "search": "sim.local",
    "ndots": 1,
    "order": None,  # list like ["lbnet","cdnnet","fluxynet"] or None=auto
}


@dataclass
class Net:
    name: str
    kind: str  # normal|flux|lb|cdn
    subnet_octet: int
    size: int = 1
    ttl: int = DEFAULT_TTL
    flux_interval: int = DEFAULT_FLUX_INTERVAL
    flux_selector: str = DEFAULT_FLUX_SELECTOR
    lb_algo: str = DEFAULT_LB_ALGO

    @property
    def subnet(self) -> str:
        return f"172.{self.subnet_octet}.0.0/24"
