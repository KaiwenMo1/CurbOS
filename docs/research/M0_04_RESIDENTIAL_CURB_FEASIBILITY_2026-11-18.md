# CurbOS M0-04 — Residential Curb Feasibility (Initial Research)

Date: 2026-11-18
Status: Source discovery complete (partial); row-level coverage, topology, field verification and pilot selection still pending.

## Executive finding
Los Angeles provides several geospatial government datasets useful for discovering street-sweeping rules, preferential parking districts, road centerlines, and some red-curb work records. None of the sources inspected alone establishes a complete, current curb-side map of *legally free* parking or real-time vacancy. Do not infer permission from an absence of records.

## Official sources verified

1. StreetsLA Posted Street Sweeping Routes, ArcGIS FeatureServer layer `Biweekly_Posted_Routes_20261019` (0): https://services1.arcgis.com/PTh9WC0Sf2WS7AAq/arcgis/rest/services/Posted_Street_Sweeping_Routes_Update/FeatureServer/0 . The layer reports last edited October 19, 2026; geometry is Polygon, with Route, Posted_Time, Posted_Day, Weeks, Route_Type, and other fields. These represent sweeping-related areas/routes, not proof of the precise curb side or complete parking eligibility.
2. StreetsLA official sweeping service and reminder information: https://streets.lacity.gov/services/street-sweeping . Signage and schedules need local verification.
3. LADOT Preferential Parking Districts (PPD) open data: https://data.lacity.org/d/2ckn-xmjp ; additional city GIS layer https://maps.lacity.org/arcgis/rest/services/Permits/BOE_Permits_Geocoder/MapServer/403 . District boundaries do not themselves resolve each block face's posted restrictions or exemptions.
4. LADOT Red Curb ArcGIS Hub: https://hub.arcgis.com/datasets/lahub::ladot-red-curb/about . Described as an inventory of work completed under the red-curb program, not a comprehensive inventory of all active curb-color restrictions.
5. City street centerline layer: https://maps.lacity.org/arcgis/rest/services/Core/Street_Information/MapServer/9 . Centerlines are not accurately positioned measured curb lines.
6. LADOT Parking in LA: https://ladot.lacity.gov/projects/parking-la . Official description of posted PPD restrictions and permits.
7. LADOT Parking Restrictions: https://ladotparking.org/parking-meters/parking-restrictions-holiday-parking/ . Additional city/state restrictions apply beyond GIS layers.
8. City boundary: https://catalog.data.gov/dataset/city-boundary-of-los-angeles . Use to avoid mistakenly combining neighboring jurisdiction rules.

Historical note only (not current proof): LADOT's 2016 Code the Curb memo described a lack of a complete citywide unm​​etered curb rule inventory at that time: https://cityclerk.lacity.org/onlinedocs/2015/15-1450-S2_rpt_DOT_03-17-2016.pdf . Current completeness must be independently verified.

## Evidence coverage classification for each sampled block face
- GEOMETRY_ONLY: street centerline / approximate block side exists, precise curb extent unknown.
- SWEEPING_AREA: associated sweeping polygon and schedule fields, curb-side matching unverified.
- PPD_POSSIBLE: district boundary overlap, posted sign and block-specific restriction unverified.
- RED_CURB_EVIDENCE: some mapped work record, current painted curb extent unverified.
- VERIFIED_RULES: only after sufficient current authoritative rule evidence and applicable location/time coverage, with documented review.
- LEGAL_ELIGIBILITY_UNKNOWN: default for residential free curb until all material restrictions for requested interval can be resolved.
- OCCUPANCY_UNKNOWN: default without reliable recent direct observation; user feedback about neighborhood difficulty is not a precise vacancy measurement.

## M0-04 audit procedure (20 block faces)
1. Select 20 block faces in City of Los Angeles jurisdiction, stratified across residential blocks with vs without PPD overlap, sweeping polygons, and nearby metered areas; record sampling rationale and avoid cherry-picking easy blocks.
2. Record stable reference, jurisdiction, street side, approximate geometry, and source-specific version/time for each face.
3. Match candidate sweeping layer and PPD polygons; inspect potential spatial ambiguity (polygon coverage, wrong street side, multiple overlaps).
4. Review official address-level map and available sign/curb evidence; distinguish published schedule from legal restriction and flag missing signage/coverage.
5. Explicitly account for driveways, hydrants, intersections, temporary restrictions, other curb colors, vehicle class, and relevant legal rules; if not established, mark unknown.
6. Have a separate human verification pass for the 20-face sample, subject to legal and safety constraints. Do not claim on-site verification until done.
7. Record for each face: geometry confidence, rule coverage by time, whether 'free' is proved for at least one specified representative stay, and whether any observation supports vacancy.
8. Report denominators, percentage complete, error modes, and inter-reviewer disagreements. No inventing data.

Suggested sample strata (not audited locations): 5 inside apparent PPD, 5 near PPD boundaries, 5 outside PPD but within sweeping areas, 5 near mixed metered/residential streets. Validate distinct jurisdiction and street-side identities before sampling.

## Go / no-go criteria for residential recommendation
- **GO for a particular curb+time window:** evidence supports full time-of-stay legality, source attribution and spatial precision adequate; report occupancy/fit separately.
- **DISCOVERY ONLY:** plausible curb geometry exists, but rule coverage, signed restrictions, or curb precision remain uncertain.
- **DO NOT DISPLAY AS PARKABLE:** explicit prohibition, inaccessible geometry or severe mapping conflict.

## Status and gaps
- Source existence/metadata: Verified for the links above.
- Programmatic row-level completeness / GIS join metrics: NOT MEASURED.
- Twenty real block faces reviewed: NOT STARTED.
- Official signed rule completeness: NOT ESTABLISHED.
- Live free residential vacancy data: NOT ESTABLISHED.
- Residential pilot neighborhood: NOT YET SELECTED.

## Recommended next execution
First execute the 20-face sample audit, in parallel with the metered SpaceID and sensor freshness audit. Then score potential pilot regions using verified legal coverage, metered coverage, data update quality, and jurisdiction simplicity. Do not mark residential curbs as verified simply because no restriction is found in public GIS.
