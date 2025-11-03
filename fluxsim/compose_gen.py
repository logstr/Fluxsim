# compose_gen.py
import os
import yaml
from .config import *  # your constants
from .state import NETWORKS, CLIENT_RESOLV
from .dns_utils import write_zone_file

home_dir = os.environ.get("HOME", os.path.expanduser("~"))


def _client_resolv_lines() -> list[str]:
    # Build resolv.conf content for the test client from NETWORKS
    lines = [
        f"search {CLIENT_RESOLV.get('search', 'sim.local')}",
        f"options ndots:{CLIENT_RESOLV.get('ndots', 1)}",
    ]
    if CLIENT_RESOLV.get("order"):
        nets = [n for n in CLIENT_RESOLV["order"] if n in NETWORKS]
        ns_ips = [f"172.{NETWORKS[n].subnet_octet}.0.53" for n in nets]
    else:
        ns_ips = sorted({f"172.{inst.subnet_octet}.0.53" for inst in NETWORKS.values()})
    for ip in ns_ips:
        lines.append(f"nameserver {ip}")
    return lines


def generate(compose_file: str) -> str:
    import os, shutil

    networks_yaml = "networks:\n"
    services_yaml = "services:\n"
    test_client_nets: set[str] = set()
    monitor_nets: set[str] = set()

    # ---- per-network services (DNS + origin/flux/lb/cdn) ----
    for idx, (name, inst) in enumerate(sorted(NETWORKS.items())):
        octet = inst.subnet_octet
        dns_ip = f"172.{octet}.0.53"
        domain = f"{name}.sim.local"
        net = f"{name}_net"
        host_dns_port = 5300 + idx

        networks_yaml += f"""  {net}:
    driver: bridge
    ipam:
      config:
        - subnet: 172.{octet}.0.0/24
"""
        test_client_nets.add(net)
        monitor_nets.add(net)

        # zone file + host log dir/file for BIND
        zone_file = write_zone_file(name, dns_ip, domain, octet, inst.ttl)
        log_dir = os.path.join("bind_logs", name)
        os.makedirs(log_dir, exist_ok=True)
        query_file = os.path.join(log_dir, "query.log")

        # If a directory was mistakenly created at the file path, remove it
        if os.path.isdir(query_file):
            shutil.rmtree(query_file)
        # Ensure it's a regular file (touch)
        if not os.path.exists(query_file):
            open(query_file, "a").close()

        dns_vols = [
            f"- ./dns_config/named.conf:/etc/bind/named.conf:ro",
            f"- ./dns_config/named.conf.options:/etc/bind/named.conf.options:ro",
            f"- ./dns_config/named.conf.local:/etc/bind/named.conf.local:ro",
            f"- ./{zone_file}:/etc/bind/db.sim.local.zone:rw",
            f"- ./{log_dir}:/var/log/named",
        ]

        dns_cmd_yaml = ""
        if inst.kind == "flux":
            agents_file = FLUX_IPS_FILE_PATH_TEMPLATE.format(network_name=name)
            dns_vols += [
                f"- ./scripts/dns_updater.sh:/usr/local/bin/dns_updater.sh:ro",
                f"- ./{agents_file}:/etc/bind/flux_agents.txt:ro",
            ]
            dns_cmd_yaml = '\n    command: ["/usr/local/bin/dns_updater.sh"]'

        env_lines = [
            "- DOMAIN=sim.local",
            f"- RECORD_NAME={name}",
        ]
        if inst.kind == "flux":
            env_lines += [
                f"- FLUX_INTERVAL={int(inst.flux_interval)}",
                f"- FLUX_SELECTOR={inst.flux_selector}",
            ]

        services_yaml += f"""  dns_server_{name}:
    build:
      context: .
      dockerfile: Dockerfile.dns
    cap_add: [ "NET_ADMIN" ]
    networks:
      {net}:
        ipv4_address: {dns_ip}
    ports:
      - "{host_dns_port}:53"
      - "{host_dns_port}:53/udp"
    volumes:
{chr(10).join(["      " + v for v in dns_vols])}{dns_cmd_yaml}
    environment:
{chr(10).join(["      " + e for e in env_lines])}
    restart: always
"""

        if inst.kind == "normal":
            services_yaml += f"""  origin_server_{name}:
    image: nginx:alpine
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/origin.conf:/etc/nginx/conf.d/default.conf:ro
      - ./html:/usr/share/nginx/html:ro
    restart: always
"""
        elif inst.kind == "flux":
            origin_svc = f"origin_server_{name}"
            agent_svc = f"{FLUX_CONTAINER_BASE_NAME}_{name}"
            services_yaml += f"""  {origin_svc}:
    image: nginx:alpine
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/origin.conf:/etc/nginx/conf.d/default.conf:ro
      - ./html:/usr/share/nginx/html:ro
    restart: always
  {agent_svc}:
    image: nginx:alpine
    depends_on: [ "{origin_svc}" ]
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/proxy.conf:/etc/nginx/templates/proxy.conf.template:ro
    environment:
      - ORIGIN_SERVER_NAME={origin_svc}
    command: ["/bin/sh","-c","envsubst '$$ORIGIN_SERVER_NAME' < /etc/nginx/templates/proxy.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
    restart: always
"""
        elif inst.kind == "lb":
            lb_svc = f"load_balancer_{name}"
            worker_svc = f"{WORKER_CONTAINER_BASE_NAME}_{name}"
            lb_ip = f"172.{octet}.0.80"
            ip_hash_line = "ip_hash;" if inst.lb_algo == "ip_hash" else ""
            services_yaml += f"""  {worker_svc}:
    image: nginx:alpine
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/origin.conf:/etc/nginx/conf.d/default.conf:ro
      - ./html:/usr/share/nginx/html:ro
    restart: always
  {lb_svc}:
    image: nginx:alpine
    networks:
      {net}:
        ipv4_address: {lb_ip}
    depends_on: [ "{worker_svc}" ]
    volumes:
      - ./nginx_configs/load_balancer.conf:/etc/nginx/templates/default.conf.template:ro
    environment:
      - WORKER_SERVICE_NAME={worker_svc}
    command: ["/bin/sh","-lc","envsubst '$$WORKER_SERVICE_NAME' < /etc/nginx/templates/default.conf.template | sed 's#__IP_HASH_MARKER__#{ip_hash_line}#' > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
    restart: always
"""
        elif inst.kind == "cdn":
            origin_svc = f"origin_server_{name}"
            edge_svc = f"cdn_edge_{name}"
            services_yaml += f"""  {origin_svc}:
    image: nginx:alpine
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/origin.conf:/etc/nginx/conf.d/default.conf:ro
      - ./html:/usr/share/nginx/html:ro
    restart: always
  {edge_svc}:
    image: nginx:alpine
    depends_on: [ "{origin_svc}" ]
    networks: [ "{net}" ]
    volumes:
      - ./nginx_configs/cdn_edge.conf:/etc/nginx/templates/default.conf.template:ro
    environment:
      - ORIGIN_SERVER_NAME={origin_svc}
      - REGION=edge
    command: ["/bin/sh","-c","envsubst '$$ORIGIN_SERVER_NAME $$REGION' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
    restart: always
"""

    # ---- resolv.conf for client ----
    lines = ["search sim.local", "options ndots:1"]
    for _, inst in NETWORKS.items():
        lines.append(f"nameserver 172.{inst.subnet_octet}.0.53")
    os.makedirs("dns_config", exist_ok=True)
    with open(os.path.join("dns_config", "resolv.dns_client.conf"), "w") as rf:
        rf.write("\n".join(lines) + "\n")

    # ---- choose a real DNS log for passive-agent (first network) ----
    first_net = next(iter(NETWORKS.keys()), None)
    passive_agent_vols = [
        "- ./dns_config:/dns_config:ro",
        "- ./monitoring:/monitoring:ro",
    ]
    if first_net:
        passive_agent_vols.append(f"- ./bind_logs/{first_net}/query.log:/samples/bind-query.log:ro")

    # ---- monitoring and client ----
    base_exporter_nets = {"soc_net", "default", "dmz_net", "sensors_net"}
    exporter_network_names = base_exporter_nets | monitor_nets
    exporter_networks_block = "\n".join(
        f"      - {name}" for name in sorted(exporter_network_names)
    )
    client_networks_block = (
        "\n".join(f"      - {name}" for name in sorted(test_client_nets))
        if test_client_nets
        else "      - default"
    )

    if NETWORKS:
        services_yaml += f"""  fluxlab_exporter:
    build:
      context: ./monitoring/exporter
    container_name: fluxlab_exporter
    environment:
      - FLUXLAB_REGISTRY=/data/registry.json
      - FLUXLAB_DNS_DIR=/dns_config
      - FLUXLAB_PROJECT={PROJECT_NAME}
    volumes:
      - ./monitoring:/data:ro
      - ./dns_config:/dns_config:ro
    ports: [ "9108:9108" ]
    networks:
{exporter_networks_block if exporter_networks_block else "      - default"}
    restart: unless-stopped
  prometheus:
    image: prom/prometheus:latest
    container_name: fluxlab_prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=15d
    ports: [ "9090:9090" ]
    restart: unless-stopped
    networks:
      - soc_net
      - default
  grafana:
    image: grafana/grafana:latest
    container_name: fluxlab_grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=fluxlab
    volumes:
      - ./monitoring/grafana:/var/lib/grafana
    ports: [ "3000:3000" ]
    restart: unless-stopped
    networks:
      - soc_net
      - default
  dns_client_test:
    build:
      context: .
      dockerfile: Dockerfile.client
    container_name: dns_client_test
    tty: true
    stdin_open: true
    command: ["/usr/local/bin/start_client.sh"]
    ports:
      - "8888:8888"
    volumes:
      - ./dns_config/resolv.dns_client.conf:/etc/resolv.conf:ro
      - {home_dir}/Desktop:/workspace:cached
    networks:
{client_networks_block if client_networks_block else "      - default"}

  dns_client_desktop:
    build:
      context: .
      dockerfile: Dockerfile.desktop
    container_name: dns_client_desktop
    profiles: ["desktop"]
    environment:
      - PUID=0
      - PGID=0
      - TZ=UTC
    ports:
      - "8081:3000"
    volumes:
      - ./dns_config/resolv.dns_client.conf:/etc/resolv.conf:ro
    networks:
{client_networks_block if client_networks_block else "      - default"}
"""

    # ---- global networks ----
    networks_yaml += """  sensors_net: {}
  dmz_net: {}
  soc_net: {}
"""

    # ---- Postgres + Redpanda + Agents ----
    services_yaml += f"""  postgres:
    image: postgres:16
    container_name: ffl-postgres
    environment:
      POSTGRES_USER: ${"{"}PGUSER{"}"}
      POSTGRES_PASSWORD: ${"{"}PGPASSWORD{"}"}
      POSTGRES_DB: ${"{"}PGDATABASE{"}"}
    volumes:
      - pg_data:/var/lib/postgresql/data
    networks: [ "soc_net" ]

  redpanda:
    image: redpandadata/redpanda:latest
    container_name: ffl-redpanda
    command:
      - redpanda start
      - --overprovisioned
      - --smp=1
      - --memory=1G
      - --reserve-memory=0M
      - --node-id=0
      - --check=false
      - --kafka-addr=0.0.0.0:9092
      - --advertise-kafka-addr=redpanda:9092
    ports: [ "9092:9092", "9644:9644" ]
    volumes:
      - redpanda_data:/var/lib/redpanda/data
    networks: [ "soc_net", "dmz_net", "sensors_net" ]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:9644/v1/status/ready"]
      interval: 5s
      timeout: 3s
      retries: 20

  active-probe:
    build: ./active-probe
    container_name: ffl-active-probe
    environment:
      - KAFKA_BROKERS=redpanda:9092
      - KAFKA_TOPIC_FF_PROBES=ff.probes
      - CORE_HOST=http://fluxlab_exporter:9108
      - PROBE_INTERVAL=3
    depends_on:
      redpanda:
        condition: service_healthy
      fluxlab_exporter:
        condition: service_started
    networks: [ "dmz_net" ]
    command: ["python", "probe.py"]

  passive-agent:
    build: ./passive-agent
    container_name: ffl-passive-agent
    environment:
      - KAFKA_BROKERS=redpanda:9092
      - KAFKA_TOPIC_FF_SIGNALS=ff.signals
      - CORE_HOST=http://fluxlab_exporter:9108
    volumes:
{chr(10).join(["      " + v for v in passive_agent_vols])}
    depends_on:
      redpanda:
        condition: service_healthy
      fluxlab_exporter:
        condition: service_started
    networks: [ "sensors_net" ]
    command: ["python", "agent.py", "--file", "/samples/bind-query.log"]

  kafka_ingestor:
    build: ./ingestor
    container_name: fluxlab_ingestor
    environment:
      - KAFKA_BROKERS=redpanda:9092
      - KAFKA_TOPIC_FF_PROBES=ff.probes
      - KAFKA_TOPIC_FF_SIGNALS=ff.signals
      - POSTGRES_HOST=postgres
      - POSTGRES_PORT=5432
      - POSTGRES_DB=${"{"}PGDATABASE{"}"}
      - POSTGRES_USER=${"{"}PGUSER{"}"}
      - POSTGRES_PASSWORD=${"{"}PGPASSWORD{"}"}
    depends_on:
      redpanda:
        condition: service_healthy
      postgres:
        condition: service_started
    networks: [ "soc_net" ]
    restart: unless-stopped

  pg_adminer:
    image: adminer:latest
    container_name: fluxlab_adminer
    environment:
      - ADMINER_DEFAULT_SERVER=postgres
    depends_on:
      - postgres
    ports: [ "8080:8080" ]
    networks: [ "soc_net" ]
    restart: unless-stopped
"""

    volumes_yaml = """volumes:
  pg_data: {}
  redpanda_data: {}
"""

    return "version: '3.9'\n\n" + networks_yaml + "\n" + volumes_yaml + "\n" + services_yaml
