# CurbOS M0-01–03 — Execution Report

**Date:** 2026-11-17  
**Scope:** source catalog, metered inventory audit setup, sensor join/freshness audit setup.  
**Status:** **Official metadata VERIFIED; row-level audit BLOCKED by source connectivity in this execution environment.** Do not report synthetic fixture results as real LADOT measurements.

## Evidence obtained from official publication pages

| Source | Dataset ID | Official portal metadata | Update / semantics | Status |
|---|---|---|---|---|
| LADOT Metered Parking Inventory & Policies | `s49e-q6j2` | 35,027 records shown in derived official parking map on Nov. 16; official dataset rounds to 35K; 7 fields: `spaceid`, `blockface`, `metertype`, `ratetype`, `raterange`, `timelimit`, `latlng`. | 2026-11-16 data update; publisher cautions posted signs govern. | Metadata verified; individual rows not retrieved. |
| LADOT Parking Meter Occupancy | `e7h6-4a3e` | 3,673 records; fields: `spaceid`, `eventtime`, `occupancystate`. | 2026-11-17 data update; `eventtime` is UTC observation transaction timestamp, values are last-known state. | Metadata verified; per-row ages not retrieved. |
| LADOT Parking Meter Occupancy Archive | `cj8s-ivry` | Historical monthly archive and large files, listed through LA Express Park / Data.gov. | Not a substitute for current state. | Catalog lead verified; no historic rows fetched. |
| LADOT Parking Calendar Sign Locations | `jp2s-nfz4` | 4 fields: `blockface`, `status`, `signcount`, `the_geom`. | Data last updated Sep. 5, 2019 per portal. | Possible auxiliary GIS source only; no comprehensive parking-rule claims. |

**Official references:**
- https://data.lacity.org/Transportation/LADOT-Metered-Parking-Inventory-Policies/s49e-q6j2/about_data
- https://data.lacity.org/Transportation/LADOT-Parking-Meter-Location-Map/epux-nymu
- https://data.lacity.org/Transportation/LADOT-Parking-Meter-Occupancy/e7h6-4a3e/data
- https://www.laexpresspark.org/la-city-open-data/
- https://data.lacity.org/Transportation/LADOT-Parking-Calendar-Sign-Locations/jp2s-nfz4
- https://data.lacity.org/terms-of-use
- https://dev.socrata.com/docs/endpoints

## Actual execution and blockers

1. Inspected official dataset portal metadata and source documentation online.
2. Attempted bounded `https://data.lacity.org/resource/e7h6-4a3e.json?...` and inventory API requests via web fetch; API data could not be opened in the available web environment.
3. Attempted direct HTTPS access in the local execution container; DNS resolution to `data.lacity.org` failed. This is **an environment access limitation, not proof the Socrata API is down**.
4. Implemented `m0_meter_audit.py`, a **standalone research script**, to fetch bounded CSV through official Socrata endpoints or read locally supplied CSVs and compute ID integrity, regional coordinate sanity, join rates and observation age distributions.
5. Ran the script against two explicitly synthetic test fixture files. It executed successfully and produced expected 1/2 join (50%) and a sample age distribution. **Those fixture percentages have no empirical bearing on LA parking.**

## What is NOT verified yet

- Number of unique IDs in either dataset; malformed IDs, coordinate validity and City of LA boundary membership.
- Actual sensor/inventory join rate or sensor coverage rate.
- Per-record timestamp ages; stale/fresh percentages; occupancy state distribution.
- Full-stay legal eligibility or actual rates from the published 7-column inventory.
- Production fitness, licensing obligations beyond per-page published labels, and geographic pilot selection.

## Reproduction instructions (network-enabled environment)

```bash
python3 tools/m0/m0_meter_audit.py --fetch \
  --inventory inventory.csv --occupancy occupancy.csv \
  --inventory-limit 40000 --occupancy-limit 10000 \
  --output m0_audit_results.json
```

The script sets its snapshot reference time after download; for a rigorous snapshot, archive start and end times and ideally fetch both sources in one short capture window. The `audit_mode` value is not proof of completeness. Compare fetched row counts to contemporaneous published counts and verify no pagination/truncation. For high-confidence joins, use full dataset or a geographic subset that includes ALL relevant inventory IDs; do not compute citywide coverage from an arbitrary 1,000-row sample.

When APIs cannot be fetched, export both official CSVs manually using the portal and run:

```bash
python3 tools/m0/m0_meter_audit.py \
  --inventory path/to/ladot_inventory.csv \
  --occupancy path/to/ladot_occupancy.csv \
  --reference-time 2026-11-17T09:05:00Z \
  --output m0_audit_results.json
```

Replace the reference timestamp with the actual UTC collection instant. Avoid processing older downloaded files using an unrelated current reference timestamp.

## M0 gate assessment

| Work package | Result |
|---|---|
| M0-01: official source fields / owners / update semantics | **Partial pass** (datasets and schemas verified; detailed licensing and endpoint row access pending) |
| M0-02: inventory row-level quality | **Not measured** (reproducible audit tool created/tested) |
| M0-03: sensor join and freshness | **Not measured** (reproducible audit tool created/tested) |
| M0-04: free residential legality | **Not started** |
| M0-05: pilot selection | **Not started** |

**Decision:** HOLD pilot selection and any numerical sensor-coverage or real-time availability claims until actual source rows are downloaded and checked. Continue pilot scope and data-source validation; do not treat 3,673 / 35,027 (~10.5%) as a measured join coverage rate.
