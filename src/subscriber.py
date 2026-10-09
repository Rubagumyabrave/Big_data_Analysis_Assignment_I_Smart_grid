"""1.3.2 MQTT subscriber: energy/meters/# at QoS 1 -> energy_live table."""
import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import ROOT, connect

TOPIC = "energy/meters/#"
EXPECTED = 2000      # stop when this many messages have arrived ...
IDLE_SECONDS = 15    # ... or after this many seconds without a new message
BATCH = 200          # insert rows in groups of 200
FIELDS = ("meter_id", "event_time", "received_time", "power_kw",
          "voltage_v", "current_a", "frequency_hz", "energy_kwh")
INSERT = f"INSERT INTO energy_live ({', '.join(FIELDS)}) VALUES %s"

(ROOT / "results").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(ROOT / "results" / "pilot_subscriber.log", mode="w"),
              logging.StreamHandler()])
log = logging.getLogger("subscriber")

conn = connect()
cur = conn.cursor()
rows = queue.Queue()         # hand-over point between the two threads
STOP = object()              # special item that tells the writer to finish
lock = threading.Lock()
stats = {"received": 0, "redelivered": 0, "parse_errors": 0,
         "inserted": 0, "insert_errors": 0, "max_backlog": 0}
last_message = time.monotonic()


# ---------- writer thread: database work only ----------
def insert(batch):
    if not batch:
        return
    try:
        execute_values(cur, INSERT, batch)
        conn.commit()
        with lock:
            stats["inserted"] += len(batch)
    except Exception as exc:
        conn.rollback()
        with lock:
            stats["insert_errors"] += len(batch)
        log.error("Insert failed for %d rows: %s", len(batch), exc)


def writer():
    batch = []
    while True:
        try:
            item = rows.get(timeout=0.5)
        except queue.Empty:
            item = None                      # nothing new for 0.5 s
        if item is STOP:
            insert(batch)                    # final partial batch
            return
        if item is not None:
            batch.append(item)
        if len(batch) >= BATCH or (item is None and batch):
            insert(batch)
            batch = []


# ---------- MQTT callbacks: fast, no database work ----------
def on_connect(client, userdata, flags, reason_code, properties):
    log.info("Connected to broker: %s", reason_code)
    client.subscribe(TOPIC, qos=1)


def on_subscribe(client, userdata, mid, reason_codes, properties):
    log.info("Subscribed to %s: %s", TOPIC, [str(rc) for rc in reason_codes])
    log.info("READY - start the publisher now")


def on_message(client, userdata, msg):
    global last_message
    with lock:
        stats["received"] += 1
        last_message = time.monotonic()
        count = stats["received"]
        if msg.dup:
            stats["redelivered"] += 1
            log.warning("Redelivered message on %s", msg.topic)
    try:
        data = json.loads(msg.payload)
        rows.put(tuple(data[f] for f in FIELDS))
    except (ValueError, KeyError) as exc:
        with lock:
            stats["parse_errors"] += 1
        log.error("Parse error on %s: %s", msg.topic, exc)
    with lock:
        stats["max_backlog"] = max(stats["max_backlog"], rows.qsize())
    if count % 500 == 0:
        log.info("Received %d messages (waiting to insert: %d)", count, rows.qsize())


def main():
    cur.execute("TRUNCATE energy_live")      # 1.3.2: begin with an empty table
    conn.commit()
    cur.execute("SELECT count(*) FROM energy_live")
    log.info("energy_live emptied, rows now: %d", cur.fetchone()[0])

    writer_thread = threading.Thread(target=writer, name="db-writer")
    writer_thread.start()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pilot-subscriber")
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    client.connect(os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"]))
    client.loop_start()

    while True:                              # wait until finished or idle
        time.sleep(0.5)
        with lock:
            done = stats["received"] >= EXPECTED
            idle = stats["received"] > 0 and time.monotonic() - last_message > IDLE_SECONDS
        if done or idle:
            break

    time.sleep(2)                            # catch any late redelivery
    client.loop_stop()
    client.disconnect()
    rows.put(STOP)                           # tell the writer to finish ...
    writer_thread.join()                     # ... and wait until it has
    cur.execute("SELECT count(*) FROM energy_live")
    stored = cur.fetchone()[0]
    conn.close()
    log.info("SUMMARY received=%d redelivered=%d parse_errors=%d inserted=%d "
             "insert_errors=%d energy_live_rows=%d max_backlog=%d",
             stats["received"], stats["redelivered"], stats["parse_errors"],
             stats["inserted"], stats["insert_errors"], stored, stats["max_backlog"])


if __name__ == "__main__":
    main()