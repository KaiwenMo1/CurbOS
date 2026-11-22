# M3 internal rule evaluation contract

**Reconciled design.** M3-00D fixes the Minimal Core scope and interval contract. M3-02D freezes the synthetic civil-time semantics for PR-02. The broader type sketches describe later slices. All rule examples and fixtures are synthetic. [Design specification and decision register](M3_DESIGN_SPEC.md)

## Typed domain boundary

PR-01 exposes only an internal pure Go evaluator for typed fixture inputs. It accepts an exact synthetic target, absolute windows, simple permit facts and explicit scoped fixture assumptions. It uses no database, wall clock, local timezone, network, public API, production data or runtime feature wiring. The broader designs below add pinned timezone inputs in PR-02, reviewed evidence in PR-03, persistence and current-use checks in PR-04/05 and replay in PR-06.

### Synthetic trust boundary

Keep the Minimal Core's input distinct from the later reviewed snapshot. A fixture assumption names the target, absolute interval and modeled fact, such as complete legal coverage for a window or no outcome-changing exemption for one restriction. These facts are synthetic test premises. They do not verify review, source rights, field placement or legal authority. Missing coverage or restriction assumptions produce `UNKNOWN` where they affect the proof. Conflicting effects without an explicit fixture condition remain `UNKNOWN`. A fixture may explicitly make base permission conditional on a named restriction. The evaluator must infer no ordering from rule order or effect.

Fixture types and references must have no path to production authorization. An arbitrary `approved=true`, a digest, or a synthetic review reference is insufficient. There is no constructor, cast or fallback that upgrades fixture assumptions into authoritative evidence. Full coverage and authority certificate verification belongs to PR-03 or later. PR-01 validates only fixture structure and bindings and keeps its entry point disconnected from the running API.

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
type IntervalResult struct {
    Window Stay // exact UTC [start, end)
    Legal LegalOutcome
    Reasons []Reason
    RuleRefs []RuleRef
    EvidenceRefs []EvidenceID
}
type RuleRef struct {
    ID RuleID
    Version RuleVersion
}
type Result struct {
    Status EvaluationStatus
    Legal LegalOutcome // overall requested stay
    Intervals []IntervalResult
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

`EvidenceRecord` keeps dataset, batch, artifact digest and record locator, source authority, rights and separate `ObservedAt`, `SourceAsOf` and legal effective period. It carries structural parse status separately from immutable, independently verified `ReviewDecision` records. Review records bind reviewer identity and authority, independence, exact digests, covered target/windows and effective validity. A separately retained revocation version records later changes in authorization.

### Coverage and negative proof

| Evidence layer | What it establishes |
|---|---|
| **Source structural/reference coverage** | Whether records parse and references resolve, with source/geometry scope, exclusions and missing references. A source reference or geometry coverage pass alone supplies no legal completeness. |
| **Reviewed legal coverage completeness** | Whether the exact target, geometry, vehicle and permit facts are covered for each requested interval by the applicable base restrictions, posted signs, permits, exceptions, temporary orders and potentially relevant excluded or unsupported records. It requires reviewed applicability, scope, provenance, precedence and effective validity. Layers compose only under a reviewed profile for compatible versions and scope. |
| **Restriction-specific negative proof** | Whether the cited restriction is authoritative and applicable to the interval and all potentially outcome-changing exceptions, exemptions or superseding authorities are inapplicable, demonstrably absent, or resolved under explicit scoped precedence. This permits a decisive prohibition when unrelated coverage is incomplete. |

`CoverageReview` preserves excluded, missing, unsupported or unparsed records with their IDs or locators, possible scope, effective window when known and review disposition. If a record could apply, carry the unresolved fact across its possible overlap. An unknown window cannot be narrowed by inference. A potentially applicable unknown restriction blocks permission. A possible exemption or superseding authority can defeat prohibition. A record confirmed irrelevant to the proof may be excluded with its disposition retained. Community reports remain unverified inputs for review, with no automatic legal authority.

The proposal tracks status and outcome independently.

| Evaluation status | Legal outcome | Meaning |
|---|---|---|
| `COMPLETE` | `PERMITTED`, `PROHIBITED` or `UNKNOWN` | Return a complete, nonoverlapping partition of the valid stay. Evidence or coverage may still be incomplete. |
| `INVALID_INPUT` | `UNKNOWN` | Request rejected before evaluation. Return a validation reason and no intervals. |
| `FAILED` | `UNKNOWN` | Dependency, cancellation, invalid snapshot or work limit prevented completion. Return a bounded failure reason and no intervals or partial legal result. |

Every `COMPLETE` result has sorted positive-length `IntervalResult` values. The first start and last end equal the normalized request bounds, and each end equals the next start. Boundaries are exact UTC instants and are end-exclusive. Each interval has its own outcome, reasons and applicable rule-to-evidence references, with safe IDs and unresolved requirements when proof is missing. If a valid stay has no eligible snapshot or a later current-use check suppresses the evidence, return one whole-stay `UNKNOWN` interval with a safe reason and no restricted references.

Cost, fit, occupancy and arrival availability use separate types and return `NOT_ASSESSED` in M3, with no cost amount or currency, fit estimate, observation, capacity/count or probability. Rules with pricing or dimensional eligibility criteria may inform legality only through separately reviewed applicability. A legal result supplies no positive value in another dimension. There is no availability aggregate.

## Time and interval semantics

### PR-01 absolute UTC evaluation

Validate Go `time.Time` values at the typed boundary. Reject a zero endpoint or `start >= end` with `INVALID_INPUT` and `INVALID_STAY_TIME`. Compare instants, discard location and monotonic-clock metadata for normalized output, and preserve nanosecond precision. PR-01 has no timestamp string parser. Offset syntax, naive strings, leap seconds and textual precision belong to a separately authorized RFC 3339 boundary. DST gaps, folds, weekly schedules and other civil-time normalization belong to PR-02.

| Inclusive PR-01 limit | Count and failure |
|---|---|
| **168 elapsed hours** | Actual elapsed time of the requested stay. Longer is `INVALID_INPUT` with `STAY_LIMIT_EXCEEDED`. |
| **256 rules** | Supplied fixture rule records, checked before filtering. Over budget is `FAILED` with `EVALUATION_LIMIT`. |
| **1,024 raw temporal windows** | One combined count across the request and fixture snapshot. Count each supplied absolute interval used by a rule, effective period, coverage record, assumption, permit validity or unresolved record. Charge one window for each unbounded fact evaluated across the whole stay, such as an unresolved record or unknown permit with no narrower interval. Count duplicates, empty windows and windows that clip out before any validation, filtering, merging or deduplication of those windows. The requested stay itself contributes only its two endpoint entries. Over budget is `FAILED` with `EVALUATION_LIMIT`. |
| **1,024 unique temporal boundaries** | Exact distinct UTC split instants after clipping, including both request endpoints. Over budget is `FAILED` with `EVALUATION_LIMIT`. |
| **2,048 evidence references** | Supplied evidence-reference entries used by the fixture request and snapshot, counted before deduplication so repeats also consume work budget. Over budget is `FAILED` with `EVALUATION_LIMIT`. |

Each positive-length clipped window contributes one start event and one end event. The request start and end each contribute one entry. Count endpoint entries individually before deduplication, even if they coincide with each other across windows or with a request endpoint. PR-01 clips each raw window at most once and handles intersections through active conditions in the sweep. This bounds the event input to **2,050 endpoint entries** (two per raw window plus the two request endpoints). Never expand a raw window into multiple event pairs in the Minimal Core.

These are synthetic work limits, with no measured performance claim. Exceeding any work budget returns `FAILED / UNKNOWN / EVALUATION_LIMIT` with no intervals or legal proof. A corrupt fixture snapshot within the raw input budgets returns `FAILED / UNKNOWN / SNAPSHOT_INVALID` with no intervals or legal proof.

1. Validate the requested stay. Preflight the rule, raw window and reference counts on the original typed collections before copying, flattening, sorting, or allocating event, deduplication or result storage. Check collection lengths before walking them and reject as soon as a count exceeds its remaining allowance. Count nested windows, implicit whole-stay windows and references without materializing them in a scratch collection. Use checked counts without overflow. Cap event capacity from the verified raw count and check the derived endpoint bound before appending each pair.
2. Validate all supplied fixture windows and bindings before applying any effect. A zero endpoint, equal or reversed endpoints, or an inconsistent binding is corruption. Each supplied proof window or assertion cites at least one fixture evidence reference, counted under the reference limit. Missing coverage stays unknown unless other valid evidence supplies it. Exact duplicates may be consolidated only after preflight and validation. Duplicates provide no additional coverage or authority.
3. Clip each valid window to the stay using `[start, end)`. A valid window with no positive-length overlap emits no events and supplies no coverage. Collect start/end events for positive-length intersections and both request endpoints. Deduplicate boundary instants, preserving distinct active conditions at each instant, and check the unique-boundary limit before evaluation. A decisive restriction never bypasses preflight, validation or any later budget check, including when it starts at the first boundary.
4. Sweep the sorted unique instants. At each boundary, remove windows ending there and add windows starting there before evaluating the next positive-length segment. Use the exact active conditions for that segment, with deterministic ordering of references and reasons. Never use fixed-minute sampling or round to clock ticks. A one-second restriction, or a shorter legitimate interval at nanosecond precision, must remain visible.
5. Emit each event-to-event interval with its own evidence and outcome, then aggregate the whole-stay outcome. The verdict for one interval never removes unknowns or replaces the evidence for another.

### PR-02 civil-time design

PR-02 normalizes supported synthetic civil inputs to absolute UTC half-open windows before the existing PR-01 evaluator. The exact-event sweep, whole-stay aggregation, absolute input budgets and legal proof requirements apply to the normalized inputs. RFC 3339 parsing remains a separate transport decision.

#### D1-A — Pinned timezone and binding

Each civil evaluation supplies an explicit jurisdiction-to-timezone binding, the exact IANA timezone ID, timezone-data version and content digest, and the immutable bytes for that zone. Check the digest and the pinned association between jurisdiction, ID, version and bytes. A loader accepting bytes under a supplied name does not establish that association. Use Go's `time.LoadLocationFromTZData` with the checked bytes where suitable. Derive local labels and offsets from that location only. Host tzdata, `time.Local`, process environment variables and inferred offsets are outside the input contract.

| Timezone input state | Result |
|---|---|
| Jurisdiction or timezone binding unresolved, with an otherwise safely evaluable request that needs civil interpretation | `COMPLETE / UNKNOWN` with `JURISDICTION_UNRESOLVED`. Return a whole-stay unknown interval with no civil proof. |
| Zone identified, but pinned bytes, version or digest missing, inconsistent or corrupt | `FAILED / UNKNOWN` with `SNAPSHOT_INVALID`. Return no intervals or partial proof. |

Validate applicable request and input bounds before returning an unresolved result. A request composed solely of absolute inputs can enter the PR-01 path directly.

#### D1-B and D1-C — Local labels and exact UTC projection

- A recurring window selects the real instants whose local labels satisfy the rule. Weekdays are numeric, from Sunday (`0`) through Saturday (`6`). Wall-clock start is inclusive and end exclusive. Use a distinct all-day marker for the span from local midnight to the following local midnight. Equal clock endpoints without that marker are an unsupported shape.
- A start clock later than the end clock anchors an overnight window to the **starting** local weekday. Its continuation belongs to that occurrence across Sunday-to-Monday and month or year rollover. Advance dates with calendar arithmetic.
- Date-only effective and seasonal ranges use inclusive start and exclusive end **local dates**. In this synthetic profile these ranges and dated exceptions apply to the actual local date of each piece, including an overnight continuation. The anchor still determines weekly recurrence. UTC conversion preserves half-open endpoints and exact precision.
- Split the stay into spans of constant UTC offset from the pinned zone. Intersect the rule's civil labels with the labels exposed by each span, project each nonempty intersection to UTC using that span's offset, then clip to the stay. Calendar pieces, UTC offset spans and their intersections can be shorter or longer than a nominal civil day. A nonexistent spring-forward label has no preimage. Repeated fall-back labels contribute both UTC occurrences. Preserve separate projected pieces at offset changes and any intervening uncovered interval.
- A conditional schedule emits a rule window when the fixture establishes its applicability. A known nonapplicable condition emits none. Preserve potentially applicable windows with unknown conditions, unsupported shapes or unresolved effects as unresolved evidence for their possible overlap, with `UNSUPPORTED_RULE` when applicable. Use the whole stay when no narrower bound is established. A real source's fold, gap, overnight or date interpretation that differs from the synthetic policy requires reviewed source-specific treatment in PR-03 or later.

Generated pieces must retain the original rule and evidence provenance. The merged core uses one absolute window per rule and rejects different windows under the same rule ID. Give distinct pieces stable, distinct fixture identities and preserve the binding to their original rule. Keep each applicable assumption and any explicit fixture permission condition bound to the corresponding normalized restriction. The exact encoding of fragment identifiers is an implementation review detail.

#### D1-D — Versioned synthetic calendars

A calendar-dependent fixture explicitly supplies the synthetic calendar identity, version and content digest, with dated membership and reviewed fixture assumptions. Resolve only bounded, explicitly defined holiday and date exceptions. A supported exception binds one rule and one actual local date and either adds an explicit window, removes a specified window, or replaces the rule's windows for that date with specified windows. Apply the operation only over its reviewed scope. Conflicting operations require a resolved fixture disposition.

Treat unknown holiday membership, unsupported anchoring and absent or unsupported calendar versions as `CALENDAR_UNRESOLVED` over the intervals they might affect. Preserve potentially relevant restrictions as unresolved evidence. A missing date entry never proves ordinary-day membership when holiday status controls the calculation. An integrity mismatch in a supplied supported calendar is `SNAPSHOT_INVALID`. Real government calendars and enforcement exceptions require later review.

#### D1-E — Continuous elapsed stay

Support a positive synthetic elapsed cap only when it applies throughout the requested stay, the continuous-occupancy start is an explicit absolute instant at or before the request start, and scoped fixture evidence establishes applicability, exceptions and that the elapsed time from that start counts. The occupancy anchor is a separate fact from request arrival. The supported fixture needs no additional prior dwell, re-parking history, partial-window accumulation or reset logic.

Compute expiration as the established occupancy start plus the elapsed cap, with checked instant arithmetic. Ending exactly at expiration is within the cap. When the stay extends beyond expiration, emit the restriction over `[max(request start, expiration), request end)`. Record `MAX_STAY_EXCEEDED` and preserve the expiration boundary when it falls inside the request. The earlier interval gets permission only through the usual independent permission and coverage proof. When the anchor, prior history or accumulation/reset semantics could change the conclusion, preserve `STAY_HISTORY_UNRESOLVED` and `UNKNOWN` for the affected proof. The normal treatment of any independent decisive restriction still applies.

Carry normalization reasons and their source references on the affected intervals. The civil stage supplies absolute inputs and diagnostics. The existing core still determines interval and whole-stay legal outcomes.

#### D1-F — Bounded normalization

Preflight typed raw civil inputs and calendar entries before copying, sorting or expanding them. Count duplicate declarations and exceptions before filtering. Validate the requested duration and count absolute inputs against their existing limits. For each UTC offset span, derive the first and last local dates actually touched by the half-open stay, including the local date of its last included instant. Check the resulting civil date envelope with at most one extra preceding local date for overnight anchors. Bound offset iteration and require monotonic progress between transitions.

The following inclusive PR-02 ceilings are bounded **candidates**, pending approval before implementation. They express admission limits, with no measured time or memory claim.

| Pre-expansion work | Candidate ceiling |
|---|---:|
| Raw civil declarations across the request and fixture | 256 |
| Supplied calendar entries across memberships and exceptions | 256 |
| Civil anchor dates in the full checked envelope, including overnight lookback | 10 |
| UTC offset spans visited for the stay | 32 |
| Pinned timezone input per evaluation | 256 KiB |
| Intermediate window entries held during calendar operations | 1,024 |

Inspect timezone byte length before hashing and loading. Iterate admitted dates and offset spans without materializing their Cartesian product. Budget intermediate calendar splits before allocation and retain at most 1,024 pending window entries at any time. Charge each generated UTC window, including unresolved fragments and duplicates, when it is produced against the core's **shared 1,024 raw temporal windows** remaining after absolute inputs are counted. Check remaining allowance before appending and before allocating output proportional to a count. Apply the same checks to duplicated reference entries and materialized rule pieces so the complete fixture respects the existing 2,048 evidence-reference and 256 rule caps. Each retained window contributes at most two endpoint entries. The 2,050 endpoint and 1,024 unique-boundary limits still apply, including the stay endpoints.

Use checked subtraction, increments and instant/date arithmetic. A work-budget excess yields `FAILED / UNKNOWN / EVALUATION_LIMIT` without interval results or legal proof. Reject the batch before evaluation if any date, span, split or generated entry exceeds the admitted work. Truncation, skipped unprocessed dates or an early legal result would violate the contract. A malformed or inconsistent fixture within work limits follows the snapshot validation failure path.

## Applicability, authority and full-stay decision

This section describes the full proof model. PR-01 applies only the explicitly scoped fixture premises and simple permit facts. PR-03 owns reviewed authority, exemption and completeness verification.

1. Validate the input and snapshot first. Resolve one exact target, side, geometry revision and jurisdiction. Civil normalization also resolves the pinned timezone from PR-02 onward. A known wrong-side or wrong-class rule is nonapplicable. An unresolved target cannot inherit any rule or coverage. A rule targeting a confirmed different side cannot fill a missing target's coverage.
2. Bound and partition the stay at changes of rules, exceptions, permit validity, authority or coverage. Check rule structure and use authorization as of the supplied assessment instant. Check legal effective periods and conditions against each evaluated interval. Freshness must use the approved evidence clock and threshold, separately from the rule's legal effective date. An unverified, stale or revoked item may explain an evidence gap. It cannot substantiate a legal proof.
3. Check geographic scope, side and orientation, vehicle class/attributes, permit issuer/class/zone and actual validity, and applicability of exemptions. Use three-valued predicates, `MATCH`, `NO_MATCH` and `UNKNOWN`. A confirmed `NO_MATCH` excludes a rule even if an unrelated attribute is missing. An unknown predicate or unsupported form blocks a conclusion where it could change the effect.
4. Resolve effects under a reviewed, scoped precedence profile. Each authority relationship identifies jurisdiction, rule classes, effect/exception type, scope, effective dates, review version and basis. No default ranking exists among ordinances, posted signs, permits and emergency orders. Equal, incomparable or unsupported authorities bearing conflicting applicable effects make the interval unknown. An approved edge can resolve the specific contradiction. Reject a cyclic, unbound or corrupt profile with `SNAPSHOT_INVALID`. Never use recency, source ordering or identifier sorting as legal precedence.
5. Prove an effect per interval and combine them across the whole stay.

| Proof | Conditions |
|---|---|
| **Permission for an interval** | Exact reviewed binding and supporting authoritative permission. The coverage review independently verifies all listed legal layers for that interval, including potentially relevant excluded and unsupported records. All required applicability facts are known and no unresolved evidence could displace permission. Silence, zero prices and source labels never suffice. |
| **Prohibition for an interval** | One verified, applicable authoritative restriction with positive-length overlap. A reviewed restriction-specific coverage record establishes every potentially outcome-changing exception, exemption, superseding permission and conflicting authority is inapplicable, absent under verified coverage or resolved under approved precedence. Other evidence gaps are allowed only if the approved profile and review show they cannot change this restriction's effect. An unknown exemption, unsupported potentially controlling Policy or unresolved conflict in that interval defeats the proof. |
| **Unknown for an interval** | Neither proof holds. Preserve the missing, unsupported, stale, revoked, wrong-side or conflicting evidence and its affected window as reasons. |

The full stay is `PROHIBITED` if **any** interval proves prohibition. Other intervals keep their own outcomes, including `UNKNOWN`. The stay is `PERMITTED` only if every interval proves permission and any whole-stay conditions are satisfied. Otherwise it is `UNKNOWN`. A conflict defeats only the proof it could change, unless the scope, target or entire snapshot is unresolved.

Reasons carry a stable code, affected interval if known, relevant rule/evidence/approval references and the coverage or missing requirement. Sort by interval start/end, reason code and stable IDs. Deduplicate exact duplicates. Representative codes are `FULL_STAY_AUTHORIZED`, `APPLICABLE_RESTRICTION`, `PERMIT_REQUIRED`, `PERMIT_UNVERIFIED`, `MAX_STAY_EXCEEDED`, `STAY_HISTORY_UNRESOLVED`, `COVERAGE_MISSING`, `TARGET_UNRESOLVED`, `SIDE_MISMATCH`, `VEHICLE_UNRESOLVED`, `AUTHORITY_CONFLICT`, `PRECEDENCE_APPLIED`, `UNSUPPORTED_RULE`, `EVIDENCE_STALE`, and `EVIDENCE_REVOKED`. A successful restriction-free proof does not require an informational reason for every irrelevant excluded rule. The matrix specifies cases where the explanation is material. At the application boundary, use `EVALUATION_CANCELLED` for cancellation, `SNAPSHOT_UNAVAILABLE` for a failed dependency, and `AUDIT_REPLAY_UNAVAILABLE` for denied or unavailable replay.

## Snapshot, current use and replay

- **Immutable identity.** `SnapshotKey` binds purpose, scope, selection pointer version, exact published release and batch, each contributing dataset and evidence artifact/locator, target and geometry revision, rule-set and normalizer/semantics versions, review/evidence and authority profile versions, and calendar and timezone data digests. It also records assessment instant and the captured revocation or eligibility generation. Synthetic and audit purposes are explicit and never encode eligibility for public use. A snapshot digest covers the canonical ordered representation after deduplicating exact records. Different content under the same version fails validation. Retain the minimum request facts and versions necessary for authorized replay.
- **Coherent load.** For internal current evaluation, select the eligible scope and release and load all dependent versions in a single read-only PostgreSQL `REPEATABLE READ` transaction or equivalent one-statement snapshot. The adapter rejects any cross-batch, cross-release or geometry/rule/evidence version mismatch. Missing eligible snapshots yield `COMPLETE` with `UNKNOWN` and reason `NO_ELIGIBLE_RELEASE`. Malformed anchors or query failure yield `FAILED`. The pure engine evaluates the sealed bundle after selection.
- **Concurrent activation and rollback.** An ordinary switch may let an in-flight result finish on A if A remains authorized under scope and pin rules. The result identifies A and carries no guarantee of still being current. A new selection sees B. A rollback uses the explicitly selected release and its own currently eligible rule and review versions. It cannot restore a withdrawn release or rebind rules from the current release.
- **Revocation while in flight.** Before returning a live internal legal result, recheck its exact release eligibility, artifact rights, approval and applicable evidence versions against current authoritative state. An intervening revocation or scope withdrawal suppresses the conclusion and returns `COMPLETE / UNKNOWN / EVIDENCE_REVOKED` with safe unavailable metadata and no restricted content. A failed or canceled recheck yields `FAILED / UNKNOWN`. A still-eligible old snapshot may finish under an ordinary switch. The check establishes eligibility as of that observation; later use requires a new check. Requirements for the revocation generation and retention are decisions for integration, prior to any real serving. Follow existing M2 historical pin and withdrawal rules. [Discovery withdrawal behavior](../../contracts/openapi/DISCOVERY.md#pins-errors-and-recovery)
- **Restricted historical audit.** An independently authorized replay uses the original request facts, exact retained snapshot and original assessment instant, semantics and tzdata. Keep the original snapshot key and digest. Mark the result's purpose as historical, set `current_use_eligible=false`, and include separately observed present authorization status when it may be disclosed. Audit replay cannot alter the active pointer or satisfy a current query. If rights, retention or missing bytes prevent replay, record the reason and return no reconstructed conclusion.

No public eligibility route or OpenAPI addition is proposed in this milestone. A future public evaluation contract requires explicit authorization, revocation/visibility semantics and ADR-027 review. Existing M2 synthetic-only publication and real-source gates still apply. [M2 acceptance](M2_ACCEPTANCE_REPORT.md) · [Synthetic test matrix](M3_TEST_MATRIX.md)
