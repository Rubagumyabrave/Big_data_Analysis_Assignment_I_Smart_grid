"""1.2.4 Load the 4,000 meter metadata rows into the meters table."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # find the generator
import smart_meter_simulator as sim
from db import connect


def main():
    meters = sim.meter_metadata()
    print(f"Meters returned by meter_metadata(): {len(meters)}")

    rows = [(m["meter_id"], m["region"], m["customer_type"],
             m["base_power_kw"], m["power_factor"]) for m in meters]

    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO meters (meter_id, region, customer_type, base_power_kw, power_factor)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (meter_id) DO NOTHING""",
            rows,
        )
        conn.commit()
        cur.execute("SELECT count(*) FROM meters")
        print(f"Rows in meters table: {cur.fetchone()[0]}")


if __name__ == "__main__":
    main()