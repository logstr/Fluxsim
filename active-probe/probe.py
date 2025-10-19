# active-probe/probe.py
import os, time, json, random, socket
from typing import List
import dns.resolver
from kafka import KafkaProducer
import requests

# ---- config via env (with sane defaults) ----
BROKERS = os.getenv("KAFKA_BROKERS", "redpanda:9092")
TOPIC   = os.getenv("KAFKA_TOPIC_FF_PROBES", "ff.probes")
CORE    = os.getenv("CORE_HOST", "http://core:8000")  # set to http://fluxlab_exporter:9108 in compose
PROBE_DNS = os.getenv("PROBE_DNS")  # e.g., "172.20.0.53"
PROBE_INTERVAL = float(os.getenv("PROBE_INTERVAL", "3"))
KAFKA_WAIT = float(os.getenv("KAFKA_WAIT", "60"))  # seconds to wait for broker readiness

DOMAINS: List[str] = [
    "normalnet.sim.local",
    "fluxynet.sim.local",
    "lbnet.sim.local",
]
ENV_DOMAINS = os.getenv("PROBE_DOMAINS")
if ENV_DOMAINS:
    DOMAINS = [d.strip() for d in ENV_DOMAINS.split(",") if d.strip()]

def _tcp_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def wait_for_kafka(brokers: str, timeout_s: float = 60.0) -> None:
    """
    Waits for any broker in the list to accept TCP and for Kafka metadata fetch to succeed.
    Raises SystemExit if not ready within timeout.
    """
    deadline = time.time() + timeout_s
    hosts = [b.strip() for b in brokers.split(",") if b.strip()]
    print(f"[active-probe] Waiting for Kafka brokers: {hosts} (timeout {timeout_s}s)")
    last_tcp_ok = False

    while time.time() < deadline:
        # 1) TCP check first
        last_tcp_ok = False
        for hp in hosts:
            try:
                h, p = hp.split(":")
                if _tcp_ok(h, int(p)):
                    last_tcp_ok = True
                    break
            except Exception:
                pass

        if not last_tcp_ok:
            time.sleep(1.0)
            continue

        # 2) Try a quick metadata fetch by constructing a producer
        try:
            prod = KafkaProducer(bootstrap_servers=hosts)
            prod.close()
            print("[active-probe] Kafka metadata fetch OK")
            return
        except Exception as e:
            # broker may be up but not yet ready for metadata; keep waiting
            time.sleep(1.0)

    raise SystemExit("[active-probe] Kafka not ready within wait window")

# ---- initialize DNS resolver ----
resolver = dns.resolver.Resolver()
if PROBE_DNS:
    resolver.nameservers = [PROBE_DNS]

def probe_once(domain: str, producer: KafkaProducer):
    ts = time.time()
    event = {"domain": domain, "ts": ts}
    try:
        ans = resolver.resolve(domain, "A", lifetime=2.0)
        addrs = [rr.address for rr in ans]
        ttl = ans.rrset.ttl if hasattr(ans, "rrset") else None
        event.update({"answers": addrs, "ttl": ttl})
    except Exception as e:
        event.update({"error": True, "err": str(e)})

    # ship to Kafka (best-effort)
    try:
        producer.send(TOPIC, event)
    except Exception as e:
        # If sending fails, don't crash the loop; log and continue.
        print(f"[active-probe] Kafka send failed: {e}")

    # best-effort notify core (optional)
    try:
        requests.post(f"{CORE}/ingest/probe", json=event, timeout=1.5)
    except Exception:
        pass

if __name__ == "__main__":
    # Wait for Kafka/Redpanda to be ready before creating the producer
    wait_for_kafka(BROKERS, timeout_s=KAFKA_WAIT)
    producer = KafkaProducer(
        bootstrap_servers=[b.strip() for b in BROKERS.split(",") if b.strip()],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    # small initial delay to let DNS/net settle
    time.sleep(2)

    while True:
        d = random.choice(DOMAINS)
        probe_once(d, producer)
        time.sleep(PROBE_INTERVAL)
