package regulations

import (
	"crypto/sha256"
	"encoding/binary"
	"strings"
	"time"
)

const (
	maxCivilDeclarations   = 256
	maxCalendarEntries     = 256
	maxCivilDates          = 10
	maxOffsetSpans         = 32
	maxTimezoneBytes       = 256 * 1024
	maxIntermediateWindows = 1024
	civilDay               = 24 * time.Hour // Length of the wall-clock label axis.
)

type TimezonePin struct {
	Name, Version string
	SHA256        [32]byte
}

// SyntheticTimezoneBinding is supplied separately from the bytes as a fixture
// premise. It carries no assertion of verified jurisdiction authority.
type SyntheticTimezoneBinding struct {
	Jurisdiction string
	Pin          TimezonePin
}

type PinnedTimezone struct {
	Pin  TimezonePin
	Data []byte
}

type CivilDate struct {
	Year  int
	Month time.Month
	Day   int
}

func (d CivilDate) midnight() time.Time {
	return time.Date(d.Year, d.Month, d.Day, 0, 0, 0, 0, time.UTC)
}

func (d CivilDate) valid() bool {
	return d.Year >= 1 && d.Year <= 9999 && d == dateOf(d.midnight())
}

func dateOf(t time.Time) CivilDate {
	y, m, d := t.Date()
	return CivilDate{y, m, d}
}

// CivilDateRange uses inclusive From and exclusive Until labels. A zero bound
// is open on that side.
type CivilDateRange struct {
	From, Until CivilDate
}

// LocalWindow endpoints are wall-clock nanoseconds since midnight. AllDay is
// explicit and uses zero endpoints. A later start denotes an overnight span.
type LocalWindow struct {
	Start, End time.Duration
	AllDay     bool
}

func (w LocalWindow) valid() bool {
	return w.Start >= 0 && w.Start < civilDay && w.End >= 0 && w.End < civilDay &&
		(!w.AllDay || (w.Start == 0 && w.End == 0))
}

// Weekdays is a bit set indexed by time.Weekday (Sunday is 0).
type Weekdays uint8

func (w Weekdays) contains(day time.Weekday) bool {
	return w&(1<<day) != 0
}

type CivilCondition uint8

const (
	CivilApplies CivilCondition = iota
	CivilDoesNotApply
	CivilConditionUnresolved
)

type DayCondition uint8

const (
	AnyDay DayCondition = iota
	HolidayOnly
	OrdinaryDayOnly
)

type CivilSchedule struct {
	Weekdays  Weekdays
	Clock     LocalWindow
	Dates     CivilDateRange
	Condition CivilCondition
	Day       DayCondition
	// CalendarRequired declares a dependency even if the calendar is absent.
	CalendarRequired bool
}

func (s CivilSchedule) valid() bool {
	zero := CivilDate{}
	return s.Weekdays != 0 && s.Weekdays < 128 && s.Clock.valid() &&
		s.Condition <= CivilConditionUnresolved && s.Day <= OrdinaryDayOnly &&
		(s.Dates.From == zero || s.Dates.From.valid()) &&
		(s.Dates.Until == zero || s.Dates.Until.valid()) &&
		(s.Dates.From == zero || s.Dates.Until == zero || s.Dates.From.midnight().Before(s.Dates.Until.midnight()))
}

func (s CivilSchedule) onDate(day time.Time) bool {
	zero := CivilDate{}
	return (s.Dates.From == zero || !day.Before(s.Dates.From.midnight())) &&
		(s.Dates.Until == zero || day.Before(s.Dates.Until.midnight()))
}

func loadFixtureTimezone(jurisdiction string, binding *SyntheticTimezoneBinding, zone *PinnedTimezone) (*time.Location, ReasonCode) {
	if binding == nil || binding.Jurisdiction == "" || binding.Pin.Name == "" {
		return nil, JurisdictionUnresolved
	}
	pin := binding.Pin
	if binding.Jurisdiction != jurisdiction || pin.Version == "" || !ianaName(pin.Name) ||
		zone == nil || len(zone.Data) == 0 || zone.Pin != pin || sha256.Sum256(zone.Data) != pin.SHA256 ||
		!orderedTZif(zone.Data) {
		return nil, SnapshotInvalid
	}
	location, err := time.LoadLocationFromTZData(pin.Name, zone.Data)
	if err != nil {
		return nil, SnapshotInvalid
	}
	return location, ""
}

// Go's loader accepts unordered transition instants, but ZoneBounds relies on
// them being strictly ordered. Check the bounded TZif blocks before loading.
func orderedTZif(data []byte) bool {
	if len(data) < 44 {
		return false
	}
	version := data[4]
	switch version {
	case 0:
		_, ok := orderedTZifBlock(data, version, 4)
		return ok
	case '2', '3':
		rest, ok := orderedTZifBlock(data, version, 4)
		if !ok {
			return false
		}
		_, ok = orderedTZifBlock(rest, version, 8)
		return ok
	default:
		return false
	}
}

func orderedTZifBlock(data []byte, version byte, width int64) ([]byte, bool) {
	if len(data) < 44 || string(data[:4]) != "TZif" || data[4] != version {
		return nil, false
	}
	var counts [6]int64
	for i := range counts {
		counts[i] = int64(binary.BigEndian.Uint32(data[20+i*4:]))
	}
	utc, standard, leap, transitions, zones, abbreviations := counts[0], counts[1], counts[2], counts[3], counts[4], counts[5]
	// These counts are uint32-sized, so the products fit int64 independent
	// of the host int width. Bound them by the supplied bytes before slicing.
	size := transitions*(width+1) + zones*6 + abbreviations + leap*(width+4) + standard + utc
	body := data[44:]
	if size > int64(len(body)) {
		return nil, false
	}
	var previous int64
	for i := int64(0); i < transitions; i++ {
		data := body[i*width:]
		var second int64
		if width == 4 {
			second = int64(int32(binary.BigEndian.Uint32(data)))
		} else {
			second = int64(binary.BigEndian.Uint64(data))
		}
		if i > 0 && second <= previous {
			return nil, false
		}
		previous = second
	}
	return body[size:], true
}

func ianaName(name string) bool {
	if name == "Local" {
		return false
	}
	for part := range strings.SplitSeq(name, "/") {
		if part == "" || strings.IndexFunc(part, func(r rune) bool {
			return !(r >= 'A' && r <= 'Z' || r >= 'a' && r <= 'z' || r >= '0' && r <= '9' ||
				r == '_' || r == '+' || r == '-')
		}) >= 0 {
			return false
		}
	}
	return true
}

type offsetSpan struct {
	utc, labels Stay
	offset      time.Duration
}

func offsetSpans(stay Stay, loc *time.Location) ([]offsetSpan, ReasonCode) {
	var spans []offsetSpan
	for cursor := stay.Start; cursor.Before(stay.End); {
		if len(spans) == maxOffsetSpans {
			return nil, EvaluationLimit
		}
		local := cursor.In(loc)
		_, seconds := local.Zone()
		_, end := local.ZoneBounds()
		if end.IsZero() || end.After(stay.End) {
			end = stay.End
		}
		end = end.UTC()
		if !end.After(cursor) {
			return nil, SnapshotInvalid
		}
		// TZif offsets are signed 32-bit seconds. Check the conversion before
		// applying it to the UTC label axis.
		const maxOffsetSeconds = int64((1<<63 - 1) / time.Second)
		if int64(seconds) > maxOffsetSeconds || int64(seconds) < -maxOffsetSeconds {
			return nil, SnapshotInvalid
		}
		offset := time.Duration(seconds) * time.Second
		first, last := cursor.Add(offset), end.Add(offset)
		if !first.Add(-offset).Equal(cursor) || !last.Add(-offset).Equal(end) {
			return nil, SnapshotInvalid
		}
		spans = append(spans, offsetSpan{Stay{cursor, end}, Stay{first, last}, offset})
		cursor = end
	}
	return spans, ""
}

func civilDateEnvelope(spans []offsetSpan, lookback bool) (time.Time, time.Time, ReasonCode) {
	first, last := dateOf(spans[0].labels.Start).midnight(), dateOf(spans[0].labels.End.Add(-1)).midnight()
	for _, span := range spans {
		a, b := dateOf(span.labels.Start).midnight(), dateOf(span.labels.End.Add(-1)).midnight()
		if a.Before(first) {
			first = a
		}
		if b.After(last) {
			last = b
		}
	}
	anchor := first
	if lookback {
		anchor = anchor.AddDate(0, 0, -1)
	}
	if anchor.Year() < 1 || last.Year() > 9999 {
		return time.Time{}, time.Time{}, SnapshotInvalid
	}
	if last.After(anchor.AddDate(0, 0, maxCivilDates-1)) {
		return time.Time{}, time.Time{}, EvaluationLimit
	}
	return first, last, ""
}

func intersection(a, b Stay) Stay {
	if b.Start.After(a.Start) {
		a.Start = b.Start
	}
	if b.End.Before(a.End) {
		a.End = b.End
	}
	return a
}

// scheduleOnDate emits the local-label pieces falling on this date. The early
// part of an overnight occurrence is controlled by the previous weekday.
func scheduleOnDate(schedule CivilSchedule, day time.Time) (pieces []Stay, unsupported bool) {
	if !schedule.onDate(day) || schedule.Condition == CivilDoesNotApply {
		return nil, false
	}
	clock := schedule.Clock
	next := day.AddDate(0, 0, 1)
	if clock.AllDay || clock.Start == clock.End {
		if !schedule.Weekdays.contains(day.Weekday()) {
			return nil, false
		}
		return []Stay{{day, next}}, !clock.AllDay
	}
	if clock.Start < clock.End {
		if schedule.Weekdays.contains(day.Weekday()) {
			return []Stay{{day.Add(clock.Start), day.Add(clock.End)}}, false
		}
		return nil, false
	}
	if clock.End != 0 && schedule.Weekdays.contains(day.AddDate(0, 0, -1).Weekday()) {
		pieces = append(pieces, Stay{day, day.Add(clock.End)})
	}
	if schedule.Weekdays.contains(day.Weekday()) {
		pieces = append(pieces, Stay{day.Add(clock.Start), next})
	}
	return pieces, false
}
