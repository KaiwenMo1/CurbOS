package regulations

import (
	"slices"
	"time"
)

type windowKind uint8

const (
	ruleWindow windowKind = iota
	coverageWindow
	assumptionWindow
	unresolvedWindow
	permitWindow
	windowKinds
)

type event struct {
	at    time.Time
	kind  windowKind
	index int
	start bool
}

type activeWindows [windowKinds][]bool

func newResult(status EvaluationStatus, reasons ...ReasonCode) Result {
	return Result{
		Status: status, Legal: Unknown, Reasons: reasons,
		Cost: NotAssessed, Fit: NotAssessed, Occupancy: NotAssessed, Arrival: NotAssessed,
	}
}

// Evaluate applies the synthetic fixture to one exact target and absolute stay.
// All input validation and event budgets precede the first legal decision.
func Evaluate(input EvaluationInput, snapshot SyntheticSnapshot) Result {
	stay := input.Stay.utc()
	if !stay.valid() {
		return newResult(InvalidInput, InvalidStayTime)
	}
	if stay.End.Sub(stay.Start) > maxStay {
		return newResult(InvalidInput, StayLimitExceeded)
	}
	windows, ok := preflight(input, snapshot)
	if !ok {
		return newResult(Failed, EvaluationLimit)
	}
	snapshot, ok = validateSnapshot(snapshot, input.Permits)
	if !ok {
		return newResult(Failed, SnapshotInvalid)
	}
	events, ok := collectEvents(stay, snapshot, input.Permits, windows)
	if !ok {
		return newResult(Failed, EvaluationLimit)
	}
	slices.SortFunc(events, compareEvents)
	boundaries := 1
	for i := 1; i < len(events); i++ {
		if events[i].at != events[i-1].at {
			boundaries++
			if boundaries > maxBoundaries {
				return newResult(Failed, EvaluationLimit)
			}
		}
	}

	if input.Target.Side > SideRight {
		return newResult(InvalidInput, InvalidTarget)
	}
	if input.Target != snapshot.Target {
		result := newResult(Complete, TargetUnresolved)
		result.Intervals = []IntervalResult{{
			Window: stay, Legal: Unknown, Reasons: []Reason{{Code: TargetUnresolved}},
		}}
		return result
	}
	return sweep(events, boundaries, snapshot, input.Permits)
}

func collectEvents(stay Stay, snapshot SyntheticSnapshot, permits PermitInventory, windows int) ([]event, bool) {
	capacity := 2 + 2*windows // preflight has bounded windows.
	events := make([]event, 0, capacity)
	events = append(events, event{at: stay.Start, kind: windowKinds}, event{at: stay.End, kind: windowKinds})
	add := func(window Stay, kind windowKind, index int) bool {
		window = window.utc()
		if window.Start.Before(stay.Start) {
			window.Start = stay.Start
		}
		if window.End.After(stay.End) {
			window.End = stay.End
		}
		if !window.Start.Before(window.End) {
			return true
		}
		if len(events) > maxEndpoints-2 || len(events) > capacity-2 {
			return false
		}
		events = append(events,
			event{at: window.Start, kind: kind, index: index, start: true},
			event{at: window.End, kind: kind, index: index},
		)
		return true
	}
	for i, rule := range snapshot.Rules {
		if !add(rule.Window, ruleWindow, i) {
			return nil, false
		}
	}
	for i, coverage := range snapshot.Coverage {
		if !add(coverage.Window, coverageWindow, i) {
			return nil, false
		}
	}
	for i, assumption := range snapshot.Restrictions {
		if !add(assumption.Window, assumptionWindow, i) {
			return nil, false
		}
	}
	for i, fact := range snapshot.Unresolved {
		if !add(windowOrStay(fact.Window, stay), unresolvedWindow, i) {
			return nil, false
		}
	}
	for i, permit := range permits.Facts {
		if !add(windowOrStay(permit.Validity, stay), permitWindow, i) {
			return nil, false
		}
	}
	return events, true
}

func windowOrStay(window *Stay, stay Stay) Stay {
	if window != nil {
		return *window
	}
	return stay
}

func compareEvents(a, b event) int {
	if order := a.at.Compare(b.at); order != 0 {
		return order
	}
	if a.start == b.start {
		return 0
	}
	if a.start {
		return 1
	}
	return -1
}

func sweep(events []event, boundaries int, snapshot SyntheticSnapshot, permits PermitInventory) Result {
	active := activeWindows{
		ruleWindow:       make([]bool, len(snapshot.Rules)),
		coverageWindow:   make([]bool, len(snapshot.Coverage)),
		assumptionWindow: make([]bool, len(snapshot.Restrictions)),
		unresolvedWindow: make([]bool, len(snapshot.Unresolved)),
		permitWindow:     make([]bool, len(permits.Facts)),
	}
	result := newResult(Complete)
	result.Legal = Permitted
	result.Intervals = make([]IntervalResult, 0, boundaries-1)
	reasonSet := make(map[ReasonCode]struct{})
	for i := 0; i < len(events); {
		at := events[i].at
		for i < len(events) && events[i].at == at {
			event := events[i]
			if event.kind != windowKinds {
				active[event.kind][event.index] = event.start
			}
			i++
		}
		if i == len(events) {
			break
		}
		interval := prove(Stay{Start: at, End: events[i].at}, active, snapshot, permits)
		result.Intervals = append(result.Intervals, interval)
		for _, reason := range interval.Reasons {
			reasonSet[reason.Code] = struct{}{}
		}
		if interval.Legal == Prohibited || (interval.Legal == Unknown && result.Legal == Permitted) {
			result.Legal = interval.Legal
		}
	}
	if result.Legal == Permitted {
		reasonSet[FullStayAuthorized] = struct{}{}
	}
	for reason := range reasonSet {
		result.Reasons = append(result.Reasons, reason)
	}
	result.Reasons = canonical(result.Reasons)
	return result
}
