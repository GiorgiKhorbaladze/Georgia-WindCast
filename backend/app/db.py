import os

import psycopg


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3)


def ready():
    with connect() as conn:
        # Readiness requires both connectivity and the initial migration.
        conn.execute("SELECT id FROM worker_heartbeat LIMIT 1")
