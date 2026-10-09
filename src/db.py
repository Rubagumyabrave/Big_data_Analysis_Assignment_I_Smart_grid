"""Shared database connection. Settings come from the .env file."""
import os
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent   # the project folder


def load_env():
    """Read KEY=VALUE lines from .env into environment variables."""
    env_file = ROOT / ".env"
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()


def connect():
    """Open a connection to the assignment database, session time zone CAT."""
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        options="-c timezone=Africa/Kigali",
    )