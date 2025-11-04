Project Overview
================

FluxSim gives defenders, educators, and researchers a reproducible sandbox for exploring evasive DNS
techniques like fast-flux, resilient load balancers, and CDN-style edge networks. Instead of wiring
isolated containers by hand, FluxSim’s CLI assembles full topologies with observability, data
ingestion, and client tooling packaged out of the box.

Key Goals
---------

* **Teach and demo** advanced DNS behaviours without touching production systems.
* **Prototype detections** with streaming telemetry from active (probe) and passive (log) agents.
* **Benchmark mitigations** by scaling edges, rotating proxies, and tuning TTLs in seconds.

Architecture at a Glance
------------------------

.. code-block:: text

   +-------------------------------------------------------------------+
   |                            Host Machine                           |
   |                                                                   |
   |   +----------------------+         +---------------------------+  |
   |   |  FluxSim CLI (riposte)        |  docker-compose stack     |  |
   |   +-----------+----------+         +------------+--------------+  |
   |               |                                 |                 |
   |               v                                 v                 |
   |      docker-compose.yml        +-------------------------------+  |
   |                                | Runtime services              |  |
   |                                | - dns_server_<net> (BIND)     |  |
   |                                | - origin/proxy/cdn/lb agents  |  |
   |                                | - fluxlab_exporter, Grafana   |  |
   |                                | - Redpanda, Postgres, ingestor|  |
   |                                | - dns_client_{test,desktop}   |  |
   |                                +-------------------------------+  |
   +-------------------------------------------------------------------+

Each network topology you add receives:

* An isolated subnet within ``172.60.0.0/24`` onward.
* A dedicated BIND authoritative server whose zone is regenerated whenever you deploy.
* Optional proxy agents (fast-flux), NGINX worker pools (load balancer), or CDN edges.

Observability
-------------

* **Active probe** container continually resolves simulated hostnames, sending TTL answers to the
  ``ff.probes`` topic.
* **Passive agent** tails BIND logs and streams query metadata to ``ff.signals``.
* **Kafka/Redpanda → Ingestor → Postgres** forms the data pipeline for long-term analysis.
* **FluxLab Exporter** aggregates runtime state for Prometheus; Grafana dashboards and ASCII TUI
  provide operator views.

What’s Included
---------------

* CLI commands for managing networks, scaling agents, and refreshing DNS.
* Dockerfiles and configs for BIND, NGINX roles, Redpanda, Postgres, exporters, and clients.
* Example dashboards, notebook demos, and integration tests.
* A pytest suite covering core utilities (DNS zone management, Docker orchestration helpers).
