import os

from app.db import connect


def check():
    maximum_age = max(60, int(os.environ.get("WORKER_INTERVAL_SECONDS", "30")) * 3)
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*) FROM worker_heartbeat "
            "WHERE observed_at > now() - make_interval(secs => %s)",
            (maximum_age,),
        ).fetchone()[0]
        if count != 1:
            raise RuntimeError("Worker heartbeat unavailable or stale")


if __name__ == "__main__":
    check()
