# CurbOS M0-06 — Code the Curb Data Discovery and Revised Pilot Decision

Date: 2026-11-18
Status: **SOURCE FILE VERIFIED / ROW-LEVEL ZONE AUDIT PENDING**
Scope: research and feasibility; **no implementation code**.

## 1. Material finding
LADOT's 2026 *Code the Curb* Downtown pilot digitized **22,726 curb zones, 11,778 curb objects and 315 unique curb policies** across **5.9 square miles / over 200 curb miles**, according to the USDOT implementation report. These figures describe the official project's output, **not a fresh count we have independently computed**.

- USDOT project report: https://www.transportation.gov/media/6831
- USDOT supporting dataset: https://rosap.ntl.bts.gov/view/dot/94217
- LADOT project page: https://ladot.lacity.gov/codethecurb
- OMF Curb Data Specification: https://github.com/openmobilityfoundation/curb-data-specification/blob/main/curbs/README.md

## 2. Concrete data files found
On the USDOT supporting dataset page, its **Supporting Files** section lists:

- **LADOT Policies JSON:** https://rosap.ntl.bts.gov/view/dot/94217/dot_94217_DS11.json (web reader successfully opened this file)
- **LADOT Zones JSON:** https://rosap.ntl.bts.gov/view/dot/94217/dot_94217_DS13.json (URL identified; web reader refused payload above size threshold, not parsed or counted)
- Policies, Zones and Curb Objects **data dictionaries** are separately downloadable from the USDOT page.
- Dataset page lists Creative Commons Attribution 4.0; preserve the full attribution and verify individual-file reuse terms before public deployment.

The Policies JSON inspected in web browser includes a `version`, `time_zone`, `last_updated`, and policy entries with `curb_policy_id`, `priority`, `time_spans` (days of week, local time), `rules` (activity, user class, rates), and source fields. Examples include `no stopping`, `no standing`, `loading`, `travel`, and `undesignated` activities. **Do not interpret zero numeric `rate` or `undesignated` as proof of free, legal automobile parking.** Certain user class fields vary in representation (scalar vs array), which is a parser/data-quality risk. Verify policy-zone joining keys and precedence from raw datasets and CDS standard.

The JSON's publication timestamp may differ from today's date. The source is a **snapshot**, not evidence that every curb restriction remains current as of November 2026.

## 3. Crucial technical warning from USDOT
The implementation evaluation explicitly reports: **IPS metered parking sensors generally stop generating new events after paid hours end (e.g., 8:00 PM)**. Consequently, an old 'vacant' reading cannot be treated as trustworthy overnight occupancy. The report also warns that some smart cameras missed activity outside their field of view and citation geolocation mapped to nearby curb segments rather than exact parking locations.

Relevant report section: 3.1 Evaluation Metrics and Data Collection, paragraphs following Table 3.

## 4. Updated pilot decision
Previous preference was Westwood Village, based on a plausible mixed metered/residential product scenario but no verified residential rule coverage.

**New priority for M0 field and data audits: Downtown Los Angeles (DTLA), first.** Reason: a concrete, published CDS-format curb inventory with zone geometry and policy files exists there. Westwood remains a valuable **second geography / product-validity comparison** because of the residential street-parking use case, but there is not yet evidence of equivalent granular curb regulation coverage.

This is a *research priority change*, **not an unconditional GO for legal recommendations**. DTLA may be skewed toward paid, loading, restricted, or commercial curb zones; residential free street parking value remains to be measured. CurbOS remains street-parking-first and not automatically 'DTLA only'.

## 5. Revised M0 gates (measured, not guessed)

### M0-06A: official files access & integrity
- Download Policies and Zones snapshots with exact source URL, access time, SHA-256, source `last_updated`, license and attribution.
- Validate JSON parse and schema (`data`, `policies`, `zones`) and record unknown/custom fields, invalid geometry, duplicate IDs.
- Measure zones↔policies join coverage and find unmapped/unknown activities.
- No synthetic rows in production counts.

### M0-06B: determine **verified free curb** candidates
- For a reproducible sample of 20 real DTLA block faces, evaluate multiple full stay intervals and vehicle types.
- Distinguish rules that indicate paid, loading, restricted, not-designated, absent, conflicting, and explicitly free legal parking.
- Validate geometry precision, time zone, current sign coverage, and completeness. Rules supporting *some restrictions* alone do not prove full legal eligibility.

### M0-06C: occupancy and time
- Join LADOT metered inventory and last-known occupancy on source-scoped `SpaceID` and validate join rate and observation age.
- Split occupancy freshness statistics by metered operating hours versus overnight; do not generalize daytime sensor freshness to nighttime.
- Report actual sample sizes, denominators, missing data and timestamps.

### M0-06D: pilot go/no-go
- GREEN: enough verified, usable curb policies and geometry for a narrowly defined parking search, with known coverage limitations.
- AMBER: launch evidence-aware discovery + verified subsets; no generic free-parking guarantees.
- RED: policy mapping, geometry, licensing, or critical safety holes prevent public assertions.

## 6. Recommended immediate execution order
1. Download and inspect published DTLA Policies/ Zones JSON in a network-enabled development environment.
2. Produce empirical zone/policy coverage and classify policy actions without inferring permissibility from absent rules.
3. Audit 20 actual DTLA block faces and compare with representative Westwood blocks.
4. Audit sensor freshness and join rates for metered spaces, explicitly separate after-hours.
5. Select the smallest verified subregion for M1, not the entire city.

## 7. Current verified vs pending

VERIFIED via official web pages:
- Published USDOT Stage 1 summary counts and scope.
- Public supporting dataset lists policies, zones and dictionaries.
- Policies JSON is reachable and exhibits detailed CDS-like scheduling/rules.
- Official report notes paid-hours sensor event cutoff.

NOT VERIFIED:
- Entire zones JSON contents and actual distinct row count in snapshot.
- Measured policy-to-zone join rate.
- Number of residential free and fully legal curb zones.
- Source freshness by zone, current signage, and real-time vacancies.
- LADOT metered inventory ↔ occupancy row-level join and fresh-event distribution.
- 20 actual block faces: still 0 reviewed.

**Do not mark M0 complete until the pending measurements are executed.**
