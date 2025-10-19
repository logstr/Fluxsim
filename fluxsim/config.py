from dataclasses import dataclass

PROJECT_NAME = "multi-flux-sim"
COMPOSE_FILE = "docker-compose.yml"
FLUX_CONTAINER_BASE_NAME = "proxy_agent"
WORKER_CONTAINER_BASE_NAME = "worker"
DNS_ZONE_FILE_PATH_TEMPLATE = "dns_config/db.{network_name}.zone"
FLUX_IPS_FILE_PATH_TEMPLATE = "dns_config/flux_agents_{network_name}.txt"
MAX_AGENTS = 10
BASE_SUBNET_START = 60

DEFAULTS = {
    "ttl": 60,
    "flux_interval": 5,
    "flux_selector": "random",  # random|roundrobin
    "lb_algo": "round_robin",   # round_robin|ip_hash
}

CLIENT_RESOLV_DEFAULT = {
    "search": "sim.local",
    "ndots": 1,
    "order": None,  # list like ["lbnet","cdnnet","fluxynet"] or None=auto
}

@dataclass
class Net:
    name: str
    kind: str                 # normal|flux|lb|cdn
    subnet_octet: int
    size: int = 1
    ttl: int = DEFAULTS["ttl"]
    flux_interval: int = DEFAULTS["flux_interval"]
    flux_selector: str = DEFAULTS["flux_selector"]
    lb_algo: str = DEFAULTS["lb_algo"]

    @property
    def subnet(self) -> str:
        return f"172.{self.subnet_octet}.0.0/24"
