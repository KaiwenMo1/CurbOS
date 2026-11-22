// Package regulations evaluates synthetic parking fixtures over absolute stays.
// PR-01 evaluates the fixture's target and permit conditions.
// Vehicle-class-specific legal eligibility requires PR-03 applicability checks
// and independently verified conditions.
package regulations

import "time"

type Stay struct {
	Start time.Time
	End   time.Time
}

type StreetSide uint8

const (
	SideUnknown StreetSide = iota
	SideLeft
	SideRight
)

// SyntheticTarget identifies a curb side relative to an exact oriented geometry.
type SyntheticTarget struct {
	Resource     string
	Geometry     string
	Orientation  string
	Jurisdiction string
	Side         StreetSide
}

type RuleID string
type EvidenceRef string

type RuleEffect uint8

const (
	Permission RuleEffect = iota + 1
	Prohibition
	PermitOnly
)

type PermitKey struct {
	Class  string
	Scope  string
	Issuer string
}

type PermitState uint8

const (
	PermitUnknown PermitState = iota
	PermitVerified
)

type PermitFact struct {
	Key   PermitKey
	State PermitState
	// A nil validity leaves the possible match open for the whole stay.
	Validity *Stay
	Evidence []EvidenceRef
}

type PermitInventoryState uint8

const (
	InventoryUnknown PermitInventoryState = iota
	InventoryComplete
)

// PermitInventory describes the fixture's facts for the requested target. An
// empty inventory supports absence only with explicit completeness evidence.
type PermitInventory struct {
	State    PermitInventoryState
	Facts    []PermitFact
	Evidence []EvidenceRef
}

type EvaluationInput struct {
	Stay    Stay
	Target  SyntheticTarget
	Permits PermitInventory
}

type FixtureWindow struct {
	Target   SyntheticTarget
	Window   Stay
	Evidence []EvidenceRef
}

type SyntheticRule struct {
	FixtureWindow
	ID     RuleID
	Effect RuleEffect
	Permit PermitKey
	// SubjectTo names restrictions that this fixture permission yields to.
	SubjectTo []RuleID
}

// RestrictionAssumption supplies a synthetic premise about the absence of an
// outcome-changing exemption or override for one exact restriction and window.
type RestrictionAssumption struct {
	FixtureWindow
	Rule RuleID
}

type UnresolvedKind uint8

const (
	PotentialEffectUnknown UnresolvedKind = iota
	PotentialRestriction
	PotentialOverride
)

// UnresolvedFact can span the whole request when Window is nil. An override
// with an empty Rule may affect any restriction on the target.
type UnresolvedFact struct {
	Target   SyntheticTarget
	Window   *Stay
	Kind     UnresolvedKind
	Rule     RuleID
	Evidence []EvidenceRef
}

// SyntheticSnapshot contains test premises with fixture-local identifiers.
type SyntheticSnapshot struct {
	Target       SyntheticTarget
	Rules        []SyntheticRule
	Coverage     []FixtureWindow
	Restrictions []RestrictionAssumption
	Unresolved   []UnresolvedFact
}

type EvaluationStatus string

const (
	Complete     EvaluationStatus = "COMPLETE"
	InvalidInput EvaluationStatus = "INVALID_INPUT"
	Failed       EvaluationStatus = "FAILED"
)

type LegalOutcome string

const (
	Permitted  LegalOutcome = "PERMITTED"
	Prohibited LegalOutcome = "PROHIBITED"
	Unknown    LegalOutcome = "UNKNOWN"
)

type DimensionStatus string

const NotAssessed DimensionStatus = "NOT_ASSESSED"

type ReasonCode string

const (
	FullStayAuthorized    ReasonCode = "FULL_STAY_AUTHORIZED"
	ApplicablePermission  ReasonCode = "APPLICABLE_PERMISSION"
	ApplicableRestriction ReasonCode = "APPLICABLE_RESTRICTION"
	PermitRequired        ReasonCode = "PERMIT_REQUIRED"
	PermitUnverified      ReasonCode = "PERMIT_UNVERIFIED"
	CoverageMissing       ReasonCode = "COVERAGE_MISSING"
	PermissionMissing     ReasonCode = "PERMISSION_MISSING"
	TargetUnresolved      ReasonCode = "TARGET_UNRESOLVED"
	SideMismatch          ReasonCode = "SIDE_MISMATCH"
	AuthorityConflict     ReasonCode = "AUTHORITY_CONFLICT"
	InvalidTarget         ReasonCode = "INVALID_TARGET"
	InvalidStayTime       ReasonCode = "INVALID_STAY_TIME"
	StayLimitExceeded     ReasonCode = "STAY_LIMIT_EXCEEDED"
	EvaluationLimit       ReasonCode = "EVALUATION_LIMIT"
	SnapshotInvalid       ReasonCode = "SNAPSHOT_INVALID"
)

type Reason struct {
	Code ReasonCode
	Rule RuleID
}

type RuleReference struct {
	ID       RuleID
	Evidence []EvidenceRef
}

type IntervalResult struct {
	Window   Stay
	Legal    LegalOutcome
	Reasons  []Reason
	RuleRefs []RuleReference
	// EvidenceRefs is a sorted, deduplicated union across the interval's
	// checks. For permits, it cites active verified matches for satisfaction,
	// complete inventory for absence, or compatible active unknown facts and
	// any incomplete inventory evidence for uncertainty. Per-check attribution
	// and a trace of discarded facts are outside this flat result.
	EvidenceRefs []EvidenceRef
}

type Result struct {
	Status    EvaluationStatus
	Legal     LegalOutcome
	Intervals []IntervalResult
	Reasons   []ReasonCode
	Cost      DimensionStatus
	Fit       DimensionStatus
	Occupancy DimensionStatus
	Arrival   DimensionStatus
}
