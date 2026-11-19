# ADR-028 — Validated Staging + Atomic Publication

**Status:** ACCEPTED by user, 2026-11-18. **Supersedes:** the proposal in `docs/design/DESIGN_FREEZE_AND_IMPLEMENTATION_READINESS.md` section 7.

## Context
LADOT CDS Zones and Policies may be interdependent and versioned; a partial import can mix newly read geometry with old rules. Incorrectly presenting partial imports as authoritative may imply unsafe parking legality.

## Decision
1. Store an **immutable raw source snapshot** with URI, license/attribution, retrieved timestamp, source-as-of time if known, SHA-256, byte size, spatial coverage, parser version and input format.
2. Parse and normalize into a **staging batch** isolated from public queries. Reject malformed references, invalid topology/geometry, duplicate source-scoped IDs, and unhandled policy types, or explicitly record unusable rows without publishing them as eligible. Validate every referenced policy and source-specific precedence semantics.
3. Publish a **coherent, versioned zone-and-policy dataset** via a PostgreSQL atomic publication boundary (e.g., version pointer advanced in one transaction after validated rows exist). Reads may finish on old version; new reads use the new version, never a half-published mix. Version consistency must be enforced on queries.
4. A failed import leaves the previous published version active and auditably records the failure. Rollback changes published version pointer only after validation; retain provenance.
5. **Publication != legal verification**: `rate=0`, absent red-curb feature, `undesignated`, and unmatched regulations never imply free or allowed. Verified legal recommendations require a separate evidence completeness gate for the entire requested stay.
6. External provider IDs map through source-scoped stable identity; geometry version changes may invalidate spatial observations tied to older geometry.

## Scope / sequencing
- M0: audit snapshot, report metrics; can be offline/research only.
- M1: prepare migrations/tooling foundations, **do not create a full publishing pipeline**.
- M2: implement real staged import, validation, atomic publication and rollback test as a bounded vertical slice.

## Required acceptance tests (M2)
- Malformed Zones or missing referenced Policy -> no partial publication.
- Crash after staging but before pointer switch -> old version remains active.
- Parallel readers get internally coherent version(s), not mixed geometry/rules.
- Re-import identical snapshot is idempotent or explicitly versioned without duplication.
- Source geometry changes cannot silently reuse stale occupancy observations.
- Unknown/unverified remains discovery-only; proof of legal allowance requires separate rules review.

## Tradeoff
More storage and data-validation work than direct import, but avoids mixed-version legal claims without needing a fully historical data platform or microservices.
