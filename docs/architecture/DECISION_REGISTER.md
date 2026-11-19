# Canonical Decision Register — ADR-001–028

**Status:** ADR-001 through ADR-028 accepted. Historical research recommendations are not architecture decisions. Do not overwrite user-confirmed choices with earlier proposals.

| ID | Decision |
|---|---|
| 001 | Go modular monolith + separate simulator process |
| 002 | Hybrid parking resources |
| 003 | Real official data plus isolated synthetic simulation |
| 004 | PostgreSQL authoritative state, eventually consistent distribution |
| 005 | Distinct metered/delineated spaces, flexible curb zones, facilities |
| 006 | Evidence-aware separation of legal/fit/observed/predicted dimensions |
| 007 | Progressive data coverage and source transparency |
| 008 | Street parking first, especially free residential plus metered |
| 009 | Going Home / Going Out share one search engine |
| 010 | Explainable ranking and uncertainty; UNKNOWN never default probability |
| 011 | Adaptive bounded radius search |
| 012 | Evidence-tiered results |
| 013 | Verified Recommendations separated from unverified Discovery |
| 014 | Community evidence with review/provenance, not automatic legal truth |
| 015 | Go backend + Python GIS/ETL/simulator/ML |
| 016 | PostgreSQL/PostGIS + pgx/sqlc + goose; prod/sim DB separation |
| 017 | Durable PostgreSQL Inbox/Outbox + Redis Streams/cache, phased |
| 018 | MapLibre + OSRM driving/walking, replaceable routing port |
| 019 | React/TypeScript/Vite + TanStack Query, map-first responsive |
| 020 | Docker Compose, GitHub CI, testing/observability, no initial K8s |
| 021 | Monorepo with Go modules / React feature structure |
| 022 | Shared resource identity + specialized subtype tables |
| 023 | Use-case orchestration + domain ports/adapters; DB transactional writes |
| 024 | Source-aware ordering + conservative cross-source arbitration |
| 025 | Utility-driven, experience-first, consented community reporting; no points |
| 026 | Evidence-aware eligibility hard gate + explainable ranking |
| 027 | Contract-first REST + **WebSocket** with snapshot reconciliation; private sessions separate |
| **028** | **Immutable raw snapshot → validated staging → atomic published version** |

## Research boundaries (NOT accepted as facts)
- DTLA currently leads **CDS data validation** due to Code the Curb datasets; Westwood is a comparison for consumer parking journeys. No user-approved final product pilot yet.
- No verified numerical DTLA Zone→Policy join rate, legitimate free-parking counts, sensor freshness or 20/20 residential legality audit has been established.
- M1 foundation may proceed without verified rules; M2 published map is evidence-labeled; M3 verified legal claims require actual law/evidence verification.

## Decisions still intentionally deferred
Specific cloud vendor, user auth provider, external reminder channels, production SLOs, rate limits, WebSocket subscription protocol and event retention periods. Choose in the milestone when required with explicit human review.
