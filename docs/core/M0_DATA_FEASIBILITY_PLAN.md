# CurbOS — M0 Data Feasibility Plan

**Status:** Ready for execution, no implementation code authorized yet  
**Date:** 2026-11-17  
**Objective:** Prove that at least one small City of Los Angeles pilot can support an honest, useful street-parking product before committing to full-stack development. Distinguish **metered inventory**, **meter occupancy**, **verified parking regulation**, and **free residential discovery**.

## 1. Initial verified leads — research, not imported data

| Dataset/source | Evidence available from official pages | M0 must verify |
|---|---|---|
| LADOT Metered Parking Inventory (`s49e-q6j2`) | ~35K rows; SpaceID, BlockFace, MeterType, RateType/RateRange, time limit, LatLng. Metadata updated Nov 16, 2026. Official disclaimer: signs govern and may differ. | Retrieve sample; check IDs, coords, empty/duplicate rows, semantics of rate/hour restrictions and time limit; verify terms for retention/reuse |
| LADOT Meter Occupancy (`e7h6-4a3e`) | Last known sensor occupancy; portal currently shows 3,673 rows, SpaceID/EventTime_UTC/OccupancyState. | Join to inventory by SpaceID; inspect age distribution and unknown/missing values; distinguish current feed refresh from actual observation time |
| Meter Occupancy Archive (`cj8s-ivry`) | Historical activity, monthly archive of previous ~36 months, files commonly >300MB; delayed publication. | Can access subset/paged data; retention/size/licensing; usable labels for event/prediction tests; avoid whole export early |
| StreetsLA Street Sweeping | Official sweeping schedules/map and sign caveats; >4,700 curb miles posted for regular routes. | Determine whether machine-readable per-block geometry + times can be licensed/accessed; validate 1st/3rd or 2nd/4th weekly patterns and exceptions |
| LADOT Preferential/Overnight/Oversize Parking | Official definitions and policies (PPD/OPD/OVRA). | Locate authoritative machine-readable district boundaries, actual posted sign applicability, and permit exceptions |
| LA GeoHub | Public GIS discovery/download platform. | Find side-specific curb, restrictions, road, red curb, driveway, hydrant layers; verify positional accuracy, freshness and individual licenses |
| Community photos / field verification | Not an official comprehensive data feed. | Small, permission-conscious manually checked pilot dataset; date, source, exact covered curb interval, rule completeness and provenance |

**Important:** City of Los Angeles ≠ Santa Monica or other neighboring municipalities; pilot city must be specified and jurisdiction validated.

Sources: https://data.lacity.org/d/s49e-q6j2 ; https://data.lacity.org/d/e7h6-4a3e ; https://data.lacity.org/d/cj8s-ivry ; https://streets.lacity.gov/services/street-sweeping ; https://ladot.lacity.gov/projects/parking-la ; https://geohub.lacity.org/ ; https://data.lacity.org/terms-of-use .

## 2. M0 questions and measurable outputs

**Q1 — What is accessible?** For each source record owner, endpoint, public access/auth, data schema, timestamp semantics, refresh policy, download limits, licensing/attribution and quality caveats. Evidence: `source_catalog.csv` or document.

**Q2 — How much is actually geographically usable?** Examine coordinate accuracy, resource IDs, duplicate IDs, missing latitude/longitude, invalid/out-of-city geometry, and visual alignment with actual roadway. Report sample sizes and denominators.

**Q3 — Can meter occupancy join to inventory?** Perform `SpaceID` joins; measure raw matched ratio = joined unique SpaceIDs / occupancy unique SpaceIDs and sensor coverage = joined unique SpaceIDs / inventoried unique SpaceIDs. Audit duplicates and mismatches. Never use the portal row count itself as coverage ratio.

**Q4 — How fresh is occupancy?** Compute age = ingestion/reference time − per-record `EventTime_UTC`, report p50/p90/p95/max age and fraction under multiple **illustrative** windows (5, 15, 60 min); choose eventual production expiry only from actual provider behavior.

**Q5 — Can residential legality be verified?** For sampled block faces, identify sources for curb geometry, posted signs, cleaning, permit districts, timed restrictions, curb colors, driveway and other permanent restrictions. Grade `VERIFIED_FULL_STAY`, `PARTIAL`, `UNKNOWN`, `CONFLICTING`. Without verified completeness do not recommend legal parking.

**Q6 — Can we prove a small pilot useful?** Compare candidate neighborhoods within City of LA based on metered density, sensor join coverage, residential interest, regulatory evidence, and feasible field verification. Choose one constrained pilot; document reasons and exclusions.

**Q7 — What can be demonstrated truthfully?** Explicitly distinguish real metered resources, last-known sensor history, verified local residential rules, unverified curb discovery, and isolated simulated events.

## 3. Execution steps

### M0.1 Source catalog and terms
- Verify official links and API access with small bounded samples, not full downloads.
- Record additional license terms, retention, required attribution and restrictions per source. LA city portal terms deny completeness and accuracy guarantees and allow additional dataset terms.
- Record attributions and posted-sign disclaimer for user-facing UI.

**Exit:** source catalog with source URLs, ownership, row/field schema, licensing and update semantics.

### M0.2 Metered inventory quality audit
- Obtain a representative sample of metered records; check geometry CRS, bounded area, ID uniqueness, missing data, meter-type distribution, rate/time-limit ambiguity.
- Geographically inspect 20–50 records across selected pilot neighborhoods. Record coordinate precision and whether point corresponds to actual curb side.

**Exit:** reproducible profile and sample map; limitations documented.

### M0.3 Sensor join and freshness
- Join sample/full bounded inventory to occupancy by SpaceID; measure unique join rates and per-record timestamp ages. Test whether repeating an unchanged last-known observation would falsely refresh freshness.
- Compare portal update time to individual observation times. Do not claim real-time vacancy unless age and source semantics support it.

**Exit:** join audit, freshness distribution, documented source-specific expiry policy candidate.

### M0.4 Free-residential curb feasibility spike
- Identify authoritative curb-related layers and machine-readable restrictions. Validate at least **20 sampled block faces** covering different combinations of sweeping, permit, signs and ambiguous areas (sample target, not existing completed work).
- For each: source-supported curb geometry, source authority, full-stay rules, posted-sign/temporary-ban gaps, confidence and unresolved questions.
- If no reliable free-residential rules exist at the chosen block, keep it in `Discovery`, not verified recommendations.

**Exit:** per-block evidence ledger and gap analysis. No blanket claim of verified residential legality.

### M0.5 Pilot scoring and go/no-go
- Score candidate *City of LA* neighborhoods based on usable official metered inventory, sensor recency coverage, mapped residential blocks, reliable rule evidence, manageable geography, and feasibility of safe field verification.
- Choose primary pilot area, optional comparison area, coverage boundary polygon, and explicit non-supported regions.

**Exit:** pilot proposal, coverage map, product honesty statement and data-quality gates.

## 4. Proposed M0 acceptance criteria

**Must pass:**
1. At least 3 official source families assessed (meter inventory, occupancy, and one or more regulations/GIS authorities), with stable URLs and field/terms documentation.
2. Reproducible sample extraction and quality profiling (not necessarily a production ETL yet).
3. Matched/unique `SpaceID` sensor join results, including denominators and observed timestamp age distribution.
4. One selected City of LA pilot geography with clear inclusion/exclusion and known coverage limitations.
5. Residential sign/rule verification audit for a defined sample of block faces; *if none passes full-stay verification*, result reported as a blocker rather than fabricated success.
6. Source provenance and a truthful UI-label policy for observed, unknown, unverified and simulated data.
7. A documented recommendation on whether to proceed to M1–M4 unchanged, narrow residential scope, or prioritize metered streets first.

**Stretch, not required:** verified free residential rule coverage above a predetermined threshold. Do not invent a percentage before a sample and full-stay legal criteria are agreed.

## 5. Metrics to report

| Metric | Denominator / caution |
|---|---|
| Inventory valid-geocoordinate rate | inventory unique IDs sampled |
| Occupancy join rate | occupancy unique SpaceIDs |
| Sensor coverage rate | inventory unique SpaceIDs within pilot |
| Fresh reading share | joined sensor IDs, provider-specific freshness threshold |
| Residential complete-rule share | audited sampled block faces; sample is not citywide statistical estimate |
| Prohibition/permit ambiguity share | audited sampled block faces |
| Routing access-point feasibility | sampled candidate curbs |
| Dataset license reviewed | each dataset independently, not blanket city portal permission |

## 6. Risk-based go/no-go pathways

**GREEN — Hybrid pilot:** Some real metered inventory with usable last-known occupancy and a small verified residential subset. Ship metered + verified residential recommendations, unverified discovery with explicit warnings.

**AMBER — Metered-first pilot:** Metered inventory usable but residential full-stay legality unavailable. Build real metered product and transparent residential discovery; do not claim verified free residential recommendations.

**RED — Data blocker:** Neither verified street rules nor trustworthy meter-resource mappings for pilot. Reassess pilot geography, authority, source permissions or product claims before full build. Continue infrastructure spikes only if their value independent of inaccurate claims is clear.

## 7. Data safety and field validation

- Respect posted signs and legal restrictions; project is informational, not a legal guarantee.
- No raw personal driving routes or residential parking history without explicit consent.
- Human audits should not infer precise parking-free intervals from rough imagery.
- Do not mass-load third-party maps or images in violation of license/terms.
- Simulation uses separate DB/Redis and is clearly labeled; never use synthetic observations to report real-world model accuracy.
- Historical archive is large; avoid downloading entire archive before checking need, disk constraints and source terms.

## 8. Proposed M0 work packages for later Codex prompts (not yet implementation)

- **M0-01 Source catalog:** repository-ready structured source documentation, attributed links, license review checklist.
- **M0-02 Inventory profiler:** sampled LADOT inventory audit with reproducible query and non-sensitive output.
- **M0-03 Sensor join profiler:** SpaceID join and timestamp freshness report.
- **M0-04 Regulations audit:** source search and sampled per-block evidence matrix.
- **M0-05 Pilot selection memo:** score areas against verified metrics; honest coverage and go/no-go.

Each future PR should have bounded sample inputs, no secrets, unit/integration quality checks where appropriate, and exact execution instructions. M0 research first, coding only after implementation prompts are explicitly approved.

## 9. Preliminary source facts (as surfaced 2026-11-17)

- Official metered inventory page reports ~35K rows and 7 listed columns, last updated Nov 16, 2026. The description mentions more metered policy information than the 7 literal column names; validate before treating as structured schedule.
- Official occupancy page reports 3,673 last-known sensor records with 3 columns, last dataset update Nov 17, 2026. This count does not establish all are fresh.
- StreetsLA sweeping describes >4,700 posted sweeping curb miles and biweekly scheduled routes. A public viewer ≠ machine-readable complete legal rules.
- LA City permit classes require conditions and signs; PPD/OPD/OVRA details must be inspected for exact restrictions.
- LA City Open Data portal terms do not warrant completeness or suitability; source-level terms should be checked before reuse.
