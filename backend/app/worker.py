"""Foundation scheduler: records liveness only; never contacts external feeds."""

import logging
import os
import time

from app.db import connect


def tick():
    with connect() as conn:
        conn.execute(
            "INSERT INTO worker_heartbeat (id, observed_at) VALUES (1, now()) "
            "ON CONFLICT (id) DO UPDATE SET observed_at = EXCLUDED.observed_at"
        )


def main():
    logging.basicConfig(level=logging.INFO)
    interval = max(1, int(os.environ.get("WORKER_INTERVAL_SECONDS", "30")))
    while True:
        try:
            tick()
        except Exception:
            logging.exception("Worker heartbeat failed")
        time.sleep(interval)


if __name__ == "__main__":
    main()
