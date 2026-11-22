package regulations

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"os"
	"os/exec"
	"reflect"
	"slices"
	"testing"
	"time"
)

func civilClock(hour, minute int) time.Duration {
	return time.Duration(hour)*time.Hour + time.Duration(minute)*time.Minute
}

func civilAt(year int, month time.Month, day, hour, minute int) time.Time {
	return time.Date(year, month, day, hour, minute, 0, 0, time.UTC)
}

func testSchedule(days Weekdays, start, end time.Duration) CivilSchedule {
	return CivilSchedule{Weekdays: days, Clock: LocalWindow{Start: start, End: end}}
}

type fixtureTransition struct {
	at   time.Time
	zone byte
}

// Synthetic TZif v1 data with two offsets and explicitly supplied transitions.
func fixtureTZif(first, second int32, transitions ...fixtureTransition) []byte {
	data := make([]byte, 20)
	copy(data, "TZif")
	for _, count := range []uint32{0, 0, 0, uint32(len(transitions)), 2, 8} {
		data = binary.BigEndian.AppendUint32(data, count)
	}
	for _, transition := range transitions {
		data = binary.BigEndian.AppendUint32(data, uint32(transition.at.Unix()))
	}
	for _, transition := range transitions {
		data = append(data, transition.zone)
	}
	data = binary.BigEndian.AppendUint32(data, uint32(first))
	data = append(data, 0, 0)
	data = binary.BigEndian.AppendUint32(data, uint32(second))
	data = append(data, 1, 4)
	return append(data, "EST\x00EDT\x00"...)
}

func setZone(fixture *CivilSnapshot, data []byte) {
	pin := TimezonePin{Name: "America/New_York", Version: "synthetic-v1", SHA256: sha256.Sum256(data)}
	fixture.TimezoneBinding = &SyntheticTimezoneBinding{Jurisdiction: fixture.Absolute.Target.Jurisdiction, Pin: pin}
	fixture.Timezone = &PinnedTimezone{Pin: pin, Data: data}
}

func fixtureTZifV2(first, second int32, transitions ...fixtureTransition) []byte {
	base := fixtureTZif(first, second, transitions...)
	base[4] = '2'
	data := append(slices.Clone(base), base[:44]...)
	for _, transition := range transitions {
		data = binary.BigEndian.AppendUint64(data, uint64(transition.at.Unix()))
	}
	data = append(data, base[44+4*len(transitions):]...)
	return append(data, '\n', '\n')
}

func civilFixture(stay Stay, schedule CivilSchedule) (EvaluationInput, CivilSnapshot) {
	input, absolute := syntheticFixture(stay)
	target := absolute.Target
	absolute.Rules[0].SubjectTo = []RuleID{"civil-ban"}
	absolute.Restrictions = []RestrictionAssumption{{
		FixtureWindow: premise(target, stay, "fixture-civil-assumption"), Rule: "civil-ban",
	}}
	fixture := CivilSnapshot{Absolute: absolute, Rules: []CivilRule{{
		CivilWindow: CivilWindow{target, schedule, []EvidenceRef{"fixture-civil-rule"}},
		ID:          "civil-ban", Effect: Prohibition,
	}}}
	setZone(&fixture, fixtureTZif(-5*3600, -4*3600,
		fixtureTransition{civilAt(2026, time.March, 8, 7, 0), 1},
		fixtureTransition{civilAt(2026, time.November, 1, 6, 0), 0},
	))
	return input, fixture
}

func normalizeFixture(t *testing.T, input EvaluationInput, fixture CivilSnapshot) CivilNormalization {
	t.Helper()
	normalized, reason := NormalizeCivil(input, fixture)
	if reason != "" {
		t.Fatalf("normalize: %s", reason)
	}
	return normalized
}

func assertFragments(t *testing.T, normalized CivilNormalization, logical RuleID, want ...Stay) {
	t.Helper()
	var got []Stay
	for _, rule := range normalized.Snapshot.Rules {
		if rule.origin == logical {
			got = append(got, rule.Window)
		}
	}
	slices.SortFunc(got, func(a, b Stay) int { return a.Start.Compare(b.Start) })
	if !slices.Equal(got, want) {
		t.Fatalf("fragments = %v, want %v", got, want)
	}
}

func TestCivilOvernightAndDates(t *testing.T) {
	for _, tc := range []struct {
		name    string
		stay    Stay
		weekday time.Weekday
		dates   CivilDateRange
		legal   LegalOutcome
	}{
		{"T21 Monday overnight", Stay{civilAt(2026, 1, 13, 4, 30), civilAt(2026, 1, 13, 5, 30)}, time.Monday, CivilDateRange{}, Prohibited},
		{"T21 month rollover", Stay{civilAt(2026, 2, 1, 4, 30), civilAt(2026, 2, 1, 5, 30)}, time.Saturday, CivilDateRange{}, Prohibited},
		{"T22 Sunday to Monday", Stay{civilAt(2026, 1, 19, 4, 30), civilAt(2026, 1, 19, 5, 30)}, time.Sunday, CivilDateRange{}, Prohibited},
		{"T22 request entirely in continuation", Stay{civilAt(2026, 1, 19, 5, 0), civilAt(2026, 1, 19, 5, 30)}, time.Sunday, CivilDateRange{}, Prohibited},
		{"T22 Monday is not the overnight anchor", Stay{civilAt(2026, 1, 19, 5, 0), civilAt(2026, 1, 19, 5, 30)}, time.Monday, CivilDateRange{}, Permitted},
		{"T22 year rollover", Stay{civilAt(2029, 1, 1, 4, 30), civilAt(2029, 1, 1, 5, 30)}, time.Sunday, CivilDateRange{}, Prohibited},
		{"T25 continuation on inclusive date", Stay{civilAt(2026, 1, 13, 5, 0), civilAt(2026, 1, 13, 6, 0)}, time.Monday,
			CivilDateRange{CivilDate{2026, 1, 13}, CivilDate{2026, 1, 14}}, Prohibited},
		{"T25 continuation on exclusive date", Stay{civilAt(2026, 1, 14, 5, 0), civilAt(2026, 1, 14, 6, 0)}, time.Tuesday,
			CivilDateRange{CivilDate{2026, 1, 13}, CivilDate{2026, 1, 14}}, Permitted},
	} {
		t.Run(tc.name, func(t *testing.T) {
			schedule := testSchedule(1<<tc.weekday, civilClock(22, 0), civilClock(6, 0))
			schedule.Dates = tc.dates
			input, fixture := civilFixture(tc.stay, schedule)
			n := normalizeFixture(t, input, fixture)
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, tc.legal)
			assertPartition(t, got, tc.stay)
			if tc.legal == Permitted {
				assertFragments(t, n, "civil-ban")
				assertIntervals(t, got, intervalWant{tc.stay, Permitted})
				return
			}
			for _, interval := range got.Intervals {
				if interval.Legal != Prohibited {
					t.Fatalf("overnight restriction lost: %#v", interval)
				}
				assertEvidence(t, interval, "fixture-civil-rule", "fixture-civil-assumption")
			}
			if tc.stay.Start.UTC().Hour() == 5 {
				assertFragments(t, n, "civil-ban", tc.stay)
			} else {
				midnight := time.Date(tc.stay.Start.Year(), tc.stay.Start.Month(), tc.stay.Start.Day(), 5, 0, 0, 0, time.UTC)
				assertFragments(t, n, "civil-ban", Stay{tc.stay.Start, midnight}, Stay{midnight, tc.stay.End})
			}
		})
	}

	t.Run("T25 ordinary date range", func(t *testing.T) {
		schedule := testSchedule(127, 0, time.Hour)
		schedule.Dates = CivilDateRange{CivilDate{2026, 1, 13}, CivilDate{2026, 1, 14}}
		for _, day := range []int{13, 14} {
			stay := Stay{civilAt(2026, 1, day, 5, 0), civilAt(2026, 1, day, 6, 0)}
			input, fixture := civilFixture(stay, schedule)
			if day == 13 {
				assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban", stay)
				assertResult(t, EvaluateCivil(input, fixture), Complete, Prohibited, ApplicableRestriction)
			} else {
				assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban")
				assertResult(t, EvaluateCivil(input, fixture), Complete, Permitted, FullStayAuthorized)
			}
		}
	})
}

func TestT23WeekdaysAndAllDay(t *testing.T) {
	schedule := testSchedule(0b0111110, civilClock(10, 0), civilClock(11, 0))
	for _, day := range []int{12, 17} {
		stay := Stay{civilAt(2026, 1, day, 15, 15), civilAt(2026, 1, day, 15, 45)}
		input, fixture := civilFixture(stay, schedule)
		if day == 12 {
			assertResult(t, EvaluateCivil(input, fixture), Complete, Prohibited, ApplicableRestriction)
			assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban", stay)
		} else {
			assertResult(t, EvaluateCivil(input, fixture), Complete, Permitted, FullStayAuthorized)
			assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban")
		}
	}
	stay := Stay{civilAt(2026, 11, 1, 4, 0), civilAt(2026, 11, 2, 5, 0)}
	transition := civilAt(2026, 11, 1, 6, 0)
	schedule = CivilSchedule{Weekdays: 1 << time.Sunday, Clock: LocalWindow{AllDay: true}}
	input, fixture := civilFixture(stay, schedule)
	assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban", Stay{stay.Start, transition}, Stay{transition, stay.End})
	got := EvaluateCivil(input, fixture)
	assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
	assertIntervals(t, got, intervalWant{Stay{stay.Start, transition}, Prohibited}, intervalWant{Stay{transition, stay.End}, Prohibited})

	fixture.Rules[0].Schedule.Clock.AllDay = false
	assertResult(t, EvaluateCivil(input, fixture), Complete, Unknown, UnsupportedRule)
	fixture.Rules[0].Schedule.Clock.End = time.Hour
	fixture.Rules[0].Schedule.Condition = CivilConditionUnresolved
	assertResult(t, EvaluateCivil(input, fixture), Complete, Unknown, UnsupportedRule)
	fixture.Rules[0].Schedule.Condition = CivilDoesNotApply
	assertResult(t, EvaluateCivil(input, fixture), Complete, Permitted, FullStayAuthorized)
}

func TestCivilDST(t *testing.T) {
	spring := func(h, m int) time.Time { return civilAt(2026, 3, 8, h, m) }
	fall := func(h, m int) time.Time { return civilAt(2026, 11, 1, h, m) }
	cases := []struct {
		name      string
		stay      Stay
		clock     LocalWindow
		fragments []Stay
		intervals []intervalWant
		legal     LegalOutcome
	}{
		{"T26 skipped labels", Stay{spring(6, 50), spring(7, 10)}, LocalWindow{Start: civilClock(2, 10), End: civilClock(2, 50)}, nil,
			[]intervalWant{{Stay{spring(6, 50), spring(7, 10)}, Permitted}}, Permitted},
		{"T27 straddling gap", Stay{spring(6, 50), spring(7, 10)}, LocalWindow{Start: civilClock(1, 55), End: civilClock(3, 5)},
			[]Stay{{spring(6, 55), spring(7, 0)}, {spring(7, 0), spring(7, 5)}}, []intervalWant{
				{Stay{spring(6, 50), spring(6, 55)}, Permitted}, {Stay{spring(6, 55), spring(7, 0)}, Prohibited},
				{Stay{spring(7, 0), spring(7, 5)}, Prohibited}, {Stay{spring(7, 5), spring(7, 10)}, Permitted},
			}, Prohibited},
		{"T28 first fold", Stay{fall(5, 22), fall(5, 28)}, LocalWindow{Start: civilClock(1, 20), End: civilClock(1, 30)},
			[]Stay{{fall(5, 22), fall(5, 28)}}, []intervalWant{{Stay{fall(5, 22), fall(5, 28)}, Prohibited}}, Prohibited},
		{"T28 second fold", Stay{fall(6, 22), fall(6, 28)}, LocalWindow{Start: civilClock(1, 20), End: civilClock(1, 30)},
			[]Stay{{fall(6, 22), fall(6, 28)}}, []intervalWant{{Stay{fall(6, 22), fall(6, 28)}, Prohibited}}, Prohibited},
		{"T28 both folds", Stay{fall(5, 15), fall(6, 35)}, LocalWindow{Start: civilClock(1, 20), End: civilClock(1, 30)},
			[]Stay{{fall(5, 20), fall(5, 30)}, {fall(6, 20), fall(6, 30)}}, []intervalWant{
				{Stay{fall(5, 15), fall(5, 20)}, Permitted}, {Stay{fall(5, 20), fall(5, 30)}, Prohibited},
				{Stay{fall(5, 30), fall(6, 20)}, Permitted}, {Stay{fall(6, 20), fall(6, 30)}, Prohibited},
				{Stay{fall(6, 30), fall(6, 35)}, Permitted},
			}, Prohibited},
		{"T29 no false bridge", Stay{fall(5, 35), fall(6, 15)}, LocalWindow{Start: civilClock(1, 20), End: civilClock(1, 30)}, nil,
			[]intervalWant{{Stay{fall(5, 35), fall(6, 15)}, Permitted}}, Permitted},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			input, fixture := civilFixture(tc.stay, CivilSchedule{Weekdays: 1 << time.Sunday, Clock: tc.clock})
			n := normalizeFixture(t, input, fixture)
			assertFragments(t, n, "civil-ban", tc.fragments...)
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, tc.legal)
			assertIntervals(t, got, tc.intervals...)
			for _, interval := range got.Intervals {
				if interval.Legal != Prohibited {
					continue
				}
				assertEvidence(t, interval, "fixture-civil-rule", "fixture-civil-assumption")
				if !slices.ContainsFunc(interval.RuleRefs, func(ref RuleReference) bool { return ref.OriginalID == "civil-ban" }) {
					t.Fatal("fragment lost its logical rule identity")
				}
			}
		})
	}
}

func attachCalendar(fixture *CivilSnapshot, calendar SyntheticCalendar) {
	calendar.Pin = CalendarPin{ID: "fixture-calendar", Version: "synthetic-v1", SHA256: calendarDigest(&calendar)}
	pin := calendar.Pin
	fixture.Calendar, fixture.CalendarBinding = &calendar, &pin
}

func holidayFixture(stay Stay, operation CalendarOperation, clock LocalWindow) (EvaluationInput, CivilSnapshot) {
	input, fixture := civilFixture(stay, testSchedule(0b0111110, civilClock(10, 0), civilClock(11, 0)))
	date := CivilDate{2026, 1, 20}
	attachCalendar(&fixture, SyntheticCalendar{
		Days: []CalendarDay{{date, Holiday}},
		Exceptions: []CalendarException{{
			Rule: "civil-ban", Date: date, Operation: operation, When: HolidayOnly,
			Clock: clock, Evidence: []EvidenceRef{"fixture-holiday-exception"},
		}},
	})
	return input, fixture
}

func TestT24CalendarExceptions(t *testing.T) {
	at := func(h, m int) time.Time { return civilAt(2026, 1, 20, h, m) }
	window := func(h1, m1, h2, m2 int) Stay { return Stay{at(h1, m1), at(h2, m2)} }
	for _, tc := range []struct {
		name   string
		op     CalendarOperation
		clock  LocalWindow
		stay   Stay
		pieces []Stay
		legal  LegalOutcome
	}{
		{"remove", CalendarRemove, LocalWindow{Start: civilClock(10, 0), End: civilClock(11, 0)}, window(15, 15, 15, 45), nil, Permitted},
		{"add", CalendarAdd, LocalWindow{Start: civilClock(11, 0), End: civilClock(12, 0)}, window(16, 15, 16, 45), []Stay{window(16, 15, 16, 45)}, Prohibited},
		{"replace", CalendarReplace, LocalWindow{Start: civilClock(10, 30), End: civilClock(11, 30)}, window(15, 15, 15, 45), []Stay{window(15, 30, 15, 45)}, Prohibited},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input, fixture := holidayFixture(tc.stay, tc.op, tc.clock)
			n := normalizeFixture(t, input, fixture)
			if n.Calendar != fixture.Calendar.Pin {
				t.Fatal("normalization dropped the calendar pin")
			}
			if !slices.Equal(n.AppliedCalendar, []CalendarUse{{"civil-ban", CivilDate{2026, 1, 20}, tc.op}}) {
				t.Fatal("normalization lost the applied operation's source key")
			}
			assertFragments(t, n, "civil-ban", tc.pieces...)
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, tc.legal)
			assertPartition(t, got, tc.stay)
			switch tc.op {
			case CalendarRemove:
				assertCalendarExclusion(t, got, fixture, tc.stay, CalendarRemove)
			case CalendarReplace:
				assertCalendarExclusion(t, got, fixture, window(15, 15, 15, 30), CalendarReplace)
			case CalendarAdd:
				if got.CalendarEvidence != nil {
					t.Fatal("calendar addition was cited as a restriction exclusion")
				}
			}
			if tc.legal == Prohibited {
				assertEvidence(t, got.Intervals[len(got.Intervals)-1], "fixture-holiday-exception")
			}
		})
	}

	for _, variant := range []string{"unknown membership", "unsupported anchor", "unsupported version", "conflicting operations"} {
		t.Run(variant, func(t *testing.T) {
			input, fixture := holidayFixture(window(15, 15, 15, 45), CalendarRemove,
				LocalWindow{Start: civilClock(10, 0), End: civilClock(11, 0)})
			calendar := *fixture.Calendar
			switch variant {
			case "unknown membership":
				calendar.Days = nil
			case "unsupported anchor":
				calendar.Exceptions[0].Anchor = OccurrenceStartDate
			case "conflicting operations":
				other := calendar.Exceptions[0]
				other.Operation = CalendarAdd
				calendar.Exceptions = append(calendar.Exceptions, other)
			}
			attachCalendar(&fixture, calendar)
			if variant == "unsupported version" {
				fixture.Calendar.Pin.Version = "unreviewed-v2"
			}
			n := normalizeFixture(t, input, fixture)
			assertFragments(t, n, "civil-ban")
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, Unknown, CalendarUnresolved)
			assertIntervals(t, got, intervalWant{input.Stay, Unknown})
			assertEvidence(t, got.Intervals[0], "fixture-civil-rule", "fixture-holiday-exception")
			if got.CalendarEvidence != nil {
				t.Fatal("unresolved calendar produced exclusion evidence")
			}
		})
	}

	t.Run("integrity mismatch", func(t *testing.T) {
		input, fixture := holidayFixture(window(15, 15, 15, 45), CalendarRemove, LocalWindow{AllDay: true})
		fixture.Calendar.Days[0].Membership = OrdinaryDay
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Failed, Unknown, SnapshotInvalid)
		if got.CalendarEvidence != nil || len(got.Intervals) != 0 {
			t.Fatal("invalid pin produced partial proof")
		}
	})

	t.Run("date exception on overnight continuation", func(t *testing.T) {
		stay := Stay{civilAt(2026, 1, 19, 4, 30), civilAt(2026, 1, 19, 5, 30)}
		midnight := civilAt(2026, 1, 19, 5, 0)
		input, fixture := civilFixture(stay, testSchedule(1<<time.Sunday, civilClock(22, 0), civilClock(6, 0)))
		attachCalendar(&fixture, SyntheticCalendar{Exceptions: []CalendarException{{
			Rule: "civil-ban", Date: CivilDate{2026, 1, 19}, Operation: CalendarRemove,
			Clock: LocalWindow{Start: 0, End: time.Hour}, Evidence: []EvidenceRef{"fixture-continuation-removal"},
		}}})
		assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban", Stay{stay.Start, midnight})
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
		assertIntervals(t, got, intervalWant{Stay{stay.Start, midnight}, Prohibited}, intervalWant{Stay{midnight, stay.End}, Permitted})
	})
}

func assertCalendarExclusion(t *testing.T, got Result, fixture CivilSnapshot, window Stay, operation CalendarOperation) {
	t.Helper()
	want := &CalendarEvidence{Pin: fixture.Calendar.Pin, Exclusions: []CalendarExclusion{{
		Use: CalendarUse{"civil-ban", CivilDate{2026, 1, 20}, operation}, Window: window,
		EvidenceRefs: []EvidenceRef{"fixture-holiday-exception"},
	}}}
	if !reflect.DeepEqual(got.CalendarEvidence, want) {
		t.Fatalf("calendar evidence = %+v, want %+v", got.CalendarEvidence, want)
	}
}

func TestCalendarExclusionProvenance(t *testing.T) {
	stay := Stay{civilAt(2026, 1, 20, 15, 15), civilAt(2026, 1, 20, 15, 30)}
	t.Run("replacement enables full stay", func(t *testing.T) {
		input, fixture := holidayFixture(stay, CalendarReplace, LocalWindow{Start: civilClock(10, 30), End: civilClock(11, 30)})
		calendar := fixture.Calendar
		calendar.Exceptions = append(calendar.Exceptions, calendar.Exceptions[0])
		attachCalendar(&fixture, *calendar)
		fixture.Rules = append(fixture.Rules, fixture.Rules[0])
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Permitted, FullStayAuthorized)
		assertIntervals(t, got, intervalWant{stay, Permitted})
		assertCalendarExclusion(t, got, fixture, stay, CalendarReplace)

		attachCalendar(&fixture, SyntheticCalendar{Days: calendar.Days})
		got = EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
		if got.CalendarEvidence != nil {
			t.Fatal("calendar with no exceptions produced exclusion evidence")
		}
	})
	t.Run("same-date removal outside the stay", func(t *testing.T) {
		stay := Stay{civilAt(2026, 1, 20, 16, 0), civilAt(2026, 1, 20, 16, 30)}
		input, fixture := holidayFixture(stay, CalendarRemove, LocalWindow{Start: civilClock(10, 30), End: civilClock(11, 0)})
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Permitted, FullStayAuthorized)
		if got.CalendarEvidence != nil {
			t.Fatal("out-of-stay exclusion was cited")
		}
	})
	t.Run("missing independent permission", func(t *testing.T) {
		input, fixture := holidayFixture(stay, CalendarRemove, LocalWindow{AllDay: true})
		fixture.Absolute.Rules = nil
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Unknown, PermissionMissing)
		if got.CalendarEvidence != nil {
			t.Fatal("exclusion was cited as proof without permission")
		}
	})
}

func TestT37TimezonePins(t *testing.T) {
	t.Run("ordered TZif v2", func(t *testing.T) {
		stay := Stay{civilAt(2026, 11, 1, 5, 15), civilAt(2026, 11, 1, 6, 35)}
		input, fixture := civilFixture(stay, testSchedule(127, civilClock(1, 20), civilClock(1, 30)))
		setZone(&fixture, fixtureTZifV2(-18000, -14400,
			fixtureTransition{civilAt(2026, 3, 8, 7, 0), 1}, fixtureTransition{civilAt(2026, 11, 1, 6, 0), 0},
		))
		assertFragments(t, normalizeFixture(t, input, fixture), "civil-ban",
			Stay{civilAt(2026, 11, 1, 5, 20), civilAt(2026, 11, 1, 5, 30)},
			Stay{civilAt(2026, 11, 1, 6, 20), civilAt(2026, 11, 1, 6, 30)},
		)
	})
	for _, tc := range []struct {
		name   string
		change func(*CivilSnapshot)
		status EvaluationStatus
		reason ReasonCode
	}{
		{"unresolved binding", func(f *CivilSnapshot) { f.TimezoneBinding = nil }, Complete, JurisdictionUnresolved},
		{"missing pinned zone", func(f *CivilSnapshot) { f.Timezone = nil }, Failed, SnapshotInvalid},
		{"missing bytes", func(f *CivilSnapshot) { f.Timezone.Data = nil }, Failed, SnapshotInvalid},
		{"inconsistent name", func(f *CivilSnapshot) { f.Timezone.Pin.Name = "Etc/UTC" }, Failed, SnapshotInvalid},
		{"inconsistent version", func(f *CivilSnapshot) { f.Timezone.Pin.Version = "synthetic-v2" }, Failed, SnapshotInvalid},
		{"inconsistent jurisdiction", func(f *CivilSnapshot) { f.TimezoneBinding.Jurisdiction = "fixture-other" }, Failed, SnapshotInvalid},
		{"digest mismatch", func(f *CivilSnapshot) { f.Timezone.Data[0] = 0 }, Failed, SnapshotInvalid},
		{"matching digest over corrupt bytes", func(f *CivilSnapshot) { setZone(f, []byte("invalid TZif")) }, Failed, SnapshotInvalid},
		{"matching digest over unordered transitions", func(f *CivilSnapshot) {
			setZone(f, fixtureTZif(-18000, -14400, fixtureTransition{instant(20), 1}, fixtureTransition{instant(10), 0}))
		}, Failed, SnapshotInvalid},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input, fixture := civilFixture(span(0, 60), testSchedule(127, civilClock(9, 0), civilClock(10, 0)))
			tc.change(&fixture)
			n, reason := NormalizeCivil(input, fixture)
			if reason != tc.reason || !reflect.DeepEqual(n, CivilNormalization{}) {
				t.Fatalf("normalization = %#v / %s", n, reason)
			}
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, tc.status, Unknown, tc.reason)
			if tc.status == Complete {
				assertIntervals(t, got, intervalWant{input.Stay, Unknown})
			}
		})
	}
}

func TestT56HostTimezoneIndependence(t *testing.T) {
	if os.Getenv("CURBOS_CIVIL_FIXTURE_CHILD") == "1" {
		spring := Stay{civilAt(2026, 3, 8, 6, 50), civilAt(2026, 3, 8, 7, 10)}
		fall := Stay{civilAt(2026, 11, 1, 5, 15), civilAt(2026, 11, 1, 6, 35)}
		holiday := Stay{civilAt(2026, 1, 20, 15, 15), civilAt(2026, 1, 20, 15, 45)}
		inputA, fixtureA := civilFixture(spring, testSchedule(127, civilClock(1, 55), civilClock(3, 5)))
		inputB, fixtureB := civilFixture(fall, testSchedule(127, civilClock(1, 20), civilClock(1, 30)))
		inputC, fixtureC := holidayFixture(holiday, CalendarRemove, LocalWindow{AllDay: true})
		inputs, fixtures := []EvaluationInput{inputA, inputB, inputC}, []CivilSnapshot{fixtureA, fixtureB, fixtureC}
		for i, input := range inputs {
			n := normalizeFixture(t, input, fixtures[i])
			result := EvaluateCivil(input, fixtures[i])
			if err := json.NewEncoder(os.Stdout).Encode([]any{n, result}); err != nil {
				t.Fatal(err)
			}
		}
		os.Exit(0)
	}
	run := func(zone string) []byte {
		t.Helper()
		cmd := exec.Command(os.Args[0], "-test.run", "^TestT56HostTimezoneIndependence$")
		cmd.Env = append(os.Environ(), "TZ="+zone, "CURBOS_CIVIL_FIXTURE_CHILD=1")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("host timezone %s: %v\n%s", zone, err, out)
		}
		return out
	}
	utc, nonUTC := run("UTC"), run("America/Los_Angeles")
	if len(utc) == 0 || !slices.Equal(utc, nonUTC) {
		t.Fatal("normalized fixtures or proof results changed with host timezone")
	}
}
