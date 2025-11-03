# FluxSim

[![CI](https://github.com/logstr/Fluxsim/actions/workflows/ci.yml/badge.svg)](https://github.com/logstr/Fluxsim/actions/workflows/ci.yml)
[![Coverage Status](https://codecov.io/gh/logstr/Fluxsim/branch/main/graph/badge.svg)](https://codecov.io/gh/logstr/Fluxsim)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Financial Contributors](https://opencollective.com/logstrio/tiers/badge.svg)](https://opencollective.com/logstrio)

Spin up DNS fast-flux, load-balancer, and CDN-like playgrounds in Docker with a friendly CLI.
FluxSim was designed for experimentation and teaching—create networks on the fly, scale them
live, and observe how DNS, HTTP, and monitoring react.

<!-- Embedded demo SVG from examples/demo.svg -->
![Demo SVG](examples/demo.svg)

## Table of Contents

1. [Quickstart](#quickstart)
2. [Architecture Overview](#architecture-overview)
3. [Network Topologies](#network-topologies)
4. [Runtime Services](#runtime-services)
5. [CLI Workflow](#cli-workflow)
6. [Client Access](#client-access)
7. [Data & Monitoring Pipeline](#data--monitoring-pipeline)
8. [Host DNS Access](#host-dns-access)
9. [Quality & Coverage](#quality--coverage)
10. [Contributing & Tooling](#contributing--tooling)
11. [Community & Governance](#community--governance)
12. [Sponsors & Backers](#sponsors--backers)
13. [License](#license)

## Quickstart

```bash
pip install -e .[dev]  # install FluxSim + dev toolchain
pre-commit install

fluxsim
# inside the REPL
add_flux_network fluxy
set_flux_n fluxy 3
set_flux_interval fluxy 5
deploy
status
desktop_start    # optional: launch GUI desktop (noVNC)
```

Copy your own configs (`Dockerfile.client`, `Dockerfile.dns`, `nginx_configs/*`,
`scripts/dns_updater.sh`, `dns_config/named.conf.*`) into this repo to customise the labs.

## Architecture Overview

```mermaid
graph TD
    host((Host Machine))
    cli[FluxSim CLI]
    compose[docker-compose.yml]
    stack[[Docker Compose Stack]]
    dns[(dns_server_* BIND)]
    origin[origin_server_*]
    proxy[proxy_agent_*]
    lb[(load_balancer_* & worker_*)]
    cdn[(cdn_edge_*)]
    client1[dns_client_test]
    client2[dns_client_desktop]
    monitoring[(prometheus/grafana/exporter)]
    data[(postgres + kafka/redpanda + ingestor)]

    host --> cli --> compose --> stack
    stack --> dns
    stack --> origin
    stack --> proxy
    stack --> lb
    stack --> cdn
    stack --> client1
    stack --> client2
    stack --> monitoring
    stack --> data

    data --> monitoring
    proxy --> dns
    lb --> origin
    cdn --> origin
```

## Network Topologies

| Kind   | Description | Default components |
|--------|-------------|--------------------|
| `normal` | Plain origin server with one authoritative DNS | `dns_server_*`, `origin_server_*` |
| `flux`   | Fast-flux rotation through nginx proxies | + `proxy_agent_*`, optional scaling, dynamic zone updates |
| `lb`     | Layer-7 load balancer with worker pool | + `load_balancer_*`, `worker_*` |
| `cdn`    | CDN-style multi-edge deployment | + `cdn_edge_*` (scalable), origin |

FluxSim allocates subnets automatically (beginning at `172.60.0.0/24`) so networks can coexist.

## Runtime Services

```mermaid
flowchart LR
    dns_server[dns_server_*] --> zone(BIND zones)
    proxy_agent[proxy_agent_*] --> dns_server
    flux_cron[scripts/dns_updater.sh] --> dns_server
    active[active-probe] -->|ff.probes| kafka[(Redpanda)]
    passive[passive-agent] -->|ff.signals| kafka
    kafka --> ingestor[kafka_ingestor]
    ingestor --> postgres[(Postgres)]
    exporter[fluxlab_exporter] --> prometheus[(Prometheus)]
    prometheus --> grafana[(Grafana)]
    exporter <---> dns_server
    exporter <---> clients[dns_client_*]
    clients -->|HTTP/DNS| dns_server
```

## CLI Workflow

- **Network management**: `add_*_network`, `remove_network`, `status`
- **Tuning**: `set_flux_n`, `set_worker_n`, `set_cdn_n`, `set_ttl`, `set_flux_interval`,
  `set_flux_selector`, `set_lb_algo`
- **Live ops**: `deploy`, `stop`, `flux_add_agent`, `flux_remove_agent`, `lb_add_worker`,
  `lb_remove_worker`, `cdn_add_edge`, `cdn_remove_edge`, `flux_set_ttl`
- **Client helpers**: `client_browse`, `desktop_start`, `desktop_stop`

All commands mutate a shared registry (`monitoring/registry.json`) so the exporter and dashboards
stay in sync.

## Client Access

- **Text / notebooks** (`dns_client_test`)
  - Jupyter Lab at http://localhost:8888 (no token, root dir `/workspace`)
  - `client_browse <hostname>` uses `lynx -dump` inside the container.
- **GUI desktop** (`dns_client_desktop`)
  - Opt-in via `desktop_start`, available at http://localhost:8081 (noVNC, user `abc`, password
    `abc`). Stop it with `desktop_stop` when idle.

Both clients share the generated `resolv.conf`, so queries run with the same resolver order you set
in the CLI (`dns_client_order`, `dns_client_set`).

## Data & Monitoring Pipeline

Set Postgres credentials (e.g., in `.env`) before deploying:

```
PGUSER=fluxlab
PGPASSWORD=fluxlab
PGDATABASE=fluxlab
```

- **Agents**: `active-probe` emits DNS answers/TTL observations; `passive-agent` tails bind query
  logs.
- **Transport**: Redpanda (Kafka-compatible) topics `ff.probes` and `ff.signals`.
- **Storage**: `kafka_ingestor` writes events into Postgres tables `probe_events` and
  `signal_events`.
- **Monitoring**: `fluxlab_exporter` exposes scrape metrics combining runtime health and ingested
  events. Prometheus/Grafana (default credentials `admin` / `fluxlab`) run on http://localhost:9090
  and http://localhost:3000.
- **Adminer**: browse database contents at http://localhost:8080.

## Host DNS Access

Every BIND server now publishes to the host. FluxSim assigns deterministic ports starting at 5300
(`dns_server_*` sorted alphabetically). Both TCP and UDP are mapped:

```bash
dig @127.0.0.1 -p 5300 fluxy.sim.local
dig @127.0.0.1 -p 5301 cdn1.sim.local
```

This makes it easy to test lookups from the host or external tools without entering the stack.

## Quality & Coverage

- **Lint & type-check**: `ruff check .`, `ruff format --check .`, `black --check .`, and `mypy fluxsim`
  (mirrors the CI workflow).
- **Unit tests with coverage**:

  ```bash
  pytest --cov=fluxsim --cov-report=xml --cov-report=term-missing
  ```

  This generates `coverage.xml` for upload to Codecov or another coverage tracker. Add the `CODECOV_TOKEN`
  repository secret (for private repos) before enabling uploads.
- **Badges**: Once Codecov is connected, the coverage badge at the top of this README reflects main-branch runs.

## Contributing & Tooling

We welcome pull requests! See [CONTRIBUTING.md](CONTRIBUTING.md) for workflow expectations,
environment setup, and review tips. A quick-start for local development:

```bash
pip install -e .[dev]
pre-commit install
pre-commit run --all-files
pytest --cov=fluxsim --cov-report=term
```

GitHub Actions (`.github/workflows/ci.yml`) repeats these checks on every push and pull request.

## Community & Governance

- **Roadmap & issues**: Coordinate enhancements through [GitHub Issues](https://github.com/fastfluxlab/multi-flux-sim/issues)
  and Projects/Milestones to make releases predictable.
- **Discussions**: Enable GitHub Discussions or a community chat to share lab results, teaching material,
  and troubleshooting tips.
- **Code of Conduct**: Adopt the [Contributor Covenant v2.1](https://www.contributor-covenant.org/)
  so collaborators understand behaviour expectations. Choose a contact email for incident reports.
- **Security policy**: Add `SECURITY.md` describing responsible disclosure steps for vulnerabilities.

## Sponsors & Backers

FluxSim lowers the barrier to studying fast-flux infrastructure. If this project accelerates your research,
coursework, or threat hunting, please sponsor continued development. Update `.github/FUNDING.yml` with your
GitHub Sponsors handle or other funding platforms; sponsors will be recognised in release notes and community calls.

## License

FluxSim is released under the MIT License. See [`LICENSE`](LICENSE) for details.
