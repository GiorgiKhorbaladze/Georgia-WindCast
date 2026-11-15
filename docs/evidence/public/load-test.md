# Anonymous-traffic load check (issue #18)

Date: 2026-11-15. Tool: `autocannon@8.0.0`. Target: production builds (`next start`, `uvicorn`) on a 4 vCPU amd64 build machine. That machine is shared with other jobs and is **not** an Ampere A1 host, so the numbers show relative behaviour, not a capacity guarantee. Data: the E2E seed (real recorded values). Requests went to the frontend directly, because Caddy's per-IP rate limits (60/min data, 240/min pages) would stop a single-IP load generator by design.

## Defect found and fixed

**Before the fix**, 20 concurrent dashboard loads for 30 s averaged 2.7 req/s at about 6 s latency (the frontend's backend timeout). The data route returned 100 % errors. Afterwards the API stayed **permanently hung**, including `/api/health`.

Root cause: client-aborted requests left their request-scoped (`yield` dependency) database sessions "idle in transaction". After 15 of them (pool 5 + overflow 10), every endpoint waited for a connection. Docker does not restart containers only because they are unhealthy, so production would have stayed down until someone intervened by hand.

Fix (backend, `app/db.py` + endpoints):
- Each endpoint opens and closes its session in its own thread (`session_scope()`), so teardown cannot be skipped.
- Pool wait is capped at 5 s, so requests fail fast instead of queueing.
- PostgreSQL ends transactions idle for more than 30 s and statements running longer than 15 s (`idle_in_transaction_session_timeout`, `statement_timeout`), as defence in depth.

Fix (frontend, `src/lib/api.ts`): concurrent visitors share one backend request per URL (coalescing), and successful responses are reused for 5 s (`WINDCAST_API_CACHE_SECONDS`). Failures are never cached. The cache is bounded to 256 entries.

Regression test: `backend/tests/test_connection_safety.py` runs real uvicorn with aborted clients and slow statements. Without the fix it fails with "15 connections leaked"; with the fix it passes.

## Results after the fix (30 s per row unless noted)

| Target | Concurrency | Req/s | p50 | p97.5 | p99 | Errors / non-2xx |
| --- | --- | --- | --- | --- | --- | --- |
| API `/api/v1/weather` directly, 2 s client timeout (the burst that hung the API), 15 s | 80 | 119.6 | 640 ms | 1040 ms | 1195 ms | 0 / 0 |
| `/` dashboard | 20 | 162.4 | 117 ms | 184 ms | 232 ms | 0 / 0 |
| `/` dashboard | 100 | 172.1 | 553 ms | 820 ms | 1047 ms | 0 / 0 |
| `/history` | 50 | 218.6 | 216 ms | 311 ms | 333 ms | 0 / 0 |
| `/map` | 50 | 193.3 | 246 ms | 366 ms | 382 ms | 0 / 0 |
| `/api/data/generation-latest` | 100 | 946.3 | 98 ms | 165 ms | 184 ms | 0 / 0 |
| `/api/data/status` | 100 | 992.0 | 96 ms | 137 ms | 163 ms | 0 / 0 |

After the burst, `/api/health` answered 200 in 0.2 s. Three seconds later every pool connection was idle (none "idle in transaction").

Idle memory of the full public stack (Docker, amd64): Caddy 18 MiB, frontend 41 MiB, API 72 MiB, worker 53 MiB, PostgreSQL 43 MiB, about 230 MiB in total.

## Interpretation

One Always Free A1 VM serves well beyond the traffic a LinkedIn post typically brings, which arrives in bursts of tens of concurrent visitors. The binding limits are the per-IP edge rate limits and the visitors' own connections, not the server. To be re-measured on the real host after deployment, with the edge in place and from several client IPs.
