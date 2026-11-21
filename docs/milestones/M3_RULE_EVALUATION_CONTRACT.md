# M3 internal rule evaluation contract

**Proposed.** Design sketches in this document describe types and behavior for review. All rule examples and fixtures are synthetic. [Design specification and decision register](M3_DESIGN_SPEC.md)

## Typed domain boundary

Proposed pure Go entry point `Evaluate(input EvaluationInput, snapshot Snapshot) Result`. The caller supplies validated evidence, an explicit assessment instant, and a content-identified timezone location loaded from pinned bytes. The engine checks the relationships before use. It never reads a wall clock, the database, the network or the OS timezone. Input size and interval limits bound the work in the pure engine. The later application use case owns context, snapshot loading, revocation check and audit authorization.

The following Go sketches live only in this Markdown. IDs and enums are distinct types. Pointer fields denote explicit unknown or inapplicability under the listed invariants.

```go
type Stay struct { Start, End time.Time }
type ZoneKey struct {
    Dataset DatasetID
    Release ReleaseID
    SourceZone SourceZoneID
}
type Target struct {
    Kind TargetKind
    Resource *ResourceID
    Zone *ZoneKey // dataset, release and source Zone ID
    Geometry GeometryRevision // digest and oriented segment or block-face revision
    Side StreetSide             // LEFT, RIGHT or UNKNOWN on the oriented segment
    Jurisdiction JurisdictionID
}
type Vehicle struct {
    Class VehicleClass
    Dimensions *VehicleDimensions // only for supported legal attributes
    Attributes []AttributeFact   // known value or UNKNOWN per typed attribute
}
type Permit struct {
    State PermitState // VERIFIED, VERIFIED_ABSENT, UNKNOWN
    Class PermitClass
    Issuer JurisdictionID
    Scope PermitScopeKey
    ValidFor *Stay
    Evidence *EvidenceID
}
type EvaluationInput struct {
    Stay Stay
    Target Target
    Vehicle Vehicle
    Permits []Permit
    PermitInventoryComplete bool
    AssessAt time.Time
}
type NormalizedRule struct {
    ID RuleID
    Version RuleVersion
    Target TargetBindingID
    Authority AuthorityKey // jurisdiction, issuer and authority class
    Effect RuleEffect
    Applicability Applicability // vehicle, activity, permits and typed exemptions
    Effective EffectivePeriod // reviewed instant or jurisdiction-local date bounds
    Absolute *Stay
    Civil *CivilSchedule
    Maximum *MaximumStay // elapsed cap and reviewed accumulation/reset semantics
    Exceptions []RuleID
    Evidence []EvidenceID
}
type CivilSchedule struct {
    Weekdays []time.Weekday
    Window CivilWindow // local times with an explicit all-day marker
    Season *LocalDateRange
    Exceptions []DateException // local dates and explicit add/remove/replace
}
type EvidenceRecord struct {
    ID EvidenceID
    Origin ArtifactRecordKey // dataset, batch, artifact, digest and locator
    Authority AuthorityKey
    ObservedAt *time.Time
    SourceAsOf *time.Time
    Effective EffectivePeriod
    Parse ParseStatus
    Rights RightsVersion
}
type ReviewDecision struct {
    Version ApprovalVersion
    Reviewer ReviewerID
    Authority ReviewerAuthorityKey
    Independence IndependenceStatus
    Subject Digest // exact evidence and target/coverage binding
    Decision ReviewStatus
    ValidFor Stay
    Verification VerificationRecordID
}
type Snapshot struct {
    Key SnapshotKey
    Jurisdiction JurisdictionProfile
    Rules []NormalizedRule
    Evidence []EvidenceRecord
    Approvals []ReviewDecision
    Coverage []CoverageReview
}
type Result struct {
    Status EvaluationStatus
    Legal LegalOutcome
    Reasons []Reason
    Snapshot *SnapshotKey
    Purpose EvaluationPurpose
    UseAuthorization UseAuthorization // status and observed-at instant, when checked
    Cost CostAssessment
    Fit FitAssessment
    Occupancy OccupancyAssessment
    Arrival AvailabilityAssessment
}
```

`Target` has exactly one key for the chosen kind. A missing or ambiguous binding is a completed unknown when the evidence loader establishes the lookup outcome. A malformed key or supplied tuple is invalid input. An unverified side never matches. A positive side or vehicle determination applies only to the facts supplied and verified for the stated stay. Permits carry applicability and validity without raw permit numbers or personal documents. Verified absence requires an explicitly complete relevant inventory. A missing permit or attribute field is unknown unless a separate verified fact establishes absence. `VERIFIED` permit facts require evidence usable at assessment, valid for the interval and applicable to the issuing jurisdiction, class and scope. Exemptions are separate typed, evidenced applicability conditions.

`NormalizedRule` contains a rule/version key, the exact target binding, jurisdiction and authority class, one effect, effective interval and typed applicability. Effects for the proposal are `PERMISSION`, `PROHIBITION`, `PERMIT_ONLY` and `MAX_STAY`. Typed qualifiers cover vehicle, verified permits, time-restricted activities and exemption conditions. A time-restricted activity becomes a parking effect only under a reviewed mapping of its effect on the requested activity and vehicle. Exactly one absolute or civil schedule is present. `Maximum` is required for `MAX_STAY` and absent for other effects. A conditional or unsupported construct cannot be coerced into an unconditional effect.

`EvidenceRecord` keeps dataset, batch, artifact digest and record locator, source authority, rights and separate `ObservedAt`, `SourceAsOf` and legal effective period. It carries structural parse status separately from immutable, independently verified `ReviewDecision` records. Review records bind reviewer identity and authority, independence, exact digests, covered target/windows and effective validity. A separately retained revocation version records later changes in authorization. `CoverageReview` is keyed to exact target, resource/geometry, jurisdiction, vehicle/permit facts and required authority and evidence layers. It declares coverage and exclusions per interval with evidence and review IDs. Required layers include applicable base restrictions, posted signs, permit rules, exceptions, temporary orders and their validity/unknown windows. More than one review can contribute coverage only when the approved profile defines how they compose with equal scope and compatible versions.

The proposal tracks status and outcome independently.

| Evaluation status | Legal outcome | Meaning |
|---|---|---|
| `COMPLETE` | `PERMITTED`, `PROHIBITED` or `UNKNOWN` | Evaluation reached the prescribed answer for all inputs. Evidence or coverage may still be incomplete. |
| `INVALID_INPUT` | `UNKNOWN` | Request rejected before evaluation, with a validation reason and no legal conclusion. |
| `FAILED` | `UNKNOWN` | Dependency, cancellation, invalid snapshot or evaluation limit prevented completion. Emit a bounded failure reason and no legal conclusion. |

Cost, fit, occupancy and arrival availability use separate types and return `NOT_ASSESSED` in M3, with no cost amount or currency, fit estimate, observation, capacity/count or probability. Rules with pricing or dimensional eligibility criteria may inform legality only through separately reviewed applicability. A legal result supplies no positive value in another dimension. There is no availability aggregate.

## Time and interval semantics

Durations and dates in this section are proposed evaluation mechanics. Jurisdiction-specific legal interpretation requires a reviewed profile.

| Case | Proposed behavior |
|---|---|
| Requested interval | Use `[start, end)`. Both nonzero instants are required and `start < end`. A future boundary would accept RFC 3339 with a numeric offset or `Z` and at most nanosecond precision. Normalize both instants to UTC. Reject naive local timestamps, invalid dates/offsets, leap seconds, zero or reversed intervals and unsupported precision with `INVALID_STAY_TIME`. Use end-exclusive comparisons throughout. |
| Duration bounds | Measure actual elapsed time, with a proposed inclusive 168-hour maximum for synthetic profiles. A longer request is `INVALID_INPUT` with `STAY_LIMIT_EXCEEDED`. Rule-count, transition and subdivision budgets are separate bounds. Exhausting work limits returns `FAILED` with `EVALUATION_LIMIT` and no truncated permission. |
| Jurisdiction time | Require a reviewed binding to an IANA timezone name and pinned tzdata bytes/version. Derive civil time from each instant under that location. A request offset specifies an instant and cannot set the legal timezone. An unresolved jurisdiction or timezone yields `UNKNOWN` with `JURISDICTION_UNRESOLVED`. An identified timezone with missing or corrupt pinned data fails with `SNAPSHOT_INVALID`. |
| Weekly schedules | Expand by local calendar day and numeric day-of-week. Week boundaries do not reset the stay. A rule defined as starting Monday at 22:00 and ending at 06:00 applies from Monday night through Tuesday morning. Normalize an overnight window into a same-day part and a next-day continuation, also across Sunday to Monday. Equal endpoints are invalid for a weekly window unless its reviewed definition uses an explicit all-day flag. |
| Holiday, seasonal and date exception | Select holidays using the versioned jurisdiction calendar, with exceptions and seasonal boundaries on the actual local civil date, including overnight continuations. A rule-specific exception explicitly adds, subtracts or replaces a window. An unsupported start-day exception or unresolved calendar membership yields `CALENDAR_UNRESOLVED` where it may affect the outcome. |
| Effective start/end | Date-only reviewed bounds are interpreted as inclusive start date and exclusive end date in the jurisdiction, tested against each instant's actual local date. Absolute effective bounds use instants and are also half-open. Exclude instants outside the bounds. An absent bound must be explicitly reviewed as open-ended; an unknown bound cannot prove coverage. |
| Temporary orders | Intersect the reviewed absolute `[start, end)` with the stay, effective period and applicability. Reject unsupported orders expressed only as an ambiguous local start/end unless normalized to unambiguous instants by reviewed evidence. An intersecting decisive restriction prohibits the full requested stay. |
| Spring-forward gap | A recurring civil window applies to the set of real instants whose local labels satisfy it. Skipped labels map to no instants, so a restriction entirely in a skipped hour contributes no overlap. A straddling window includes its real portions on either side. A request timestamp without an offset is invalid even if that wall label would otherwise look plausible. |
| Fall-back repeated hour | A recurring civil window selects both real occurrences of matching labels. Compute their UTC intervals separately and do not bridge a wall-clock subwindow between folds. An offset-bearing request chooses exact instants. If reviewed evidence prescribes a different fold convention and normalization cannot implement it, classify the affected window as unsupported. |
| Maximum stay | Use elapsed duration for the proposed continuous-stay rule. For a reviewed applicable maximum, exactly the cap is permissible absent other restrictions, while elapsed time beyond it proves a violation when all applicable exceptions are resolved. Time outside a rule window counts or resets only as its reviewed accumulation/reset semantics specify. Initial support can limit this to a cap applying throughout the stay. Missing prior dwell/re-parking facts or unsupported partial-window accumulation yield `STAY_HISTORY_UNRESOLVED`. |
| Overlap and boundaries | A positive-length intersection can decide a prohibition. Ending exactly when a restriction starts or starting exactly when it ends does not overlap it. Effective dates, permission and exemption ends, permit expiry and calendar boundaries split the stay without gaps or double counting. |

Implement civil windows by intersecting each local-label range with UTC offset segments for the pinned timezone, then projecting to UTC and clipping to the requested/effective intervals. Adding 24 elapsed hours to find a next local date or mapping just the two wall endpoints would give incorrect DST behavior. Sort and normalize interval boundaries before evaluating them.

## Applicability, authority and full-stay decision

1. Validate the input and snapshot first. Resolve one exact target, side, geometry revision, jurisdiction and timezone. A known wrong-side or wrong-class rule is nonapplicable. An unresolved target cannot inherit any rule or coverage. A rule targeting a confirmed different side cannot fill a missing target's coverage.
2. Bound and partition the stay at changes of rules, exceptions, permit validity, authority or coverage. Check rule structure and use authorization as of the supplied assessment instant. Check legal effective periods and conditions against each evaluated interval. Freshness must use the approved evidence clock and threshold, separately from the rule's legal effective date. An unverified, stale or revoked item may explain an evidence gap. It cannot substantiate a legal proof.
3. Check geographic scope, side and orientation, vehicle class/attributes, permit issuer/class/zone and actual validity, and applicability of exemptions. Use three-valued predicates, `MATCH`, `NO_MATCH` and `UNKNOWN`. A confirmed `NO_MATCH` excludes a rule even if an unrelated attribute is missing. An unknown predicate or unsupported form blocks a conclusion where it could change the effect.
4. Resolve effects under a reviewed, scoped precedence profile. Each authority relationship identifies jurisdiction, rule classes, effect/exception type, scope, effective dates, review version and basis. No default ranking exists among ordinances, posted signs, permits and emergency orders. Equal, incomparable or unsupported authorities bearing conflicting applicable effects make the interval unknown. An approved edge can resolve the specific contradiction. Reject a cyclic, unbound or corrupt profile with `SNAPSHOT_INVALID`. Never use recency, source ordering or identifier sorting as legal precedence.
5. Prove an effect per interval and combine them across the whole stay.

| Proof | Conditions |
|---|---|
| **Permission for an interval** | Exact reviewed binding and supporting authoritative permission. The approved coverage review independently verifies completeness across the relevant layers for that interval, including potential restrictions, exceptions and temporary orders. All applicability facts needed for the effect are known and no unresolved evidence could displace it. Silence, zero prices and source labels never suffice. |
| **Prohibition for an interval** | One verified, applicable authoritative restriction with positive-length overlap. A reviewed restriction-specific coverage record establishes every potentially outcome-changing exception, exemption, superseding permission and conflicting authority is inapplicable, absent under verified coverage or resolved under approved precedence. Other evidence gaps are allowed only if the approved profile and review show they cannot change this restriction's effect. An unknown exemption, unsupported potentially controlling Policy or unresolved conflict in that interval defeats the proof. |
| **Unknown for an interval** | Neither proof holds. Preserve the missing, unsupported, stale, revoked, wrong-side or conflicting evidence and its affected window as reasons. |

The full stay is `PROHIBITED` if **any** interval proves prohibition. An independent proven restriction can decide the stay even if a different interval remains unknown. The result retains both reasons. The stay is `PERMITTED` only if every interval proves permission and any whole-stay conditions are satisfied. Otherwise it is `UNKNOWN`. A conflict defeats only the proof it could change, unless the scope, target or entire snapshot is unresolved.

Reasons carry a stable code, affected interval if known, relevant rule/evidence/approval references and the coverage or missing requirement. Sort by interval start/end, reason code and stable IDs. Deduplicate exact duplicates. Representative codes are `FULL_STAY_AUTHORIZED`, `APPLICABLE_RESTRICTION`, `PERMIT_REQUIRED`, `PERMIT_UNVERIFIED`, `MAX_STAY_EXCEEDED`, `STAY_HISTORY_UNRESOLVED`, `COVERAGE_MISSING`, `TARGET_UNRESOLVED`, `SIDE_MISMATCH`, `VEHICLE_UNRESOLVED`, `AUTHORITY_CONFLICT`, `PRECEDENCE_APPLIED`, `UNSUPPORTED_RULE`, `EVIDENCE_STALE`, and `EVIDENCE_REVOKED`. A successful restriction-free proof does not require an informational reason for every irrelevant excluded rule. The matrix specifies cases where the explanation is material. At the application boundary, use `EVALUATION_CANCELLED` for cancellation, `SNAPSHOT_UNAVAILABLE` for a failed dependency, and `AUDIT_REPLAY_UNAVAILABLE` for denied or unavailable replay.

## Snapshot, current use and replay

- **Immutable identity.** `SnapshotKey` binds purpose, scope, selection pointer version, exact published release and batch, each contributing dataset and evidence artifact/locator, target and geometry revision, rule-set and normalizer/semantics versions, review/evidence and authority profile versions, and calendar and timezone data digests. It also records assessment instant and the captured revocation or eligibility generation. Synthetic and audit purposes are explicit and never encode eligibility for public use. A snapshot digest covers the canonical ordered representation after deduplicating exact records. Different content under the same version fails validation. Retain the minimum request facts and versions necessary for authorized replay.
- **Coherent load.** For internal current evaluation, select the eligible scope and release and load all dependent versions in a single read-only PostgreSQL `REPEATABLE READ` transaction or equivalent one-statement snapshot. The adapter rejects any cross-batch, cross-release or geometry/rule/evidence version mismatch. Missing eligible snapshots yield `COMPLETE` with `UNKNOWN` and reason `NO_ELIGIBLE_RELEASE`. Malformed anchors or query failure yield `FAILED`. The pure engine evaluates the sealed bundle after selection.
- **Concurrent activation and rollback.** An ordinary switch may let an in-flight result finish on A if A remains authorized under scope and pin rules. The result identifies A and carries no guarantee of still being current. A new selection sees B. A rollback uses the explicitly selected release and its own currently eligible rule and review versions. It cannot restore a withdrawn release or rebind rules from the current release.
- **Revocation while in flight.** Before returning a live internal legal result, recheck its exact release eligibility, artifact rights, approval and applicable evidence versions against current authoritative state. An intervening revocation or scope withdrawal suppresses the conclusion and returns `COMPLETE / UNKNOWN / EVIDENCE_REVOKED` with safe unavailable metadata and no restricted content. A failed or canceled recheck yields `FAILED / UNKNOWN`. A still-eligible old snapshot may finish under an ordinary switch. The check establishes eligibility as of that observation; later use requires a new check. Requirements for the revocation generation and retention are decisions for integration, prior to any real serving. Follow existing M2 historical pin and withdrawal rules. [Discovery withdrawal behavior](../../contracts/openapi/DISCOVERY.md#pins-errors-and-recovery)
- **Restricted historical audit.** An independently authorized replay uses the original request facts, exact retained snapshot and original assessment instant, semantics and tzdata. Keep the original snapshot key and digest. Mark the result's purpose as historical, set `current_use_eligible=false`, and include separately observed present authorization status when it may be disclosed. Audit replay cannot alter the active pointer or satisfy a current query. If rights, retention or missing bytes prevent replay, record the reason and return no reconstructed conclusion.

No public eligibility route or OpenAPI addition is proposed in this milestone. A future public evaluation contract requires explicit authorization, revocation/visibility semantics and ADR-027 review. Existing M2 synthetic-only publication and real-source gates still apply. [M2 acceptance](M2_ACCEPTANCE_REPORT.md) · [Synthetic test matrix](M3_TEST_MATRIX.md)
