# fluxsim/commands.py
"""Command registration for the FluxSim CLI.

`register` is invoked by :mod:`fluxsim.cli` to populate the interactive shell with
project-specific commands. Each subcommand interacts with shared state stored in
:mod:`fluxsim.state`, orchestrates docker-compose via :mod:`fluxsim.deploy`, and updates the
monitoring registry so Grafana/Prometheus stay in sync.

The command set is grouped into lifecycle management, configuration tuning, and client helpers.
Docstrings are intentionally verbose to help new contributors navigate the API in combination with
the generated Sphinx documentation (:doc:`../cli`).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from riposte.printer import Palette

from .config import COMPOSE_FILE, MAX_AGENTS
from .docker_utils import compose as dcompose
from .state import BASE_SUBNET_OCTET, CLIENT_RESOLV, NETWORKS, Net, write_registry

# Structured help registry: cmd -> metadata. Populated during `register`.
HELP: dict[str, dict[str, object]] = {}


def register(cli) -> dict[str, dict[str, object]]:
    """Attach FluxSim commands to the provided riposte ``cli`` instance."""

    def _get_next_subnet() -> int:
        """Return the next unused 172.x.0.0/24 subnet octet."""
        global BASE_SUBNET_OCTET
        used = {n.subnet for n in NETWORKS.values()}
        while True:
            subnet = f"172.{BASE_SUBNET_OCTET}.0.0/24"
            if subnet not in used:
                return BASE_SUBNET_OCTET
            BASE_SUBNET_OCTET += 1
            if BASE_SUBNET_OCTET > 255:
                raise RuntimeError("Exhausted 172.x.0.0/24 ranges")

    # ---------- pretty printing helpers ----------

    def _hdr(text: str) -> str:
        return Palette.BOLD.format(Palette.CYAN.format(text))

    def _ok(line: str) -> None:
        cli.print(Palette.GREEN.format(f"[+] {line}"))

    def _kv(k: str, v: str) -> str:
        return f"{Palette.GREY.format(k)}{v}"

    def _add(
        name: str,
        desc: str,
        usage: str,
        long_desc: str = "",
        examples: list[str] | None = None,
        group: str = "General",
    ) -> Callable:
        """Decorator factory: attach command + store rich help metadata."""
        HELP[name] = {
            "name": name,
            "desc": desc.strip(),
            "usage": usage.strip(),
            "long": long_desc.strip(),
            "examples": examples or [],
            "group": group,
        }
        return cli.command(name, desc)

    # Import late to avoid cycles
    from .deploy import (  # noqa: I001
        deploy,
        scale_cdn_edges,
        scale_flux_agents,
        scale_lb_workers,
        stop_and_clean,
        update_zone_ttl,
    )

    # ---------- commands ----------
    @_add(
        "deploy",
        desc="Generate docker-compose.yml from current networks and bring everything up.",
        usage="deploy",
        long_desc="""
            Builds the Compose file from your configured networks and starts containers.
            After services start, it finalizes DNS (sets A records, writes flux agent list, or multi-A for CDN).
        """,
        examples=["deploy"],
        group="Lifecycle",
    )
    def cmd_deploy() -> None:
        """Render compose, start services, and show updated network status."""
        """Render compose file, start services, and persist registry metadata."""
        deploy(cli)  # pass cli for pretty prints
        write_registry(NETWORKS)
        cmd_status()

    @_add(
        "stop",
        desc="Tear everything down and remove compose networks.",
        usage="stop",
        long_desc="Stops all services and removes networks created for this project.",
        examples=["stop"],
        group="Lifecycle",
    )
    def cmd_stop() -> None:
        """Tear down the docker-compose stack and update the registry."""
        stop_and_clean(cli)  # pass cli for pretty prints
        write_registry(NETWORKS)
        cli.success("Stopped.")

    @_add(
        "status",
        desc="Show a summary of configured networks and quick test hints.",
        usage="status",
        long_desc="Lists each network, its subnet, DNS IP and a ready-to-run test command.",
        examples=["status"],
        group="Inspect",
    )
    def cmd_status() -> None:
        """Print a human-friendly summary of configured networks."""
        if not NETWORKS:
            cli.print(Palette.YELLOW.format("No networks configured."))
            return

        cli.print(_hdr("\n[STATUS] Configured Networks\n"))
        for name, inst in sorted(NETWORKS.items()):
            dns_ip = f"172.{inst.subnet_octet}.0.53"
            # Header line for the network
            cli.info(_hdr(f"[{inst.kind.upper()}] {name}") + "  " + _kv("Subnet: ", inst.subnet))

            # Detail lines, always prefixed with [+] and in green
            _ok(_kv("DNS IP: ", f"{dns_ip}") + "   " + _kv("Domain: ", f"{name}.sim.local"))

            if inst.kind == "flux":
                _ok(_kv("Agents: ", str(inst.size)))
                _ok(
                    "Test:   docker compose exec dns_client_test "
                    f"dig @{dns_ip} {name}.sim.local +short"
                )

            elif inst.kind == "lb":
                lb_ip = f"172.{inst.subnet_octet}.0.80"
                _ok(_kv("Workers: ", str(inst.size)) + "   " + _kv("Load Balancer IP: ", lb_ip))
                _ok(f"Test:    docker compose exec dns_client_test curl http://{lb_ip}")

            elif inst.kind == "cdn":
                _ok(_kv("Edges: ", str(inst.size)))
                _ok(
                    "Test:    docker compose exec dns_client_test "
                    f"dig @{dns_ip} {name}.sim.local +short"
                )

            else:  # normal
                _ok(
                    "Test:   docker compose exec dns_client_test "
                    f"dig @{dns_ip} {name}.sim.local +short"
                )

            cli.print("")  # blank line between networks

    # --- add network commands ---
    @_add(
        "add_normal_network",
        desc="Create a simple origin-only network.",
        usage="add_normal_network <name>",
    )
    def add_normal_network(name: str) -> None:
        """Register a new origin-only network in state and display status."""
        if name in NETWORKS:
            cli.error("Already exists.")
            return
        octet = _get_next_subnet()
        NETWORKS[name] = Net(
            name=name,
            kind="normal",
            subnet_octet=octet,
            subnet=f"172.{octet}.0.0/24",
        )
        write_registry(NETWORKS)
        cli.success(f"Added normal '{name}' (172.{octet}.0.0/24)")
        cmd_status()

    @_add(
        "add_flux_network",
        desc="Create a fast-flux network (proxy agents rotate via DNS).",
        usage="add_flux_network <name>",
    )
    def add_flux_network(name: str) -> None:
        """Register a new fast-flux network template."""
        if name in NETWORKS:
            cli.error("Already exists.")
            return
        octet = _get_next_subnet()
        NETWORKS[name] = Net(
            name=name,
            kind="flux",
            subnet_octet=octet,
            subnet=f"172.{octet}.0.0/24",
        )
        write_registry(NETWORKS)
        cli.success(f"Added flux '{name}' (172.{octet}.0.0/24)")
        cmd_status()

    @_add(
        "add_lb_network",
        desc="Create a load-balanced network (LB + N workers).",
        usage="add_lb_network <name>",
    )
    def add_lb_network(name: str) -> None:
        """Register a new load-balancer network template."""
        if name in NETWORKS:
            cli.error("Already exists.")
            return
        octet = _get_next_subnet()
        NETWORKS[name] = Net(
            name=name,
            kind="lb",
            subnet_octet=octet,
            subnet=f"172.{octet}.0.0/24",
        )
        write_registry(NETWORKS)
        cli.success(f"Added load balanced '{name}' (172.{octet}.0.0/24)")
        cmd_status()

    @_add(
        "add_cdn_network",
        desc="Create a CDN-like network with multiple edges (multi-A DNS).",
        usage="add_cdn_network <name>",
    )
    def add_cdn_network(name: str):
        if name in NETWORKS:
            cli.error("Already exists.")
            return
        octet = _get_next_subnet()
        NETWORKS[name] = Net(
            name=name,
            kind="cdn",
            subnet_octet=octet,
            subnet=f"172.{octet}.0.0/24",
            size=3,
        )
        write_registry(NETWORKS)
        cli.success(f"Added CDN '{name}' (172.{octet}.0.0/24) with 3 edges")
        cmd_status()

    @_add(
        "remove_network", desc="Delete a network from the catalog.", usage="remove_network <name>"
    )
    def remove_network(name: str) -> None:
        """Remove a network definition from the catalog."""
        if name not in NETWORKS:
            cli.error("Unknown network.")
            return
        kind = NETWORKS[name].kind
        del NETWORKS[name]
        write_registry(NETWORKS)
        cli.success(f"Removed {kind} network '{name}'.")
        cmd_status()

    # --- tuning commands ---
    @_add(
        "set_flux_n",
        desc="Scale number of proxy agents for a flux network.",
        usage="set_flux_n <name> <N>",
        long_desc="Sets the number of nginx proxy agents for the given flux network (1..10).",
        examples=["set_flux_n fluxy 3"],
        group="Tuning",
    )
    def set_flux_n(name: str, n_str: str) -> None:
        """Schedule a flux network to run with ``n`` proxy agents on next deploy."""
        if name not in NETWORKS or NETWORKS[name].kind != "flux":
            cli.error("Not a flux network.")
            return
        try:
            n = int(n_str)
            assert 1 <= n <= MAX_AGENTS
        except Exception:
            cli.error(f"N must be 1..{MAX_AGENTS}")
            return
        NETWORKS[name].size = n
        cli.success(f"Set flux network '{name}' to scale to {n} agents on next deploy.")

    @_add(
        "set_worker_n",
        desc="Scale number of workers behind the load balancer.",
        usage="set_worker_n <name> <N>",
        long_desc="Sets the number of backend workers for an LB network (1..10).",
        examples=["set_worker_n lbn 4"],
        group="Tuning",
    )
    def set_worker_n(name: str, n_str: str) -> None:
        """Schedule a load-balancer network to run with ``n`` workers."""
        if name not in NETWORKS or NETWORKS[name].kind != "lb":
            cli.error("Not a LB network.")
            return
        try:
            n = int(n_str)
            assert 1 <= n <= MAX_AGENTS
        except Exception:
            cli.error(f"N must be 1..{MAX_AGENTS}")
            return
        NETWORKS[name].size = n
        cli.success(f"Set LB network '{name}' to scale to {n} workers on next deploy.")

    @_add(
        "set_cdn_n",
        desc="Scale number of CDN edges (multi-A records).",
        usage="set_cdn_n <name> <N>",
        long_desc="Sets the number of CDN edges for a CDN network (1..10).",
        examples=["set_cdn_n cdn1 5"],
        group="Tuning",
    )
    def set_cdn_n(name: str, n_str: str) -> None:
        """Schedule a CDN network to publish ``n`` edge addresses."""
        if name not in NETWORKS or NETWORKS[name].kind != "cdn":
            cli.error("Not a CDN network.")
            return
        try:
            n = int(n_str)
            assert 1 <= n <= MAX_AGENTS
        except Exception:
            cli.error(f"N must be 1..{MAX_AGENTS}")
            return
        NETWORKS[name].size = n
        cli.success(f"Set CDN '{name}' to {n} edges (next deploy).")

    @_add(
        "set_ttl",
        desc="Set DNS TTL (seconds) for a network.",
        usage="set_ttl <name> <seconds>",
        long_desc="Updates the TTL used when generating the zone file for the network.",
        examples=["set_ttl fluxy 30"],
        group="Tuning",
    )
    def set_ttl(net: str, sec: str) -> None:
        """Update the stored TTL for ``net`` (applied on next deploy)."""
        if net not in NETWORKS:
            cli.error("Unknown net")
            return
        try:
            NETWORKS[net].ttl = max(1, int(sec))
        except Exception:
            cli.error("Bad TTL")
            return
        cli.success(f"{net}: TTL set to {NETWORKS[net].ttl} (next deploy)")

    @_add(
        "set_flux_interval",
        desc="Set how often flux DNS rotates the A record (seconds).",
        usage="set_flux_interval <name> <seconds>",
        long_desc="Only for flux networks. Lower = more frequent target switching.",
        examples=["set_flux_interval fluxy 5"],
        group="Tuning",
    )
    def set_flux_interval(net: str, sec: str) -> None:
        """Update rotation interval for flux DNS updates (seconds)."""
        if net not in NETWORKS or NETWORKS[net].kind != "flux":
            cli.error("Not a flux net")
            return
        try:
            NETWORKS[net].flux_interval = max(1, int(sec))
        except Exception:
            cli.error("Bad interval")
            return
        cli.success(f"{net}: flux interval set to {NETWORKS[net].flux_interval}s")

    @_add(
        "set_flux_selector",
        desc="Choose flux selection strategy: random | roundrobin.",
        usage="set_flux_selector <name> <random|roundrobin>",
        long_desc="Controls how the DNS updater picks the next proxy agent IP.",
        examples=["set_flux_selector fluxy random", "set_flux_selector fluxy roundrobin"],
        group="Tuning",
    )
    def set_flux_selector(net: str, sel: str) -> None:
        """Choose how the flux DNS updater orders proxy agents."""
        if net not in NETWORKS or NETWORKS[net].kind != "flux":
            cli.error("Not a flux net")
            return
        if sel not in ("random", "roundrobin"):
            cli.error("Use random|roundrobin")
            return
        NETWORKS[net].flux_selector = sel
        cli.success(f"{net}: selector set to {sel}")

    @_add(
        "set_lb_algo",
        desc="Set LB algorithm: round_robin | ip_hash.",
        usage="set_lb_algo <name> <round_robin|ip_hash>",
        long_desc="Changes the NGINX upstream algorithm used by the load balancer.",
        examples=["set_lb_algo lbn ip_hash", "set_lb_algo lbn round_robin"],
        group="Tuning",
    )
    def set_lb_algo(net: str, algo: str) -> None:
        """Toggle the NGINX load-balancer algorithm."""
        if net not in NETWORKS or NETWORKS[net].kind != "lb":
            cli.error("Not an LB net")
            return
        if algo not in ("round_robin", "ip_hash"):
            cli.error("Use round_robin|ip_hash")
            return
        NETWORKS[net].lb_algo = algo
        cli.success(f"{net}: LB algo set to {algo}")

    # --- live commands ---
    @_add(
        "flux_set_ttl",
        desc="Update the TTL for a running flux network and reload DNS.",
        usage="flux_set_ttl <name> <seconds>",
        long_desc="Applies immediately: edits the zone file, bumps serial, and reloads the dns_server container.",
        group="Live Ops",
        examples=["flux_set_ttl fluxy 15"],
    )
    def flux_set_ttl(name: str, sec: str):
        if name not in NETWORKS or NETWORKS[name].kind != "flux":
            cli.error("Not a flux network.")
            return
        try:
            ttl = max(1, int(sec))
        except Exception:
            cli.error("Bad TTL")
            return
        NETWORKS[name].ttl = ttl
        if update_zone_ttl(name, ttl, cli):
            write_registry(NETWORKS)

    @_add(
        "flux_add_agent",
        desc="Add one proxy agent to a running flux network.",
        usage="flux_add_agent <name>",
        long_desc="Scales the proxy_agent service up by one and refreshes the flux agents list immediately.",
        group="Live Ops",
        examples=["flux_add_agent fluxy"],
    )
    def flux_add_agent(name: str) -> None:
        """Immediately scale up the proxy agent pool for a flux network."""
        if name not in NETWORKS or NETWORKS[name].kind != "flux":
            cli.error("Not a flux network.")
            return
        current = NETWORKS[name].size
        if current >= MAX_AGENTS:
            cli.error(f"Already at MAX_AGENTS ({MAX_AGENTS}).")
            return
        new_size = current + 1
        if scale_flux_agents(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: agents scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "flux_remove_agent",
        desc="Remove one proxy agent from a running flux network.",
        usage="flux_remove_agent <name>",
        long_desc="Scales the proxy_agent service down by one (minimum 1) and refreshes DNS metadata.",
        group="Live Ops",
        examples=["flux_remove_agent fluxy"],
    )
    def flux_remove_agent(name: str) -> None:
        """Scale down the proxy agent pool for a flux network."""
        if name not in NETWORKS or NETWORKS[name].kind != "flux":
            cli.error("Not a flux network.")
            return
        current = NETWORKS[name].size
        if current <= 1:
            cli.error("Cannot go below 1 agent.")
            return
        new_size = current - 1
        if scale_flux_agents(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: agents scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "lb_add_worker",
        desc="Add one backend worker to a running load balancer network.",
        usage="lb_add_worker <name>",
        long_desc="Scales worker_<name> up by one container.",
        group="Live Ops",
        examples=["lb_add_worker lbn"],
    )
    def lb_add_worker(name: str) -> None:
        """Scale up the worker pool backing a load balancer."""
        if name not in NETWORKS or NETWORKS[name].kind != "lb":
            cli.error("Not a load balancer network.")
            return
        current = NETWORKS[name].size
        if current >= MAX_AGENTS:
            cli.error(f"Already at MAX_AGENTS ({MAX_AGENTS}).")
            return
        new_size = current + 1
        if scale_lb_workers(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: workers scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "lb_remove_worker",
        desc="Remove one backend worker from a running load balancer network.",
        usage="lb_remove_worker <name>",
        long_desc="Scales worker_<name> down by one container (minimum 1).",
        group="Live Ops",
        examples=["lb_remove_worker lbn"],
    )
    def lb_remove_worker(name: str) -> None:
        """Scale down the worker pool backing a load balancer."""
        if name not in NETWORKS or NETWORKS[name].kind != "lb":
            cli.error("Not a load balancer network.")
            return
        current = NETWORKS[name].size
        if current <= 1:
            cli.error("Cannot go below 1 worker.")
            return
        new_size = current - 1
        if scale_lb_workers(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: workers scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "cdn_add_edge",
        desc="Add one CDN edge node and update DNS immediately.",
        usage="cdn_add_edge <name>",
        long_desc="Scales cdn_edge_<name> up by one container and refreshes multi-A records.",
        group="Live Ops",
        examples=["cdn_add_edge cdn1"],
    )
    def cdn_add_edge(name: str) -> None:
        """Add one CDN edge container and refresh DNS."""
        if name not in NETWORKS or NETWORKS[name].kind != "cdn":
            cli.error("Not a CDN network.")
            return
        current = NETWORKS[name].size
        if current >= MAX_AGENTS:
            cli.error(f"Already at MAX_AGENTS ({MAX_AGENTS}).")
            return
        new_size = current + 1
        if scale_cdn_edges(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: edges scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "cdn_remove_edge",
        desc="Remove one CDN edge node and update DNS.",
        usage="cdn_remove_edge <name>",
        long_desc="Scales cdn_edge_<name> down by one container (minimum 1) and refreshes DNS records.",
        group="Live Ops",
        examples=["cdn_remove_edge cdn1"],
    )
    def cdn_remove_edge(name: str) -> None:
        """Remove one CDN edge container and refresh DNS."""
        if name not in NETWORKS or NETWORKS[name].kind != "cdn":
            cli.error("Not a CDN network.")
            return
        current = NETWORKS[name].size
        if current <= 1:
            cli.error("Cannot go below 1 edge.")
            return
        new_size = current - 1
        if scale_cdn_edges(name, new_size, cli):
            NETWORKS[name].size = new_size
            cli.success(f"{name}: edges scaled to {new_size}")
            write_registry(NETWORKS)

    @_add(
        "dns_client_order",
        desc="Order or auto-select DNS resolvers for the test client.",
        usage="dns_client_order <net1,net2,...|auto>",
        long_desc="""
Controls /etc/resolv.conf in the dns_client_test container. Use 'auto' to sort
by IP, or provide an explicit comma-separated order of network names.
        """,
        examples=["dns_client_order auto", "dns_client_order lbnet,cdn1,fluxy"],
        group="Client",
    )
    def dns_client_order(order: str):
        if order == "auto":
            CLIENT_RESOLV["order"] = None
            cli.success("dns_client: order=auto")
            return
        names = [n.strip() for n in order.split(",") if n.strip()]
        missing = [n for n in names if n not in NETWORKS]
        if missing:
            cli.error("Unknown nets: " + ", ".join(missing))
            return
        CLIENT_RESOLV["order"] = names
        cli.success("dns_client: order=" + ",".join(names))

    @_add(
        "dns_client_set",
        desc="Set search domain or ndots for the test client.",
        usage="dns_client_set <search|ndots> <value>",
        long_desc="Tweaks how names resolve inside the dns_client_test container.",
        examples=["dns_client_set search sim.local", "dns_client_set ndots 1"],
        group="Client",
    )
    def dns_client_set(key: str, val: str):
        if key == "search":
            CLIENT_RESOLV["search"] = val
        elif key == "ndots":
            try:
                CLIENT_RESOLV["ndots"] = max(0, int(val))
            except Exception:
                cli.error("Bad ndots")
                return
        else:
            cli.error("Use search|ndots")
            return
        cli.success(f"dns_client: {key}={val}")

    @_add(
        "client_browse",
        desc="Render a page from dns_client_test using lynx -dump.",
        usage="client_browse <url>",
        long_desc="Runs lynx inside the dns_client_test container so you can see HTML responses with the client resolver settings.",
        examples=["client_browse fluxy.sim.local", "client_browse http://172.60.0.80"],
        group="Client",
    )
    def client_browse(*parts: str) -> None:
        """Fetch a URL inside dns_client_test and print the rendered output."""
        if not parts:
            cli.error("Usage: client_browse <url>")
            return
        raw = " ".join(parts).strip()
        target = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
        res = dcompose(
            ["exec", "-T", "dns_client_test", "lynx", "-dump", target],
            COMPOSE_FILE,
            check=False,
        )
        if not res:
            cli.error("docker compose exec failed.")
            return
        if not isinstance(res, subprocess.CompletedProcess):
            cli.error("Unexpected docker compose response.")
            return
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            cli.error(err or "lynx reported an error.")
            return
        output = (res.stdout or "").strip()
        cli.print(output or "(no content)")

    @_add(
        "desktop_start",
        desc="Build and launch the optional GUI desktop client (noVNC).",
        usage="desktop_start",
        long_desc="Starts dns_client_desktop via docker compose with the 'desktop' profile. Accessible at http://localhost:8081 (default credentials abc/abc).",
        group="Client",
        examples=["desktop_start"],
    )
    def desktop_start():
        res = dcompose(
            ["--profile", "desktop", "up", "-d", "--build", "dns_client_desktop"],
            COMPOSE_FILE,
            check=False,
        )
        if not res:
            cli.error("desktop start failed (compose invocation failed).")
            return
        if not isinstance(res, subprocess.CompletedProcess):
            cli.error("Unexpected docker compose response.")
            return
        if res.returncode != 0:
            err = (res.stderr or "").strip()
            cli.error(err or "desktop start failed")
            return
        cli.success("Desktop client is up on http://localhost:8081 (abc/abc).")

    @_add(
        "desktop_stop",
        desc="Stop and remove the GUI desktop client container.",
        usage="desktop_stop",
        long_desc="Stops dns_client_desktop and removes the container so it stays off until you start it again.",
        group="Client",
        examples=["desktop_stop"],
    )
    def desktop_stop():
        stop = dcompose(
            ["--profile", "desktop", "stop", "dns_client_desktop"], COMPOSE_FILE, check=False
        )
        if stop and isinstance(stop, subprocess.CompletedProcess) and stop.returncode not in (0, 1):
            cli.error((stop.stderr or "desktop stop failed").strip())
            return
        rm = dcompose(
            ["--profile", "desktop", "rm", "-f", "dns_client_desktop"], COMPOSE_FILE, check=False
        )
        if not rm:
            cli.error("desktop remove failed")
            return
        if not isinstance(rm, subprocess.CompletedProcess):
            cli.error("Unexpected docker compose response.")
            return
        if rm.returncode != 0:
            cli.error((rm.stderr or "desktop remove failed").strip())
            return
        cli.success("Desktop client stopped and removed.")

    return HELP
