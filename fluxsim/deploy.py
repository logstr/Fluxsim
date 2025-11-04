"""Deployment orchestration for FluxSim."""

import os
import subprocess
import time
from typing import Any

from riposte.printer import Palette

from .compose_gen import generate
from .config import (
    COMPOSE_FILE,
    DNS_ZONE_FILE_PATH_TEMPLATE,
    FLUX_CONTAINER_BASE_NAME,
    PROJECT_NAME,
    WORKER_CONTAINER_BASE_NAME,
)
from .dns_utils import (
    set_multi_a_records,
    set_single_a_record,
    set_zone_ttl,
    write_flux_agents,
)
from .docker_utils import compose as dcompose, service_container_ids
from .state import NETWORKS, clear_state


def _project_net(name: str) -> str:
    """Return the canonical docker network name for ``name`` within this project."""

    return f"{PROJECT_NAME}_{name}_net"


def _write_client_resolv(cli: Any | None = None) -> str:
    """
    Generate dns_config/resolv.dns_client.conf from *running* dns_server_* containers if any,
    otherwise fall back to 172.<octet>.0.53 computed from NETWORKS.

    Returns the absolute path written.
    """
    import json

    os.makedirs("dns_config", exist_ok=True)
    path = os.path.join("dns_config", "resolv.dns_client.conf")

    # Try to read running dns_server_* container IPs (from a previous deploy, etc.)
    ns_ips: list[str] = []
    try:
        # docker compose ps --format json prints an array in recent versions; handle string/empty too
        out = subprocess.run(
            ["docker", "compose", "-p", PROJECT_NAME, "-f", COMPOSE_FILE, "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        items = json.loads(out) if out else []
        if isinstance(items, list):
            for svc in items:
                name = svc.get("Service", "") or svc.get("Name", "")
                if isinstance(name, str) and name.startswith("dns_server_"):
                    cid = svc.get("ID") or svc.get("IDName") or ""
                    if not cid:
                        continue
                    # Inspect IP across all networks; prefer our project network match
                    insp = subprocess.run(
                        ["docker", "inspect", cid], capture_output=True, text=True, check=False
                    ).stdout
                    if insp:
                        try:
                            arr = json.loads(insp)
                            nets = arr[0]["NetworkSettings"]["Networks"] or {}
                            for _net_name, meta in nets.items():
                                # pick first IPv4
                                ip = (meta.get("IPAddress") or "").strip()
                                if ip and ip.count(".") == 3:
                                    ns_ips.append(ip)
                        except Exception:
                            pass
    except Exception:
        pass

    # Fallback to deterministic IPs by subnet octet (works even on first deploy)
    if not ns_ips:
        for _, inst in NETWORKS.items():
            ns_ips.append(f"172.{inst.subnet_octet}.0.53")

    # Deduplicate & stable order
    ns_ips = sorted({ip for ip in ns_ips if ip.startswith("172.")})

    lines = ["search sim.local", "options ndots:1"] + [f"nameserver {ip}" for ip in ns_ips]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

    if cli:
        if ns_ips:
            _ok(
                cli,
                f"Wrote resolv for client with {len(ns_ips)} nameserver(s): {', '.join(ns_ips)}",
            )
        else:
            _warn(cli, "Wrote resolv for client with no nameservers (check networks)")

    return os.path.abspath(path)


def _service_ips(service_name: str, network_name: str) -> list[str]:
    """Inspect docker for the IPv4 addresses bound to ``service_name`` on ``network_name``."""

    ids = service_container_ids(service_name, COMPOSE_FILE)
    docker_net = _project_net(network_name)
    ips: list[str] = []
    for cid in ids:
        try:
            out = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    f'{{{{ (index .NetworkSettings.Networks "{docker_net}").IPAddress }}}}',
                    cid,
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if out and out.count(".") == 3:
                ips.append(out)
        except subprocess.CalledProcessError:
            pass
    return sorted(set(ips))


def _compose_validate(cli: Any | None, compose_file: str) -> bool:
    """Run ``docker compose config`` and pretty-print the first error if any."""
    proc = subprocess.run(
        ["docker", "compose", "-f", compose_file, "config"], capture_output=True, text=True
    )
    if proc.returncode == 0:
        return True
    if cli:
        cli.error("docker compose config failed:")
        if proc.stderr.strip():
            cli.print(Palette.RED.format(proc.stderr.strip()))
        else:
            cli.print(Palette.RED.format(proc.stdout.strip()))
    else:
        print(proc.stderr or proc.stdout)
    return False


def _wait_ips(service: str, net: str, expect_at_least=1, timeout=60, poll=2) -> list[str]:
    """Poll service IPs until the expected count is reached or timeout elapses."""

    deadline = time.time() + timeout
    last: list[str] = []
    while time.time() < deadline:
        ips = _service_ips(service, net)
        if len(ips) >= expect_at_least:
            return ips
        last = ips
        time.sleep(poll)
    return last


def _reload_dns_service(name: str, cli: Any | None = None) -> bool:
    """
    Ask the dns_server_<name> container to reload its zone.
    Falls back to sending HUP to named if rndc is unavailable.
    """
    cmd = [
        "exec",
        "-T",
        f"dns_server_{name}",
        "sh",
        "-lc",
        "rndc reload sim.local || pkill -HUP named",
    ]
    res = dcompose(cmd, COMPOSE_FILE, check=False)
    ok = bool(res and getattr(res, "returncode", 1) == 0)
    if cli:
        if ok:
            _ok(cli, f"{name}: dns reload requested")
        else:
            _warn(cli, f"{name}: dns reload command failed")
    return ok


def refresh_flux_agents(name: str, cli: Any | None = None) -> list[str]:
    """
    Capture current proxy agent IPs for a flux network and rewrite the agents file.
    Returns the list of IPs discovered.
    """
    ips = _service_ips(f"{FLUX_CONTAINER_BASE_NAME}_{name}", name)
    path = write_flux_agents(name, ips)
    if cli:
        if ips:
            _ok(cli, f"{name}: refresh wrote {len(ips)} agent IP(s) to {path}")
        else:
            _warn(cli, f"{name}: no proxy agents discovered when refreshing")
    return ips


def update_zone_ttl(name: str, ttl: int, cli: Any | None = None) -> bool:
    """
    Update the zone TTL on disk and request a reload from the dns container.
    """
    zone_path = DNS_ZONE_FILE_PATH_TEMPLATE.format(network_name=name)
    if not os.path.exists(zone_path):
        if cli:
            _warn(cli, f"{name}: zone file missing ({zone_path})")
        return False
    set_zone_ttl(zone_path, ttl)
    if cli:
        _ok(cli, f"{name}: zone TTL set to {ttl}")
    return _reload_dns_service(name, cli)


def scale_flux_agents(name: str, size: int, cli: Any | None = None) -> bool:
    """Scale the running ``proxy_agent_<name>`` service and refresh DNS state."""
    if size < 1:
        if cli:
            _warn(cli, f"{name}: size must be >= 1")
        return False
    cmd = [
        "up",
        "-d",
        "--scale",
        f"{FLUX_CONTAINER_BASE_NAME}_{name}={size}",
        f"{FLUX_CONTAINER_BASE_NAME}_{name}",
    ]
    res = dcompose(cmd, COMPOSE_FILE, check=False)
    if not res or getattr(res, "returncode", 1) != 0:
        if cli:
            _err(cli, f"{name}: scaling command failed")
        return False

    ips = refresh_flux_agents(name, cli)
    if ips:
        _reload_dns_service(name, cli)
    return True


def scale_lb_workers(name: str, size: int, cli: Any | None = None) -> bool:
    """Scale the ``worker_<name>`` service backing the load balancer."""
    if size < 1:
        if cli:
            _warn(cli, f"{name}: size must be >= 1")
        return False
    cmd = [
        "up",
        "-d",
        "--scale",
        f"{WORKER_CONTAINER_BASE_NAME}_{name}={size}",
        f"{WORKER_CONTAINER_BASE_NAME}_{name}",
    ]
    res = dcompose(cmd, COMPOSE_FILE, check=False)
    if not res or getattr(res, "returncode", 1) != 0:
        if cli:
            _err(cli, f"{name}: scaling workers failed")
        return False
    if cli:
        _ok(cli, f"{name}: worker pool scaled to {size}")
    return True


def scale_cdn_edges(name: str, size: int, cli: Any | None = None) -> bool:
    """Scale the ``cdn_edge_<name>`` service and rewrite multi-A DNS records."""
    if size < 1:
        if cli:
            _warn(cli, f"{name}: size must be >= 1")
        return False
    cmd = [
        "up",
        "-d",
        "--scale",
        f"cdn_edge_{name}={size}",
        f"cdn_edge_{name}",
    ]
    res = dcompose(cmd, COMPOSE_FILE, check=False)
    if not res or getattr(res, "returncode", 1) != 0:
        if cli:
            _err(cli, f"{name}: scaling CDN edges failed")
        return False

    ips = _wait_ips(f"cdn_edge_{name}", name, expect_at_least=size, timeout=90)
    zone_path = DNS_ZONE_FILE_PATH_TEMPLATE.format(network_name=name)
    if ips:
        set_multi_a_records(zone_path, name, ips)
        _ok(cli, f"{name}: updated multi-A with {len(ips)} edge IP(s)")
        _reload_dns_service(name, cli)
    else:
        _warn(cli, f"{name}: no CDN edge IPs discovered after scaling")
    return True


# -------- pretty printing helpers --------
def _hdr(cli, text: str):
    if cli:
        cli.print(Palette.BOLD.format(Palette.CYAN.format(text)))
    else:
        print(text)


def _ok(cli, line: str):
    if cli:
        cli.success(line)  # green [+] prefix built-in
    else:
        print("[+] " + line)


def _warn(cli, line: str):
    if cli:
        cli.print(Palette.YELLOW.format(line))
    else:
        print(line)


def _err(cli, line: str):
    if cli:
        cli.error(line)
    else:
        print("[-] " + line)


def deploy(cli: Any | None = None) -> None:
    if len(NETWORKS) == 0:
        if cli:
            cli.print(Palette.YELLOW.format("WARNING: No networks registered."))
        else:
            print("WARNING: No networks registered.")
        return

    # Generate compose file
    with open(COMPOSE_FILE, "w") as f:
        f.write(generate(COMPOSE_FILE))
    if cli:
        cli.success(f"Wrote {COMPOSE_FILE}")

    if not _compose_validate(cli, COMPOSE_FILE):
        return

    # 🔧 Ensure the client resolv file exists BEFORE 'up' (bind-mount target)
    _write_client_resolv(cli)

    _hdr(cli, "\n[Deploying]")
    dcompose(["down", "-v", "--remove-orphans"], COMPOSE_FILE, check=False)
    time.sleep(1.0)

    scale_args: list[str] = []
    for name, inst in NETWORKS.items():
        if inst.kind == "flux" and inst.size > 1:
            scale_args += ["--scale", f"{FLUX_CONTAINER_BASE_NAME}_{name}={inst.size}"]
        elif inst.kind == "lb" and inst.size > 1:
            scale_args += ["--scale", f"{WORKER_CONTAINER_BASE_NAME}_{name}={inst.size}"]
        elif inst.kind == "cdn" and inst.size > 1:
            scale_args += ["--scale", f"cdn_edge_{name}={inst.size}"]

    if dcompose(["up", "-d", "--build"] + scale_args, COMPOSE_FILE) is None:
        _err(cli, "Compose up failed.")
        return

    # (Optional) refresh resolv now that DNS containers are up—no restart needed for client,
    #   the file is bind-mounted so new contents are visible instantly.
    _write_client_resolv(cli)

    _hdr(cli, "\n[Finalizing DNS]")
    for name, inst in NETWORKS.items():
        zone_path = DNS_ZONE_FILE_PATH_TEMPLATE.format(network_name=name)
        if inst.kind == "normal":
            origin = f"origin_server_{name}"
            ips = _wait_ips(origin, name, expect_at_least=1)
            if ips:
                set_single_a_record(zone_path, name, ips[0])
                _ok(cli, f"{name}: set A -> {ips[0]}")
            else:
                _warn(cli, f"{name}: origin had no IPs yet")
        elif inst.kind == "flux":
            proxy = f"{FLUX_CONTAINER_BASE_NAME}_{name}"
            ips = _wait_ips(proxy, name, expect_at_least=1)
            # This writes dns_config/flux_agents_<name>.txt (hardened below)
            path = write_flux_agents(name, ips)
            _ok(cli, f"{name}: wrote {len(ips)} agent IP(s) to {path}")
        elif inst.kind == "lb":
            lb = f"load_balancer_{name}"
            ips = _wait_ips(lb, name, expect_at_least=1)
            if ips:
                set_single_a_record(zone_path, name, ips[0])
                _ok(cli, f"{name}: set A -> {ips[0]}")
            else:
                _warn(cli, f"{name}: LB had no IPs yet")
        elif inst.kind == "cdn":
            edge = f"cdn_edge_{name}"
            ips = _wait_ips(edge, name, expect_at_least=max(1, inst.size), timeout=90)
            if ips:
                set_multi_a_records(zone_path, name, ips)
                _ok(cli, f"{name}: published {len(ips)} CDN edge A-records")
            else:
                _warn(cli, f"{name}: no CDN edge IPs yet")

    _ok(cli, "\nDeployment complete.")


def stop_and_clean(cli: Any | None = None) -> None:
    _hdr(cli, "\n[Stopping]")
    dcompose(["down", "-v", "--remove-orphans"], COMPOSE_FILE, check=False)
    clear_state()
    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        leftovers = [n for n in out.splitlines() if n.startswith(f"{PROJECT_NAME}_")]
        if leftovers:
            subprocess.run(
                ["docker", "network", "rm"] + leftovers, capture_output=True, text=True, check=False
            )
            _ok(cli, f"Removed networks: {', '.join(leftovers)}")
    except Exception as e:
        _warn(cli, f"While removing networks: {e}")
