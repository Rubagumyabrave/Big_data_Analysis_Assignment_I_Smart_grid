"""1.3.1 MQTT publisher: first 2,000 generator readings -> energy/meters/{meter_id}, QoS 1."""
import itertools
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))            # to import the generator
sys.path.insert(0, str(ROOT / "src"))    # to import db (loads .env)
import smart_meter_simulator as sim
import db  # noqa: F401  (reads .env into os.environ)

COUNT = 2000
RATE = 300             # messages per second; run 1 at full speed lost 183 (queue_full)

(ROOT / "results").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(ROOT / "results" / "pilot_publisher.log", mode="w"),
              logging.StreamHandler()])
log = logging.getLogger("publisher")

lock = threading.Lock()
acked = set()          # message ids confirmed by a PUBACK
failed = {}            # message ids the broker rejected
connected = threading.Event()


def on_connect(client, userdata, flags, reason_code, properties):
    log.info("Connected to broker: %s", reason_code)
    connected.set()


def on_publish(client, userdata, mid, reason_code, properties):
    # For QoS 1 this runs when the broker's PUBACK arrives
    with lock:
        if reason_code.is_failure:
            failed[mid] = str(reason_code)
        else:
            acked.add(mid)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pilot-publisher")
    client.on_connect = on_connect
    client.on_publish = on_publish
    client.connect(os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"]))
    client.loop_start()
    if not connected.wait(10):
        log.error("Could not connect to the broker")
        return

    taken = 0
    mids = []
    start = time.perf_counter()
    for reading in itertools.islice(sim.iter_readings(), COUNT):
        taken += 1
        # pace sending: message n is sent no earlier than start + n / RATE seconds
        delay = start + taken / RATE - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        topic = f"energy/meters/{reading['meter_id']}"
        info = client.publish(topic, json.dumps(reading), qos=1, retain=False)
        mids.append(info.mid)
    log.info("Taken from generator: %d - waiting for broker acknowledgements", taken)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with lock:
            if len(acked) + len(failed) >= len(mids):
                break
        time.sleep(0.1)
    elapsed = time.perf_counter() - start
    client.loop_stop()
    client.disconnect()

    unacked = len(mids) - len(acked) - len(failed)
    for mid, reason in failed.items():
        log.error("Broker rejected message id %s: %s", mid, reason)
    log.info("SUMMARY taken=%d acknowledged=%d failed=%d unacknowledged=%d "
             "rate=%d msg/s elapsed=%.2fs",
             taken, len(acked), len(failed), unacked, RATE, elapsed)


if __name__ == "__main__":
    main()