# passive-agent/agent.py
import os, time, json, argparse, re
from kafka import KafkaProducer
import requests

BROKERS = os.getenv("KAFKA_BROKERS", "redpanda:9092")
TOPIC   = os.getenv("KAFKA_TOPIC_FF_SIGNALS", "ff.signals")
CORE    = os.getenv("CORE_HOST", "http://core:8000")

# Sample BIND-ish line matcher; adapt if your format differs
LINE = re.compile(r".*query:\s+([a-zA-Z0-9._-]+)\s+IN\s+A.*(?:ttl=(\d+))?.*", re.IGNORECASE)

producer = KafkaProducer(
    bootstrap_servers=BROKERS.split(","),
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)

def emit(domain: str, ttl: int | None):
    evt = {"domain": domain, "ttl": ttl, "source": "dns_log", "ts": time.time()}
    producer.send(TOPIC, evt)
    # Optional: keep Core warm / side-effect ping
    try:
        requests.get(f"{CORE}/status", timeout=1)
    except Exception:
        pass

def tail(path: str):
    with open(path, "r") as f:
        # seek to end if you only want new lines:
        # f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.25)
                continue
            m = LINE.match(line.strip())
            if not m:
                continue
            domain = m.group(1)
            ttl = int(m.group(2)) if m.group(2) else None
            emit(domain, ttl)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="path to DNS log to tail")
    args = ap.parse_args()
    tail(args.file)
