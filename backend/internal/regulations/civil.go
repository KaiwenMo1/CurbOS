package regulations

import (
	"cmp"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"slices"
	"time"
)

type CivilWindow struct {
	Target   SyntheticTarget
	Schedule CivilSchedule
	Evidence []EvidenceRef
}

type CivilRule struct {
	CivilWindow
	ID        RuleID
	Effect    RuleEffect
	Permit    PermitKey
	SubjectTo []RuleID
}

type ContinuousStayMode uint8

const (
	StayHistoryUnknown ContinuousStayMode = iota
	ContinuousElapsed
)

type ContinuousStayCap struct {
	FixtureWindow
	ID             RuleID
	Limit          time.Duration
	OccupancyStart *time.Time
	Mode           ContinuousStayMode
	// CountedFrom cites the premise that elapsed occupancy counts from the
	// supplied start without prior dwell, re-parking, or reset logic.
	CountedFrom []EvidenceRef
}

// CivilSnapshot can refer to logical civil or cap rule IDs in SubjectTo,
// restriction assumptions, and unresolved overrides in Absolute.
type CivilSnapshot struct {
	Absolute        SyntheticSnapshot
	TimezoneBinding *SyntheticTimezoneBinding
	Timezone        *PinnedTimezone
	CalendarBinding *CalendarPin
	Calendar        *SyntheticCalendar
	Rules           []CivilRule
	Coverage        []CivilWindow
	Caps            []ContinuousStayCap
}

type CivilNormalization struct {
	Snapshot SyntheticSnapshot
	Timezone TimezonePin
	Calendar CalendarPin
	// AppliedCalendar identifies the scoped records in the pinned calendar
	// even when a removal leaves no normalized rule to carry their evidence.
	AppliedCalendar []CalendarUse

	calendarExclusions []CalendarExclusion
}

type CalendarUse struct {
	Rule      RuleID
	Date      CivilDate
	Operation CalendarOperation
}

func civilPreflight(input EvaluationInput, fixture CivilSnapshot) bool {
	budget, ok := remainingBudget(input, fixture.Absolute)
	if !ok || fixture.Timezone != nil && len(fixture.Timezone.Data) > maxTimezoneBytes {
		return false
	}
	declarations := maxCivilDeclarations
	for _, n := range [...]int{len(fixture.Rules), len(fixture.Coverage), len(fixture.Caps)} {
		if n > declarations {
			return false
		}
		declarations -= n
	}
	if c := fixture.Calendar; c != nil {
		if len(c.Days) > maxCalendarEntries || len(c.Exceptions) > maxCalendarEntries-len(c.Days) {
			return false
		}
		for _, exception := range c.Exceptions {
			if !budget.take(0, 0, len(exception.Evidence)) {
				return false
			}
		}
	}
	for _, rule := range fixture.Rules {
		if !budget.take(0, 0, len(rule.Evidence)) {
			return false
		}
	}
	for _, coverage := range fixture.Coverage {
		if !budget.take(0, 0, len(coverage.Evidence)) {
			return false
		}
	}
	for _, cap := range fixture.Caps {
		if !budget.take(0, 0, len(cap.Evidence)) || !budget.take(0, 0, len(cap.CountedFrom)) {
			return false
		}
	}
	return true
}

// NormalizeCivil validates and projects synthetic fixtures. A nonempty
// diagnostic returns a zero normalization. It does not decide parking legality.
func NormalizeCivil(input EvaluationInput, fixture CivilSnapshot) (CivilNormalization, ReasonCode) {
	stay := input.Stay.utc()
	if !stay.valid() {
		return CivilNormalization{}, InvalidStayTime
	}
	if stay.End.Sub(stay.Start) > maxStay {
		return CivilNormalization{}, StayLimitExceeded
	}
	if input.Target.Side > SideRight {
		return CivilNormalization{}, InvalidTarget
	}
	if !civilPreflight(input, fixture) {
		return CivilNormalization{}, EvaluationLimit
	}

	expandedIDs, civilIDs, lookback, ok := validateCivilFixture(stay, input.Permits, fixture)
	if !ok {
		return CivilNormalization{}, SnapshotInvalid
	}
	calendar, ok := indexCalendar(fixture.CalendarBinding, fixture.Calendar, civilIDs)
	if !ok {
		return CivilNormalization{}, SnapshotInvalid
	}

	var timezone TimezonePin
	var spans []offsetSpan
	var first, last time.Time
	if len(fixture.Rules) != 0 || len(fixture.Coverage) != 0 {
		location, reason := loadFixtureTimezone(fixture.Absolute.Target.Jurisdiction, fixture.TimezoneBinding, fixture.Timezone)
		if reason != "" {
			if reason == JurisdictionUnresolved && !absoluteBoundariesFit(input, fixture.Absolute) {
				return CivilNormalization{}, EvaluationLimit
			}
			return CivilNormalization{}, reason
		}
		if input.Target.Jurisdiction == "" {
			if !absoluteBoundariesFit(input, fixture.Absolute) {
				return CivilNormalization{}, EvaluationLimit
			}
			return CivilNormalization{}, JurisdictionUnresolved
		}
		timezone = fixture.TimezoneBinding.Pin
		spans, reason = offsetSpans(stay, location)
		if reason != "" {
			return CivilNormalization{}, reason
		}
		first, last, reason = civilDateEnvelope(spans, lookback)
		if reason != "" {
			return CivilNormalization{}, reason
		}
	}

	out := newCivilOutput(input, fixture.Absolute, expandedIDs)
	var calendarUses map[calendarKey]CalendarUse
	for _, rule := range fixture.Rules {
		for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
			if !rule.Schedule.onDate(day) || rule.Schedule.Condition == CivilDoesNotApply || !touchesDate(day, spans) {
				continue
			}
			pieces, unsupported := scheduleOnDate(rule.Schedule, day)
			resolution := calendar.resolve(rule.ID, rule.Schedule, day, pieces)
			reason := resolution.reason
			if reason == "" && (unsupported || rule.Schedule.Condition == CivilConditionUnresolved) {
				reason = UnsupportedRule
			}
			if reason == "" && resolution.operation != 0 {
				date := dateOf(day)
				if calendarUses == nil {
					calendarUses = make(map[calendarKey]CalendarUse)
				}
				use := CalendarUse{rule.ID, date, resolution.operation}
				calendarUses[calendarKey{rule.ID, date}] = use
				if rule.Target == fixture.Absolute.Target && rule.Effect != Permission {
					if !out.addCalendarExclusions(use, resolution, spans) {
						return CivilNormalization{}, EvaluationLimit
					}
				}
			}
			for _, piece := range resolution.windows {
				for _, span := range spans {
					window, exists := project(piece, span)
					if !exists {
						continue
					}
					if reason != "" {
						if !out.addGap(rule.Target, window, rule.ID, rule.Effect, reason, rule.Evidence, resolution.evidence) {
							return CivilNormalization{}, EvaluationLimit
						}
						continue
					}
					if !out.addRule(window, rule.ID, rule.Target, rule.Effect, rule.Permit, rule.SubjectTo, rule.Evidence, resolution.evidence, "") {
						return CivilNormalization{}, EvaluationLimit
					}
				}
			}
		}
	}
	for _, coverage := range fixture.Coverage {
		for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
			pieces, unsupported := scheduleOnDate(coverage.Schedule, day)
			if len(pieces) == 0 {
				continue
			}
			resolution := calendar.resolve("", coverage.Schedule, day, pieces)
			reason := resolution.reason
			if reason == "" && (unsupported || coverage.Schedule.Condition == CivilConditionUnresolved) {
				reason = UnsupportedRule
			}
			for _, piece := range resolution.windows {
				for _, span := range spans {
					window, exists := project(piece, span)
					if !exists {
						continue
					}
					if reason != "" {
						if !out.addGap(coverage.Target, window, "", Prohibition, reason, coverage.Evidence, nil) {
							return CivilNormalization{}, EvaluationLimit
						}
						continue
					}
					if !out.budget.take(1, 0, len(coverage.Evidence)) {
						return CivilNormalization{}, EvaluationLimit
					}
					out.snapshot.Coverage = append(out.snapshot.Coverage, FixtureWindow{coverage.Target, window, coverage.Evidence})
				}
			}
		}
	}
	for _, cap := range fixture.Caps {
		if reason := out.addCap(stay, cap); reason != "" {
			return CivilNormalization{}, reason
		}
	}
	if !out.bindProof(stay, fixture.Absolute, expandedIDs) {
		return CivilNormalization{}, EvaluationLimit
	}

	snapshot, ok := validateSnapshot(out.snapshot, input.Permits)
	if !ok {
		return CivilNormalization{}, SnapshotInvalid
	}
	if !absoluteBoundariesFit(input, snapshot) {
		return CivilNormalization{}, EvaluationLimit
	}
	sortCivilWindows(stay, snapshot)
	var uses []CalendarUse
	for _, use := range calendarUses {
		uses = append(uses, use)
	}
	slices.SortFunc(uses, func(a, b CalendarUse) int {
		if order := cmp.Compare(a.Rule, b.Rule); order != 0 {
			return order
		}
		return a.Date.midnight().Compare(b.Date.midnight())
	})
	slices.SortFunc(out.calendarExclusions, compareCalendarExclusions)
	exclusions := slices.CompactFunc(out.calendarExclusions, func(a, b CalendarExclusion) bool {
		return compareCalendarExclusions(a, b) == 0
	})
	return CivilNormalization{
		Snapshot: snapshot, Timezone: timezone, Calendar: calendar.pin,
		AppliedCalendar: uses, calendarExclusions: exclusions,
	}, ""
}

// EvaluateCivil delegates all legal decisions to the absolute evaluator.
func EvaluateCivil(input EvaluationInput, fixture CivilSnapshot) Result {
	if len(fixture.Rules) == 0 && len(fixture.Coverage) == 0 && len(fixture.Caps) == 0 &&
		fixture.TimezoneBinding == nil && fixture.Timezone == nil && fixture.CalendarBinding == nil && fixture.Calendar == nil {
		return Evaluate(input, fixture.Absolute)
	}
	normalized, reason := NormalizeCivil(input, fixture)
	switch reason {
	case "":
		result := Evaluate(input, normalized.Snapshot)
		for _, exclusion := range normalized.calendarExclusions {
			if slices.ContainsFunc(result.Intervals, func(interval IntervalResult) bool {
				return interval.Legal == Permitted && intersection(interval.Window, exclusion.Window).valid()
			}) {
				if result.CalendarEvidence == nil {
					result.CalendarEvidence = &CalendarEvidence{Pin: normalized.Calendar}
				}
				result.CalendarEvidence.Exclusions = append(result.CalendarEvidence.Exclusions, exclusion)
			}
		}
		return result
	case JurisdictionUnresolved:
		result := newResult(Complete, reason)
		result.Intervals = []IntervalResult{{
			Window: input.Stay.utc(), Legal: Unknown, Reasons: []Reason{{Code: reason}},
		}}
		return result
	case InvalidStayTime, StayLimitExceeded, InvalidTarget:
		return newResult(InvalidInput, reason)
	default:
		return newResult(Failed, reason)
	}
}

func absoluteBoundariesFit(input EvaluationInput, snapshot SyntheticSnapshot) bool {
	windows, ok := preflight(input, snapshot)
	if !ok {
		return false
	}
	_, _, ok = prepareEvents(input.Stay.utc(), snapshot, input.Permits, windows)
	return ok
}

func project(labels Stay, span offsetSpan) (Stay, bool) {
	overlap := intersection(labels, span.labels)
	if !overlap.Start.Before(overlap.End) {
		return Stay{}, false
	}
	return Stay{overlap.Start.Add(-span.offset), overlap.End.Add(-span.offset)}, true
}

func touchesDate(day time.Time, spans []offsetSpan) bool {
	date := Stay{day, day.AddDate(0, 0, 1)}
	return slices.ContainsFunc(spans, func(span offsetSpan) bool {
		overlap := intersection(date, span.labels)
		return overlap.Start.Before(overlap.End)
	})
}

// Validate declared fixture bindings before timezone resolution or expansion.
// Representatives establish the logical rule graph without inventing proof.
func validateCivilFixture(stay Stay, permits PermitInventory, fixture CivilSnapshot) (map[RuleID]bool, map[RuleID]bool, bool, bool) {
	expanded := make(map[RuleID]bool)
	civilIDs := make(map[RuleID]bool)
	schedules := make(map[RuleID]CivilSchedule)
	caps := make(map[RuleID]ContinuousStayCap)
	absolute := fixture.Absolute
	absolute.Rules = slices.Clone(absolute.Rules)
	absoluteIDs := make(map[RuleID]bool)
	for _, rule := range absolute.Rules {
		absoluteIDs[rule.ID] = true
	}
	var lookback bool
	for _, rule := range fixture.Rules {
		schedule := rule.Schedule
		if !schedule.valid() || absoluteIDs[rule.ID] {
			return nil, nil, false, false
		}
		if prior, ok := schedules[rule.ID]; ok && prior != schedule {
			return nil, nil, false, false
		}
		schedules[rule.ID] = schedule
		expanded[rule.ID], civilIDs[rule.ID] = true, true
		lookback = lookback || schedule.Clock.Start > schedule.Clock.End
		absolute.Rules = append(absolute.Rules, SyntheticRule{
			FixtureWindow: FixtureWindow{rule.Target, stay, rule.Evidence},
			ID:            rule.ID, Effect: rule.Effect, Permit: rule.Permit, SubjectTo: rule.SubjectTo,
		})
	}
	for _, coverage := range fixture.Coverage {
		if !coverage.Schedule.valid() || !coverage.Target.exact() ||
			!sameOrientedCurb(coverage.Target, absolute.Target) || !validRefs(coverage.Evidence, true) {
			return nil, nil, false, false
		}
		lookback = lookback || coverage.Schedule.Clock.Start > coverage.Schedule.Clock.End
	}
	for _, cap := range fixture.Caps {
		if absoluteIDs[cap.ID] || civilIDs[cap.ID] || cap.Limit <= 0 ||
			cap.Mode > ContinuousElapsed || !validRefs(cap.CountedFrom, false) ||
			(cap.OccupancyStart != nil && cap.OccupancyStart.IsZero()) {
			return nil, nil, false, false
		}
		if prior, ok := caps[cap.ID]; ok && (prior.Limit != cap.Limit || prior.Mode != cap.Mode ||
			!equalAnchor(prior.OccupancyStart, cap.OccupancyStart) ||
			!slices.Equal(canonical(slices.Clone(prior.CountedFrom)), canonical(slices.Clone(cap.CountedFrom)))) {
			return nil, nil, false, false
		}
		caps[cap.ID], expanded[cap.ID] = cap, true
		absolute.Rules = append(absolute.Rules, SyntheticRule{FixtureWindow: cap.FixtureWindow, ID: cap.ID, Effect: Prohibition})
	}
	_, ok := validateSnapshot(absolute, permits)
	return expanded, civilIDs, lookback, ok
}

func equalAnchor(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == b
	}
	return a.Equal(*b)
}

type civilOutput struct {
	snapshot           SyntheticSnapshot
	budget             workBudget
	fragments          map[RuleID]map[RuleID]Stay
	calendarExclusions []CalendarExclusion
}

func newCivilOutput(input EvaluationInput, absolute SyntheticSnapshot, expanded map[RuleID]bool) civilOutput {
	base := SyntheticSnapshot{
		Target: absolute.Target, Rules: slices.Clone(absolute.Rules), Coverage: slices.Clone(absolute.Coverage),
	}
	for _, premise := range absolute.Restrictions {
		if !expanded[premise.Rule] {
			base.Restrictions = append(base.Restrictions, premise)
		}
	}
	for _, fact := range absolute.Unresolved {
		if !expanded[fact.Rule] {
			base.Unresolved = append(base.Unresolved, fact)
		}
	}
	// The base is a subset of the preflighted absolute collections.
	budget, _ := remainingBudget(input, base)
	// Generated windows, including calendar exclusions carried only as
	// evidence, share the intermediate allowance.
	budget.windows = min(budget.windows, maxIntermediateWindows)
	return civilOutput{snapshot: base, budget: budget, fragments: make(map[RuleID]map[RuleID]Stay)}
}

func (out *civilOutput) addCalendarExclusions(use CalendarUse, resolution calendarResolution, spans []offsetSpan) bool {
	for _, piece := range resolution.excluded {
		for _, span := range spans {
			window, exists := project(piece, span)
			if !exists {
				continue
			}
			if !out.budget.take(1, 0, len(resolution.evidence)) {
				return false
			}
			out.calendarExclusions = append(out.calendarExclusions, CalendarExclusion{
				Use: use, Window: window, EvidenceRefs: canonical(slices.Clone(resolution.evidence)),
			})
		}
	}
	return true
}

func (out *civilOutput) addGap(target SyntheticTarget, window Stay, id RuleID, effect RuleEffect, reason ReasonCode, evidence, extra []EvidenceRef) bool {
	if !out.budget.take(1, 0, len(evidence)) || !out.budget.take(0, 0, len(extra)) {
		return false
	}
	kind := PotentialRestriction
	if effect == Permission {
		kind = PotentialEffectUnknown
	}
	out.snapshot.Unresolved = append(out.snapshot.Unresolved, UnresolvedFact{
		Target: target, Window: &window, Kind: kind, Evidence: joinedEvidence(evidence, extra), origin: id, reason: reason,
	})
	return true
}

func (out *civilOutput) addRule(window Stay, logical RuleID, target SyntheticTarget, effect RuleEffect, permit PermitKey, subjectTo []RuleID, evidence, extra []EvidenceRef, violation ReasonCode) bool {
	if !out.budget.take(1, 1, len(evidence)) || !out.budget.take(0, 0, len(extra)) {
		return false
	}
	id := fragmentID(logical, window)
	if out.fragments[logical] == nil {
		out.fragments[logical] = make(map[RuleID]Stay)
	}
	out.fragments[logical][id] = window
	out.snapshot.Rules = append(out.snapshot.Rules, SyntheticRule{
		FixtureWindow: FixtureWindow{target, window, joinedEvidence(evidence, extra)},
		ID:            id, Effect: effect, Permit: permit, SubjectTo: subjectTo, origin: logical, violation: violation,
	})
	return true
}

func joinedEvidence(evidence, extra []EvidenceRef) []EvidenceRef {
	out := append(slices.Clone(evidence), extra...)
	slices.Sort(out)
	return out
}

func compareCivilWindows(a, b FixtureWindow) int {
	if order := a.Window.Start.Compare(b.Window.Start); order != 0 {
		return order
	}
	if order := a.Window.End.Compare(b.Window.End); order != 0 {
		return order
	}
	if order := cmp.Compare(a.Target.Side, b.Target.Side); order != 0 {
		return order
	}
	return slices.Compare(a.Evidence, b.Evidence)
}

func sortCivilWindows(stay Stay, snapshot SyntheticSnapshot) {
	slices.SortFunc(snapshot.Coverage, compareCivilWindows)
	slices.SortFunc(snapshot.Restrictions, func(a, b RestrictionAssumption) int {
		if order := cmp.Compare(a.Rule, b.Rule); order != 0 {
			return order
		}
		return compareCivilWindows(a.FixtureWindow, b.FixtureWindow)
	})
	slices.SortFunc(snapshot.Unresolved, func(a, b UnresolvedFact) int {
		if order := cmp.Compare(a.Rule, b.Rule); order != 0 {
			return order
		}
		if order := cmp.Compare(a.origin, b.origin); order != 0 {
			return order
		}
		if order := cmp.Compare(a.Kind, b.Kind); order != 0 {
			return order
		}
		if order := cmp.Compare(a.reason, b.reason); order != 0 {
			return order
		}
		return compareCivilWindows(
			FixtureWindow{a.Target, windowOrStay(a.Window, stay), a.Evidence},
			FixtureWindow{b.Target, windowOrStay(b.Window, stay), b.Evidence},
		)
	})
}

func fragmentID(logical RuleID, window Stay) RuleID {
	// Fixed-width UTC endpoint encoding keeps the input unambiguous even
	// when logical identifiers contain punctuation.
	var bounds [24]byte
	binary.BigEndian.PutUint64(bounds[:8], uint64(window.Start.Unix()))
	binary.BigEndian.PutUint32(bounds[8:12], uint32(window.Start.Nanosecond()))
	binary.BigEndian.PutUint64(bounds[12:20], uint64(window.End.Unix()))
	binary.BigEndian.PutUint32(bounds[20:], uint32(window.End.Nanosecond()))
	hash := sha256.New()
	hash.Write([]byte("curbos-civil-fragment-v1\x00"))
	hash.Write([]byte(logical))
	hash.Write(bounds[:])
	return RuleID("civil:" + hex.EncodeToString(hash.Sum(nil)))
}

func (out *civilOutput) addCap(stay Stay, cap ContinuousStayCap) ReasonCode {
	window := intersection(stay, cap.Window.utc())
	if !window.Start.Before(window.End) {
		return ""
	}
	if cap.Mode != ContinuousElapsed || cap.OccupancyStart == nil || len(cap.CountedFrom) == 0 ||
		window != stay || cap.OccupancyStart.After(stay.Start) {
		if !out.addGap(cap.Target, window, cap.ID, Prohibition, StayHistoryUnresolved, cap.Evidence, cap.CountedFrom) {
			return EvaluationLimit
		}
		return ""
	}
	start := cap.OccupancyStart.UTC()
	expiry := start.Add(cap.Limit)
	if !expiry.After(start) || !expiry.Add(-cap.Limit).Equal(start) {
		return SnapshotInvalid
	}
	if !expiry.Before(stay.End) {
		return ""
	}
	window.Start = stay.Start
	if expiry.After(window.Start) {
		window.Start = expiry
	}
	if !out.addRule(window, cap.ID, cap.Target, Prohibition, PermitKey{}, nil, cap.Evidence, cap.CountedFrom, MaxStayExceeded) {
		return EvaluationLimit
	}
	return ""
}

func (out *civilOutput) bindProof(stay Stay, absolute SyntheticSnapshot, expanded map[RuleID]bool) bool {
	for i := range out.snapshot.Rules {
		rule := &out.snapshot.Rules[i]
		var ids []RuleID
		for _, id := range canonical(slices.Clone(rule.SubjectTo)) {
			if !expanded[id] {
				ids = append(ids, id)
				continue
			}
			for fragment, window := range out.fragments[id] {
				if overlap := intersection(rule.Window, window); overlap.Start.Before(overlap.End) {
					ids = append(ids, fragment)
				}
			}
		}
		rule.SubjectTo = canonical(ids)
	}
	for _, assumption := range absolute.Restrictions {
		for id, window := range out.fragments[assumption.Rule] {
			overlap := intersection(assumption.Window, window).utc()
			if !overlap.Start.Before(overlap.End) {
				continue
			}
			if !out.budget.take(1, 0, len(assumption.Evidence)) {
				return false
			}
			bound := assumption
			bound.Rule, bound.Window = id, overlap
			out.snapshot.Restrictions = append(out.snapshot.Restrictions, bound)
		}
	}
	for _, fact := range absolute.Unresolved {
		for id, window := range out.fragments[fact.Rule] {
			overlap := intersection(windowOrStay(fact.Window, stay), window).utc()
			if !overlap.Start.Before(overlap.End) {
				continue
			}
			if !out.budget.take(1, 0, len(fact.Evidence)) {
				return false
			}
			bound := fact
			bound.Rule, bound.Window = id, &overlap
			out.snapshot.Unresolved = append(out.snapshot.Unresolved, bound)
		}
	}
	return true
}
