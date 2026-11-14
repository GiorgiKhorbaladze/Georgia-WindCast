# Georgia WindCast - MVP technical specification

## Scope
Informational monitoring for Georgia. Show national actual wind generation (MW) from GSE, history collected by this application, and model-derived wind for Ruisi, Zemo Wind and Kartli/Gori. Provide an interactive map, historical weather comparisons and a 48–72 hour meteorological forecast. This product has no SCADA or dispatching function.

## Architecture
Next.js, TypeScript, Tailwind, MapLibre GL JS, and Apache ECharts. FastAPI read API, separate scheduled ingestion worker, and PostgreSQL migrations. Docker Compose for reproducible startup and GitHub Actions for verification. Prefer standard PostgreSQL and record any proposed deviation in an ADR. Configure service endpoints, freshness thresholds and credentials through environment variables.

## Data contracts
- Generation is national aggregate MW only. A candidate source is https://www.gse.com.ge/apps/gsebackend/rest/map and candidate field `typeSum.windPowerData`. Issue #3 validates the candidate and its reuse terms. Aim for approximately 60-second server-side polling only if supported. Preserve provenance and source observation and retrieval timestamps separately. If trustworthy observation time is missing, show freshness as unverified. Retries must not refresh stale observations. Keep history gaps visible.
- Site weather uses verified coordinates and Open-Meteo initially. Expose speed in m/s, direction in meteorological degrees and height above ground at 10 m and 100 m, plus speed at 200 m where available. Retain source/model, valid time, model run if supplied and retrieval time. Historical weather analysis and forecasts are model products. Missing variables, unavailable stations and unsupported heights remain explicit.
- Store UTC and display Asia/Tbilisi. Keep production and fixtures separate. Never allocate national MW to farms, present model weather as station telemetry, or present weather forecasts as MW forecasts. Credit GSE, weather providers and basemap sources under applicable terms.

## Roadmap
1. Reproducible foundation and initial application CI (#1).
2. Independent GSE and weather integrations (#3, #4).
3. Dark cyan/navy dashboard and charts, Georgia map with supported animated wind, synchronized history and forecast views (#5–#7).
4. Independent QA and private deployment readiness (#8, #9).

See [Epic #2](https://github.com/GiorgiKhorbaladze/Georgia-WindCast/issues/2) for the linked backlog.

## Change control
Claude Code implements and tests on feature branches, with linked PRs and exact-head CI evidence. ChatGPT Work reviews data integrity, architecture and defects independently. Owner approval is required for merges and public release. GitHub reports that classic branch protection and rulesets are unenforced for the current private repository/account arrangement. Until GitHub enforcement is available, use pull requests and verify green CI before requesting owner approval.

## License decision for owner review
The private repository starts without an open-source license. The owner will decide whether to grant redistribution rights and under which license. Third-party software and data keep their own terms.
