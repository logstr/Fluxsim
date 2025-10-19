import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import psycopg2
from kafka import KafkaConsumer


KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "redpanda:9092")
PROBE_TOPIC = os.getenv("KAFKA_TOPIC_FF_PROBES", "ff.probes")
SIGNAL_TOPIC = os.getenv("KAFKA_TOPIC_FF_SIGNALS", "ff.signals")
CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "fluxlab-db-writer")

PG_HOST = os.getenv("POSTGRES_HOST", os.getenv("PGHOST", "postgres"))
PG_PORT = int(os.getenv("POSTGRES_PORT", os.getenv("PGPORT", "5432")))
PG_DB = os.getenv("POSTGRES_DB", os.getenv("PGDATABASE", "fluxlab"))
PG_USER = os.getenv("POSTGRES_USER", os.getenv("PGUSER", "fluxlab"))
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", os.getenv("PGPASSWORD", "fluxlab"))

SHUTDOWN = threading.Event()


def log(msg: str) -> None:
    print(f"[db-writer] {msg}", flush=True)


def connect_pg():
    while not SHUTDOWN.is_set():
        try:
            conn = psycopg2.connect(
                host=PG_HOST,
                port=PG_PORT,
                dbname=PG_DB,
                user=PG_USER,
                password=PG_PASSWORD,
            )
            conn.autocommit = True
            log("Connected to Postgres.")
            return conn
        except Exception as exc:
            log(f"Postgres connect failed: {exc}. retrying in 3s...")
            time.sleep(3)
    raise SystemExit("Shutdown before Postgres connection established.")


def ensure_tables(conn) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS probe_events (
        id BIGSERIAL PRIMARY KEY,
        domain TEXT NOT NULL,
        answers JSONB,
        ttl INTEGER,
        error BOOLEAN DEFAULT FALSE,
        err TEXT,
        ts TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS signal_events (
        id BIGSERIAL PRIMARY KEY,
        domain TEXT NOT NULL,
        ttl INTEGER,
        source TEXT,
        ts TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    log("Ensured tables exist.")


def to_ts(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return datetime.now(tz=timezone.utc)


def upsert_probe(conn, payload: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO probe_events (domain, answers, ttl, error, err, ts)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                payload.get("domain"),
                json.dumps(payload.get("answers")) if payload.get("answers") else None,
                payload.get("ttl"),
                payload.get("error", False),
                payload.get("err"),
                to_ts(payload.get("ts")),
            ),
        )


def upsert_signal(conn, payload: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO signal_events (domain, ttl, source, ts)
            VALUES (%s, %s, %s, %s)
            """,
            (
                payload.get("domain"),
                payload.get("ttl"),
                payload.get("source"),
                to_ts(payload.get("ts")),
            ),
        )


def start_consumer(topics: Iterable[str]):
    brokers = [b.strip() for b in KAFKA_BROKERS.split(",") if b.strip()]
    consumer = KafkaConsumer(
        *topics,
        bootstrap_servers=brokers,
        group_id=CONSUMER_GROUP,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )
    log(f"Subscribed to topics: {topics}")
    return consumer


def main():
    topics = [PROBE_TOPIC, SIGNAL_TOPIC]
    conn = connect_pg()
    ensure_tables(conn)
    consumer = start_consumer(topics)

    try:
        for message in consumer:
            if SHUTDOWN.is_set():
                break
            payload = message.value or {}
            topic = message.topic
            try:
                if topic == PROBE_TOPIC:
                    upsert_probe(conn, payload)
                elif topic == SIGNAL_TOPIC:
                    upsert_signal(conn, payload)
            except Exception as exc:
                log(f"Failed to persist message from {topic}: {exc}")
    finally:
        consumer.close()
        conn.close()
        log("Shut down.")


def handle_signal(signum, frame):
    log(f"Received signal {signum}, shutting down...")
    SHUTDOWN.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        main()
    except Exception as exc:
        log(f"Fatal error: {exc}")
        sys.exit(1)
