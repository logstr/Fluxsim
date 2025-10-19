# monitoring/exporter/app.py
import os, json, time, socket, threading
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, Response, HTTPException, Body
from prometheus_client import (
    CollectorRegistry, Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST
)
import dns.resolver

REGISTRY_PATH = os.environ.get("FLUXLAB_REGISTRY", "/data/registry.json")
DNS_CFG_DIR   = os.environ.get("FLUXLAB_DNS_DIR", "/dns_config")
PROJECT_NAME  = os.environ.get("FLUXLAB_PROJECT", "multi-flux-sim")

app = FastAPI(title="FluxLab Exporter")

# -------------------------
# Simple in-memory store for ingested events
# -------------------------
LOCK = threading.Lock()
EVENTS_TOTAL = {"probe": 0, "signal": 0, "query": 0}
LAST_PROBE: Dict[str, Dict[str, Any]] = {}   # domain -> {ttl, answers, ts}
LAST_SIGNAL: Dict[str, Dict[str, Any]] = {}  # domain -> {ttl, ts, source}
DOMAIN_COUNTS: Dict[str, int] = {}           # domain -> total events seen

def _load_registry() -> Dict:
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    except Exception:
        return {"updated_at": 0, "networks": {}}

def _read_flux_agents(net: str) -> List[str]:
    p = os.path.join(DNS_CFG_DIR, f"flux_agents_{net}.txt")
    try:
        with open(p) as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []

def _dig(host: str, nameserver: Optional[str]=None) -> List[str]:
    if not host:
        return []
    try:
        r = dns.resolver.Resolver()
        if nameserver:
            r.nameservers = [nameserver]
        ans = r.resolve(host, "A", lifetime=2.0)
        return sorted({str(a.address) for a in ans})
    except Exception:
        return []

def _probe_http(hostport: str, timeout: float=2.0) -> bool:
    try:
        host, port = hostport.split(":")
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.sendall(b"GET / HTTP/1.0\r\nHost: fluxlab\r\n\r\n")
            s.settimeout(timeout)
            _ = s.recv(64)
        return True
    except Exception:
        return False

# -------------------------
# Health / Status
# -------------------------
@app.get("/health")
def health():
    return {"ok": True, "project": PROJECT_NAME}

@app.get("/status")
def status():
    with LOCK:
        return {
            "events_total": dict(EVENTS_TOTAL),
            "domains_tracked": len(DOMAIN_COUNTS),
            "last_probe_examples": dict(list(LAST_PROBE.items())[:5]),
            "last_signal_examples": dict(list(LAST_SIGNAL.items())[:5]),
        }

# -------------------------
# Ingest endpoints (agents call these)
# -------------------------
def _safe_int(v):
    try:
        return int(v) if v is not None else None
    except Exception:
        return None

@app.post("/ingest/probe")
def ingest_probe(payload: Dict[str, Any] = Body(...)):
    """
    Expected fields:
      - domain (str, required)
      - answers (list[str], optional)
      - ttl (int, optional)
      - ts (float, optional)
    """
    domain = payload.get("domain")
    if not domain:
        raise HTTPException(status_code=400, detail="domain required")

    ttl = _safe_int(payload.get("ttl"))
    answers = payload.get("answers") or []
    ts = payload.get("ts") or time.time()

    with LOCK:
        EVENTS_TOTAL["probe"] += 1
        DOMAIN_COUNTS[domain] = DOMAIN_COUNTS.get(domain, 0) + 1
        LAST_PROBE[domain] = {"ttl": ttl, "answers": answers, "ts": ts}

    return {"ok": True}

@app.post("/ingest/signal")
def ingest_signal(payload: Dict[str, Any] = Body(...)):
    """
    Expected fields:
      - domain (str, required)
      - ttl (int, optional)
      - ts (float, optional)
      - source (str, optional; e.g., 'dns_log')
    """
    domain = payload.get("domain")
    if not domain:
        raise HTTPException(status_code=400, detail="domain required")

    ttl = _safe_int(payload.get("ttl"))
    ts = payload.get("ts") or time.time()
    source = payload.get("source") or "agent"

    with LOCK:
        EVENTS_TOTAL["signal"] += 1
        DOMAIN_COUNTS[domain] = DOMAIN_COUNTS.get(domain, 0) + 1
        LAST_SIGNAL[domain] = {"ttl": ttl, "ts": ts, "source": source}

    return {"ok": True}

# -------------------------
# Metrics
# -------------------------
@app.get("/metrics")
def metrics():
    reg = CollectorRegistry()

    # existing metrics
    up          = Gauge("fluxlab_network_up", "Network scrape OK (exporter viewpoint)", ["net"], registry=reg)
    dns_up      = Gauge("fluxlab_dns_up", "DNS resolution succeeded", ["net","fqdn"], registry=reg)
    dns_answers = Gauge("fluxlab_dns_answers", "Count of A answers", ["net","fqdn"], registry=reg)
    flux_agents = Gauge("fluxlab_flux_agents", "Configured flux agent IPs in file", ["net"], registry=reg)
    cdn_edges   = Gauge("fluxlab_cdn_edges", "Configured CDN edges (size)", ["net"], registry=reg)
    lb_workers  = Gauge("fluxlab_lb_workers", "Configured LB workers (size)", ["net"], registry=reg)
    http_up     = Gauge("fluxlab_http_up", "HTTP/TCP check to service (LB or first edge)", ["net","target"], registry=reg)
    ttl_hint    = Gauge("fluxlab_dns_ttl_hint", "TTL used in zone (seconds) if known", ["net"], registry=reg)
    scrape_ts   = Gauge("fluxlab_scrape_timestamp", "Exporter scrape unix time", registry=reg)

    # NEW: ingest-derived metrics
    events_total = Counter("fluxlab_events_total", "Total ingested events", ["source"], registry=reg)
    domains_tracked = Gauge("fluxlab_domains_tracked", "Number of domains with any activity", registry=reg)
    domain_last_ttl = Gauge("fluxlab_domain_last_ttl", "Last seen TTL for domain", ["source","domain"], registry=reg)
    domain_last_seen = Gauge("fluxlab_domain_last_seen", "Last seen unix ts for domain", ["source","domain"], registry=reg)
    domain_event_count = Gauge("fluxlab_domain_events", "Total events seen for domain", ["domain"], registry=reg)

    # export ingest state
    with LOCK:
        # counters
        for src in ("probe","signal","query"):
            events_total.labels(source=src).inc(EVENTS_TOTAL.get(src, 0))  # inc by total since process start

        domains_tracked.set(len(DOMAIN_COUNTS))
        # per-domain gauges from last seen
        for d, meta in LAST_PROBE.items():
            if meta.get("ttl") is not None:
                domain_last_ttl.labels(source="probe", domain=d).set(int(meta["ttl"]))
            if meta.get("ts") is not None:
                domain_last_seen.labels(source="probe", domain=d).set(float(meta["ts"]))
        for d, meta in LAST_SIGNAL.items():
            if meta.get("ttl") is not None:
                domain_last_ttl.labels(source="signal", domain=d).set(int(meta["ttl"]))
            if meta.get("ts") is not None:
                domain_last_seen.labels(source="signal", domain=d).set(float(meta["ts"]))
        for d, n in DOMAIN_COUNTS.items():
            domain_event_count.labels(domain=d).set(n)

    # your existing registry-based metrics
    data: Dict = _load_registry()
    nets: Dict[str, Dict] = data.get("networks", {})
    now = time.time()

    for name, meta in nets.items():
        fqdn  = meta.get("fqdn")
        kind  = (meta.get("kind") or "").lower()
        dns_ip = meta.get("dns_ip")
        size  = int(meta.get("size") or 1)

        # TTL hint via $TTL header if present
        ttl = None
        zf = os.path.join(DNS_CFG_DIR, f"db.{name}.zone")
        try:
            with open(zf) as f:
                for ln in f:
                    ln = ln.strip()
                    if ln.startswith("$TTL"):
                        ttl = int(ln.split()[1]); break
        except Exception:
            pass
        if ttl is not None:
            ttl_hint.labels(net=name).set(ttl)

        # role-specific counts
        if kind == "flux":
            agents = _read_flux_agents(name)
            flux_agents.labels(net=name).set(len(agents))
        elif kind == "cdn":
            cdn_edges.labels(net=name).set(size)
        elif kind == "lb":
            lb_workers.labels(net=name).set(size)

        # DNS resolution (system + explicit nameserver)
        ok = True
        ans1 = _dig(fqdn) if fqdn else []
        ans2 = _dig(fqdn, dns_ip) if (fqdn and dns_ip) else []
        if fqdn:
            dns_up.labels(net=name, fqdn=fqdn).set(1.0 if (ans1 or ans2) else 0.0)
            dns_answers.labels(net=name, fqdn=fqdn).set(len(set(ans1 + ans2)))
            ok = ok and bool(ans1 or ans2)

        # L4/HTTP probe
        target = None
        if kind == "lb" and meta.get("lb_ip"):
            target = f"{meta['lb_ip']}:80"
        elif kind == "cdn" and ans1:
            target = f"{sorted(ans1)[0]}:80"
        elif kind in ("normal", "flux") and ans1:
            target = f"{sorted(ans1)[0]}:80"

        if target:
            http_ok = _probe_http(target)
            http_up.labels(net=name, target=target).set(1.0 if http_ok else 0.0)
            ok = ok and http_ok

        up.labels(net=name).set(1.0 if ok else 0.0)

    scrape_ts.set(now)
    return Response(content=generate_latest(reg), media_type=CONTENT_TYPE_LATEST)
