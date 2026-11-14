# ADR 0001: Foundation services and deferred integrations

Status: accepted for Issue #1 implementation.

Use Next.js/TypeScript/Tailwind, FastAPI, a separate Python scheduler and standard
PostgreSQL 17 (official Alpine image) with Alembic. Alpine reduces local disk use;
no database extension or alternate storage engine is introduced. API and worker share a locked Python environment and
image, but run as separate services. Migration completion gates startup. A named
volume persists PostgreSQL data. All services have startup health checks.

The initial worker writes a UTC heartbeat, not fabricated observations. The UI
and status API explicitly report unavailable sources. The initial UI is static:
no frontend API endpoint configuration is needed until integration. MapLibre and
ECharts are deferred until map/chart issues #5–#7; no deviation from the target
architecture is intended. External feed URLs, freshness thresholds and credentials
will be introduced through environment configuration with their source contracts.
No external feed, font, map tile or weather service is required at build or test time.
Package installation and container image pulls require registry access; runtime
and CI assertions do not depend on upstream data sources.

The scheduler is deliberately minimal until ingestion requirements exist. It
retries failed heartbeats and logs failures; its health check detects stale
heartbeats. Services publish only loopback ports for local development. This is
not a production deployment or a release approval.

Local cloud verification needs session CA trust and reduced VFS disk usage.
These are environment-only adjustments, documented with the passing transcript
in [Issue #1 evidence](evidence/issue-1.md); the committed CI uses normal builds.
