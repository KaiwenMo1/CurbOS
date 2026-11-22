package regulations

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"slices"
	"time"
	"unicode/utf8"
)

type CalendarPin struct {
	ID, Version string
	SHA256      [32]byte
}

type HolidayMembership uint8

const (
	HolidayUnresolved HolidayMembership = iota
	OrdinaryDay
	Holiday
)

type CalendarDay struct {
	Date       CivilDate
	Membership HolidayMembership
}

type CalendarOperation uint8

const (
	CalendarAdd CalendarOperation = iota + 1
	CalendarRemove
	CalendarReplace
)

type CalendarAnchor uint8

const (
	ActualLocalDate     CalendarAnchor = iota
	OccurrenceStartDate                // Unsupported for exceptions in this slice.
)

type CalendarException struct {
	Rule      RuleID
	Date      CivilDate
	Operation CalendarOperation
	Anchor    CalendarAnchor
	When      DayCondition
	Clock     LocalWindow
	Evidence  []EvidenceRef
}

type SyntheticCalendar struct {
	Pin        CalendarPin
	Days       []CalendarDay
	Exceptions []CalendarException
}

// calendarDigest hashes sorted, individually hashed typed fixture records.
// Reordering the input or a record's references preserves the content digest.
func calendarDigest(calendar *SyntheticCalendar) [32]byte {
	var records [][32]byte
	add := func(kind byte, value any) {
		// Both record types have only JSON-representable fields.
		encoded, _ := json.Marshal(value)
		records = append(records, sha256.Sum256(append([]byte{kind}, encoded...)))
	}
	for _, day := range calendar.Days {
		add('d', day)
	}
	for _, exception := range calendar.Exceptions {
		exception.Evidence = slices.Clone(exception.Evidence)
		slices.Sort(exception.Evidence)
		add('e', exception)
	}
	slices.SortFunc(records, func(a, b [32]byte) int { return bytes.Compare(a[:], b[:]) })
	hash := sha256.New()
	for _, record := range records {
		hash.Write(record[:])
	}
	var digest [32]byte
	hash.Sum(digest[:0])
	return digest
}

type calendarKey struct {
	rule RuleID
	date CivilDate
}

type fixtureCalendar struct {
	pin        CalendarPin
	ready      bool
	days       map[CivilDate]HolidayMembership
	exceptions map[calendarKey][]CalendarException
}

func indexCalendar(expected *CalendarPin, calendar *SyntheticCalendar, civilIDs map[RuleID]bool) (fixtureCalendar, bool) {
	if calendar == nil {
		return fixtureCalendar{}, true
	}
	index := fixtureCalendar{
		days: make(map[CivilDate]HolidayMembership), exceptions: make(map[calendarKey][]CalendarException),
	}
	pin := calendar.Pin
	if expected != nil && pin.ID != "" && pin.Version != "" &&
		pin.ID == expected.ID && pin.Version == expected.Version {
		if pin.SHA256 != expected.SHA256 || pin.SHA256 != calendarDigest(calendar) {
			return fixtureCalendar{}, false
		}
		index.pin, index.ready = pin, true
	}
	for _, day := range calendar.Days {
		if !day.Date.valid() || day.Membership > Holiday {
			return fixtureCalendar{}, false
		}
		membership, exists := index.days[day.Date]
		if !exists {
			index.days[day.Date] = day.Membership
		} else if membership != day.Membership {
			index.days[day.Date] = HolidayUnresolved
		}
	}
	for _, exception := range calendar.Exceptions {
		if !civilIDs[exception.Rule] || !utf8.ValidString(string(exception.Rule)) ||
			!exception.Date.valid() || !exception.Clock.valid() ||
			exception.When > OrdinaryDayOnly || !validRefs(exception.Evidence, true) ||
			slices.ContainsFunc(exception.Evidence, func(ref EvidenceRef) bool { return !utf8.ValidString(string(ref)) }) {
			return fixtureCalendar{}, false
		}
		key := calendarKey{exception.Rule, exception.Date}
		index.exceptions[key] = append(index.exceptions[key], exception)
	}
	return index, true
}

func matchesDay(condition DayCondition, membership HolidayMembership) (applies, known bool) {
	switch {
	case condition == AnyDay:
		return true, true
	case membership == HolidayUnresolved:
		return false, false
	case condition == HolidayOnly:
		return membership == Holiday, true
	default:
		return membership == OrdinaryDay, true
	}
}

func exceptionWindow(date time.Time, clock LocalWindow) (Stay, bool) {
	if clock.AllDay {
		return Stay{date, date.AddDate(0, 0, 1)}, true
	}
	return Stay{date.Add(clock.Start), date.Add(clock.End)}, clock.Start < clock.End
}

type calendarResolution struct {
	windows   []Stay
	evidence  []EvidenceRef
	reason    ReasonCode
	operation CalendarOperation
}

// resolve applies a single distinct effective operation to one actual date.
// Conflicting operations and unsupported anchoring remain unknown.
func (c fixtureCalendar) resolve(rule RuleID, schedule CivilSchedule, day time.Time, base []Stay) calendarResolution {
	date := dateOf(day)
	exceptions := c.exceptions[calendarKey{rule, date}]
	wholeDay := Stay{day, day.AddDate(0, 0, 1)}
	if !c.ready && (schedule.CalendarRequired || schedule.Day != AnyDay || len(exceptions) > 0) {
		if schedule.CalendarRequired || len(exceptions) > 0 {
			var refs []EvidenceRef
			for _, exception := range exceptions {
				refs = append(refs, exception.Evidence...)
			}
			return calendarResolution{windows: []Stay{wholeDay}, evidence: refs, reason: CalendarUnresolved}
		}
		return calendarResolution{windows: base, reason: CalendarUnresolved}
	}

	// An unsupported start-date operation might affect the continuation
	// on the next date. Keep its uncertainty within that possible scope.
	var refs []EvidenceRef
	if schedule.Clock.Start > schedule.Clock.End && schedule.Clock.End != 0 {
		previous := dateOf(day.AddDate(0, 0, -1))
		for _, exception := range c.exceptions[calendarKey{rule, previous}] {
			if exception.Anchor != ActualLocalDate {
				refs = append(refs, exception.Evidence...)
			}
		}
	}
	ambiguous := len(refs) > 0
	whole := ambiguous
	// There are at most two base pieces and one additional candidate per
	// admitted exception. A removal splits each base piece at most once.
	possible := slices.Clone(base)
	var chosen CalendarException
	for _, exception := range exceptions {
		applies, known := matchesDay(exception.When, c.days[date])
		if known && !applies {
			continue
		}
		refs = append(refs, exception.Evidence...)
		window, bounded := exceptionWindow(day, exception.Clock)
		if !bounded || exception.Anchor != ActualLocalDate ||
			exception.Operation < CalendarAdd || exception.Operation > CalendarReplace {
			ambiguous, whole = true, true
			continue
		}
		if exception.Operation != CalendarRemove {
			possible = append(possible, window)
		}
		if !known {
			ambiguous = true
			continue
		}
		if chosen.Operation != 0 && (chosen.Operation != exception.Operation || chosen.Clock != exception.Clock) {
			ambiguous = true
		}
		chosen = exception
	}
	applies, known := matchesDay(schedule.Day, c.days[date])
	if ambiguous || !known {
		if whole {
			return calendarResolution{windows: []Stay{wholeDay}, evidence: refs, reason: CalendarUnresolved}
		}
		return calendarResolution{windows: possible, evidence: refs, reason: CalendarUnresolved}
	}
	if !applies {
		base = nil
	}
	switch chosen.Operation {
	case CalendarAdd:
		window, _ := exceptionWindow(day, chosen.Clock)
		base = append(base, window)
	case CalendarRemove:
		window, _ := exceptionWindow(day, chosen.Clock)
		base = removeWindow(base, window)
	case CalendarReplace:
		window, _ := exceptionWindow(day, chosen.Clock)
		base = []Stay{window}
	}
	return calendarResolution{windows: base, evidence: refs, operation: chosen.Operation}
}

func removeWindow(windows []Stay, remove Stay) []Stay {
	var retained []Stay
	for _, window := range windows {
		overlap := intersection(window, remove)
		if !overlap.Start.Before(overlap.End) {
			retained = append(retained, window)
			continue
		}
		if window.Start.Before(overlap.Start) {
			retained = append(retained, Stay{window.Start, overlap.Start})
		}
		if overlap.End.Before(window.End) {
			retained = append(retained, Stay{overlap.End, window.End})
		}
	}
	return retained
}
