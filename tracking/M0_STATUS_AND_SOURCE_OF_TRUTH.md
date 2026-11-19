# M0 Status & Source of Truth

**Date:** 2026-11-18. This is a consolidated index, not evidence of newly executed full data audits.

| Area | Current status | Best document |
|---|---|---|
| ADR-001–027 | ACCEPTED | `../docs/core/CURBOS_HANDOFF_AND_M0_07_2026-11-18.md` |
| Official source identification | PARTIAL, links/metadata documented | `../docs/core/M0_DATA_FEASIBILITY_PLAN.md` |
| Meter row quality and sensor SpaceID join | NOT MEASURED | `../docs/research/M0_EXECUTION_REPORT_2026-11-17.md` |
| Residential restrictions sources | DISCOVERED, completeness unverified | `../docs/research/M0_04_RESIDENTIAL_CURB_FEASIBILITY_2026-11-18.md` |
| DTLA CDS Policies | Previously inspected, parser variability noted | `../docs/research/M0_06_CODE_THE_CURB_DISCOVERY_2026-11-18.md` |
| Full DTLA Zones → Policies join | NOT MEASURED; requires full raw JSON | `../tools/m0/m0_08_cds_audit.py` |
| Actual block-face inspections | 0 / 20 verified | `../tools/m0/M0_04_BLOCK_FACE_AUDIT_TEMPLATE.csv` |
| Pilot selection | PENDING: DTLA prioritized for data audit, Westwood for comparative product research | `../docs/research/M0_06_CODE_THE_CURB_DISCOVERY_2026-11-18.md` |
| M1–M8 | PLANNED, not implemented | `../docs/design/DESIGN_FREEZE_AND_IMPLEMENTATION_READINESS.md` |

## Current minimum next actions
1. Obtain the unchanged official DTLA Zones and Policies JSON files; run `tools/m0/m0_08_cds_audit.py` with real data.
2. Obtain authoritative metered+occupancy CSVs; run `tools/m0/m0_meter_audit.py` and retain timestamps for freshness.
3. Audit 20 *actual* curb block faces with source and reviewer evidence, not placeholders.
4. Use results to choose the first published feature coverage and pilot neighborhood.

## Supersession clarifications
- Westwood was proposed *before* discovery of detailed downtown curb data. DTLA now has priority for M0 data validation; this is not a verified free-parking pilot decision.
- ADR-027 **WebSocket** is final accepted, replacing earlier discussion of SSE.
- M0 reports that describe an audit utility as 'completed' do not imply an official dataset was retrieved or its join measured.
- All source numbers visible on government portals and in official reports remain **published source claims**, not measurements made by this audit.

## v1.2 update (2026-11-18)
- ADR-028 **ACCEPTED**: validated staging + atomic publication (see `../docs/adr/ADR-028_VALIDATED_STAGING_ATOMIC_PUBLICATION.md`).
- Final engineering review complete for M1 planning; first Codex PR prompts authored **but not executed**.
- M0 row-level measurement, DTLA zone/policy joins and 20 block-face checks remain PENDING.
- Canonical source of truth now `../docs/architecture/DECISION_REGISTER.md` + `../AGENTS.md`.
