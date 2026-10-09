"""Q1-Q5 workloads for 3.2 and 4.3. {table} is replaced by the table being measured."""

QUERIES = {
    # Q1: average power per CAT hour on 21 September
    "Q1": """
        SELECT date_trunc('hour', event_time, 'Africa/Kigali') AS hour_cat,
               avg(power_kw)                                    AS avg_power_kw,
               count(*)                                         AS readings
        FROM {table}
        WHERE event_time >= '2026-09-21 00:00:00+02'
          AND event_time <  '2026-09-22 00:00:00+02'
        GROUP BY 1
        ORDER BY 1""",

    # Q2: ten highest network-total 15-minute intervals, 22-28 September
    "Q2": """
        SELECT event_time, sum(power_kw) AS total_power_kw
        FROM {table}
        WHERE event_time >= '2026-09-22 00:00:00+02'
          AND event_time <  '2026-09-29 00:00:00+02'
        GROUP BY event_time
        ORDER BY total_power_kw DESC, event_time ASC
        LIMIT 10""",

    # Q3: total energy per meter over the whole period
    "Q3": """
        SELECT meter_id, sum(energy_kwh) AS total_energy_kwh
        FROM {table}
        GROUP BY meter_id
        ORDER BY meter_id""",

    # Q4: one meter, 22-28 September
    "Q4": """
        SELECT sum(energy_kwh) AS energy_kwh,
               avg(power_kw)   AS avg_power_kw,
               max(power_kw)   AS peak_power_kw
        FROM {table}
        WHERE meter_id = 1000000000
          AND event_time >= '2026-09-22 00:00:00+02'
          AND event_time <  '2026-09-29 00:00:00+02'""",

    # Q5: full scan summary
    "Q5": """
        SELECT count(*)        AS row_count,
               sum(energy_kwh) AS total_energy_kwh,
               avg(power_kw)   AS avg_power_kw,
               min(power_kw)   AS min_power_kw,
               max(power_kw)   AS max_power_kw
        FROM {table}""",
}