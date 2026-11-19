# CurbOS M0-05 — Pilot Shortlist & Sampling Protocol

Date: 2026-11-18
Status: PROVISIONAL — not a verified pilot selection

## Research-supported facts
- LADOT states LA Express Park expanded from Downtown Los Angeles to Westwood Village (2015), Hollywood (2018), and Venice Beach (2019). Source: https://ladot.lacity.gov/projects/parking-la
- Metered inventory: https://data.lacity.org/d/s49e-q6j2 ; last-known occupancy: https://data.lacity.org/d/e7h6-4a3e . Dataset counts/coverage remain UNMEASURED in this execution.
- City StreetsLA posted-sweeping routes layer has polygon geometry and fields including Posted_Day, Posted_Time, Weeks. It is not complete curb-side eligibility: https://services1.arcgis.com/PTh9WC0Sf2WS7AAq/arcgis/rest/services/Posted_Street_Sweeping_Routes_Update/FeatureServer/0

## Preliminary pilot alternatives
| Area | Rationale | Gating unknowns | Status |
|---|---|---|---|
| Westwood Village + nearby LA-city residential blocks | Commercial meters + nearby residential street-parking product use cases | Actual sensor-to-meter overlap, permit/sweeping/sign coverage, geographic boundary | PREFERRED TO AUDIT, not selected |
| Downtown Los Angeles | Original Express Park area and strong meter-focused scenario | Residential free-street relevance, block-specific prohibitions, freshness | BACKUP |
| Hollywood | Express Park and mixed commercial/residential use case | Actual meter sensor overlap, complex restrictions, free legality | BACKUP |
| Venice | Express Park and visitor parking | Exact LA jurisdiction, beach/coastal restrictions, residential legal coverage | BACKUP |

Do not interpret these as measured rankings. Selection requires completed audit.

## Sampling method: 20 actual block-faces
Select block-faces only after authoritative street geometry and jurisdiction are loaded. Maintain unique street-side IDs, spatial coordinates, neighborhood and source IDs. Allocate:
- S1: 5 inside PPD candidate areas
- S2: 5 PPD boundary-adjacent candidate block-faces
- S3: 5 outside PPD but intersecting official sweeping route polygons
- S4: 5 in mixed metered / unmetered areas

Strata may overlap: establish precedence S1>S2>S3>S4 and select unique faces; record the sampling frame and seed to avoid cherry-picking. Sample only within City of Los Angeles. Polygon intersections alone do not establish curb-side posted restrictions.

Per-face required evidence:
- City and street-side geometry; geometric precision and source/version
- Sweeping day/time/weekly rule, mapping confidence, sign evidence
- PPD restrictions and curb-side sign evidence
- Meters / curb colors / driveway / hydrant / access conflicts if known
- For a specified weekday daytime, weekday overnight, and weekend stay, ALLOWED/PROHIBITED/UNKNOWN with reason codes
- Whether FREE is supported by verified pricing and posted restrictions
- Occupancy evidence (should default UNKNOWN absent direct observation)
- reviewer/date and unresolved issues

### What counts as verified
Full-stay legal eligibility should only be ALLOWED with adequate current, spatially matched authoritative rules and documented completeness of material restrictions. No record != no restriction. Photos and third-party map data may help identify gaps but don't automatically confirm official legality.

## Candidate scoring rubric (only after data audit)
- 35% proportion of sample stays with adequately evidenced legality and source attribution
- 20% metered inventory quality/unique-ID spatial mapping
- 20% joined sensor fresh-observation coverage (report denominator, source-specific age)
- 15% manageable jurisdiction / street-side geometric ambiguity
- 10% product suitability for Going Home + Going Out

A score is NOT allowed if key data coverage is unavailable. Never substitute arbitrary values. A jurisdiction or safety blocker overrules numeric ranking.

## Decision gates
- GREEN: core meter inventory validated; a small but meaningful sample of legally verified residential curb stays available; reasonable mapping/sensor provenance; scoped pilot possible.
- AMBER: metered search and rule discovery feasible; residential free legality unproven -> Discovery only.
- RED: source licensing, geometry, or reliable regulation mapping blocks safe public claims -> pause relevant feature or change geography.

## Current evidence status
- Source discovery: PARTIAL COMPLETE
- Meter CSV row audit: PENDING (could not retrieve through current session)
- Occupancy join and timestamp freshness: PENDING
- Residential sample of 20 actual faces: 0/20 VERIFIED
- Pilot decision: PENDING; Westwood is research priority, not GO

## Runbook next actions
1. In a networked development environment execute the existing `curbos_design/m0_meter_audit.py --fetch` utility; preserve raw snapshot date, metadata and output.
2. Aggregate joined space counts and fresh observations by region; use actual coordinates within LA boundaries and official district layers.
3. Obtain authoritative street block-face geometry and district boundaries; create deterministic set of 20 block-faces following the strata.
4. Cross-check official posted sweeping and PPD against current signage and any official block-level restrictions; record reviewer, dates, evidence, and UNKNOWN values.
5. Score four pilot areas using the rubric only with measured values; record GO / AMBER / RED.

## Execution blockers
This session's web browsing fetched dataset metadata but row-level Socrata API requests failed. The local container cannot resolve public internet hosts. Therefore no row-level audit, join rate, or 20-block review is claimed.
