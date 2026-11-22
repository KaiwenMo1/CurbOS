package regulations

import (
	"reflect"
	"slices"
	"testing"
	"time"
)

func capFixture(stay Stay, anchor time.Time) (EvaluationInput, CivilSnapshot) {
	input, absolute := syntheticFixture(stay)
	absolute.Rules[0].SubjectTo = []RuleID{"cap"}
	absolute.Restrictions = []RestrictionAssumption{{
		FixtureWindow: premise(absolute.Target, stay, "fixture-cap-assumption"), Rule: "cap",
	}}
	return input, CivilSnapshot{Absolute: absolute, Caps: []ContinuousStayCap{{
		FixtureWindow: premise(absolute.Target, stay, "fixture-cap"), ID: "cap", Limit: time.Hour,
		OccupancyStart: &anchor, Mode: ContinuousElapsed, CountedFrom: []EvidenceRef{"fixture-occupancy-anchor"},
	}}}
}

func TestT31T32ContinuousStay(t *testing.T) {
	for _, tc := range []struct {
		name  string
		start time.Time
		extra time.Duration
	}{
		{"T31 exactly at cap", instant(0), 0},
		{"T31 one nanosecond over", instant(0), time.Nanosecond},
		{"T31 one minute over", instant(0), time.Minute},
		{"T32 fold exactly at cap", civilAt(2026, 11, 1, 5, 0), 0},
		{"T32 fold one minute over", civilAt(2026, 11, 1, 5, 0), time.Minute},
	} {
		t.Run(tc.name, func(t *testing.T) {
			expiry := tc.start.Add(time.Hour)
			stay := Stay{tc.start, expiry.Add(tc.extra)}
			input, fixture := capFixture(stay, tc.start)
			n := normalizeFixture(t, input, fixture)
			got := EvaluateCivil(input, fixture)
			if tc.extra == 0 {
				assertFragments(t, n, "cap")
				assertResult(t, got, Complete, Permitted, FullStayAuthorized)
				assertIntervals(t, got, intervalWant{stay, Permitted})
				return
			}
			tail := Stay{expiry, stay.End}
			assertFragments(t, n, "cap", tail)
			assertResult(t, got, Complete, Prohibited, MaxStayExceeded)
			assertIntervals(t, got, intervalWant{Stay{stay.Start, expiry}, Permitted}, intervalWant{tail, Prohibited})
			assertEvidence(t, got.Intervals[1], "fixture-occupancy-anchor", "fixture-cap", "fixture-cap-assumption")
			if !slices.ContainsFunc(got.Intervals[1].RuleRefs, func(ref RuleReference) bool { return ref.OriginalID == "cap" }) {
				t.Fatal("cap lost its logical rule identity")
			}

			fixture.Absolute.Coverage = nil
			got = EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, Prohibited, MaxStayExceeded)
			assertIntervals(t, got, intervalWant{Stay{stay.Start, expiry}, Unknown}, intervalWant{tail, Prohibited})
		})
	}
	t.Run("occupancy started before request arrival", func(t *testing.T) {
		input, fixture := capFixture(span(30, 90), instant(0))
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Prohibited, MaxStayExceeded)
		assertIntervals(t, got, want(30, 60, Permitted), want(60, 90, Prohibited))
	})
}

func TestT33UnresolvedStayHistory(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(*ContinuousStayCap)
	}{
		{"missing anchor", func(cap *ContinuousStayCap) { cap.OccupancyStart = nil }},
		{"required prior dwell or unsupported reset", func(cap *ContinuousStayCap) { cap.Mode = StayHistoryUnknown }},
		{"missing continuity premise", func(cap *ContinuousStayCap) { cap.CountedFrom = nil }},
		{"anchor after arrival", func(cap *ContinuousStayCap) {
			anchor := instant(30)
			cap.OccupancyStart = &anchor
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input, fixture := capFixture(span(0, 30), instant(0))
			tc.change(&fixture.Caps[0])
			assertFragments(t, normalizeFixture(t, input, fixture), "cap")
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, Unknown, StayHistoryUnresolved)
			assertIntervals(t, got, want(0, 30, Unknown))
			assertEvidence(t, got.Intervals[0], "fixture-cap")
		})
	}
	t.Run("partial accumulation window", func(t *testing.T) {
		input, fixture := capFixture(span(0, 30), instant(0))
		fixture.Caps[0].Window.End = instant(15)
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Unknown, StayHistoryUnresolved)
		assertIntervals(t, got, want(0, 15, Unknown), want(15, 30, Permitted))
	})
	t.Run("unproven exemption premise", func(t *testing.T) {
		input, fixture := capFixture(span(0, 61), instant(0))
		fixture.Absolute.Restrictions = nil
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Unknown, CoverageMissing)
		assertIntervals(t, got, want(0, 60, Permitted), want(60, 61, Unknown))
	})
}

func TestFragmentIdentityAndRebinding(t *testing.T) {
	at := func(h, m int) time.Time { return civilAt(2026, 11, 1, h, m) }
	stay := Stay{at(5, 15), at(6, 35)}
	input, fixture := civilFixture(stay, testSchedule(127, civilClock(1, 20), civilClock(1, 30)))
	other := fixture.Rules[0]
	other.ID, other.Evidence = "fixture-civil-permission", []EvidenceRef{"fixture-other-permission"}
	other.Effect, other.SubjectTo = Permission, []RuleID{"civil-ban"}
	fixture.Rules = append(fixture.Rules, other)
	secondOccurrence := Stay{at(6, 20), at(6, 30)}
	fixture.Absolute.Unresolved = []UnresolvedFact{{
		Target: fixture.Absolute.Target, Rule: "civil-ban", Kind: PotentialOverride,
		Window: &secondOccurrence, Evidence: []EvidenceRef{"fixture-second-fold-override"},
	}}
	n := normalizeFixture(t, input, fixture)
	assertFragments(t, n, "civil-ban", Stay{at(5, 20), at(5, 30)}, secondOccurrence)
	proof := EvaluateCivil(input, fixture)
	assertResult(t, proof, Complete, Prohibited, ApplicableRestriction, CoverageMissing)
	assertIntervals(t, proof,
		intervalWant{Stay{at(5, 15), at(5, 20)}, Permitted},
		intervalWant{Stay{at(5, 20), at(5, 30)}, Prohibited},
		intervalWant{Stay{at(5, 30), at(6, 20)}, Permitted},
		intervalWant{secondOccurrence, Unknown},
		intervalWant{Stay{at(6, 30), at(6, 35)}, Permitted},
	)
	assertEvidence(t, proof.Intervals[3], "fixture-civil-rule", "fixture-second-fold-override", "fixture-civil-assumption")
	slices.Reverse(fixture.Rules)
	if got := normalizeFixture(t, input, fixture); !reflect.DeepEqual(n, got) {
		t.Fatal("reordering declarations changed normalized records")
	}

	fixture.Rules = append(fixture.Rules, fixture.Rules[1])
	duplicate := normalizeFixture(t, input, fixture)
	if len(duplicate.Snapshot.Rules) != len(n.Snapshot.Rules)+2 {
		t.Fatal("duplicate raw fragments were filtered before admission")
	}
	if got := EvaluateCivil(input, fixture); !reflect.DeepEqual(got, proof) {
		t.Fatal("duplicate declarations changed the proof")
	}
	fixture.Rules[len(fixture.Rules)-1].Schedule.Clock.End++
	assertResult(t, EvaluateCivil(input, fixture), Failed, Unknown, SnapshotInvalid)
}

func TestT55CivilAdmissionBudgets(t *testing.T) {
	excess := func(t *testing.T, input EvaluationInput, fixture CivilSnapshot) {
		t.Helper()
		n, reason := NormalizeCivil(input, fixture)
		if reason != EvaluationLimit || !reflect.DeepEqual(n, CivilNormalization{}) {
			t.Fatalf("overflow returned %#v / %s", n, reason)
		}
		assertResult(t, EvaluateCivil(input, fixture), Failed, Unknown, EvaluationLimit)
	}
	coverageOnly := func(fixture *CivilSnapshot, schedule CivilSchedule) {
		fixture.Absolute.Rules, fixture.Absolute.Restrictions, fixture.Absolute.Coverage = nil, nil, nil
		fixture.Rules = nil
		fixture.Coverage = []CivilWindow{{fixture.Absolute.Target, schedule, []EvidenceRef{"fixture-civil-coverage"}}}
	}

	t.Run("shared raw and intermediate windows", func(t *testing.T) {
		start := civilAt(2026, 1, 12, 15, 0)
		stay := Stay{start, start.Add(168 * time.Hour)}
		schedule := testSchedule(127, civilClock(9, 0), civilClock(11, 0))
		input, fixture := civilFixture(stay, schedule)
		coverageOnly(&fixture, schedule)
		fixture.Coverage = slices.Repeat(fixture.Coverage, 128)
		n := normalizeFixture(t, input, fixture)
		if len(n.Snapshot.Coverage) != 1024 {
			t.Fatalf("normalized %d windows at limit", len(n.Snapshot.Coverage))
		}
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Unknown, PermissionMissing)
		assertPartition(t, got, stay)
		fixture.Absolute.Coverage = []FixtureWindow{premise(fixture.Absolute.Target, stay, "fixture-extra")}
		excess(t, input, fixture)
	})
	t.Run("raw declarations", func(t *testing.T) {
		schedule := CivilSchedule{Weekdays: 127, Clock: LocalWindow{AllDay: true}}
		input, fixture := civilFixture(span(0, 60), schedule)
		coverageOnly(&fixture, schedule)
		fixture.Coverage = slices.Repeat(fixture.Coverage, 256)
		n := normalizeFixture(t, input, fixture)
		if len(n.Snapshot.Coverage) != 256 {
			t.Fatal("raw limit fixture was truncated")
		}
		fixture.Coverage = append(fixture.Coverage, fixture.Coverage[0])
		excess(t, input, fixture)
	})
	t.Run("calendar entries", func(t *testing.T) {
		input, fixture := civilFixture(span(0, 60), testSchedule(127, civilClock(9, 0), civilClock(10, 0)))
		calendar := SyntheticCalendar{Days: slices.Repeat([]CalendarDay{{CivilDate{2026, 1, 12}, OrdinaryDay}}, 256)}
		attachCalendar(&fixture, calendar)
		normalizeFixture(t, input, fixture)
		calendar.Days = append(calendar.Days, calendar.Days[0])
		attachCalendar(&fixture, calendar)
		excess(t, input, fixture)
	})
	t.Run("timezone bytes", func(t *testing.T) {
		input, fixture := civilFixture(span(0, 60), testSchedule(127, civilClock(9, 0), civilClock(10, 0)))
		data := make([]byte, 256*1024)
		copy(data, fixture.Timezone.Data)
		setZone(&fixture, data)
		normalizeFixture(t, input, fixture)
		setZone(&fixture, append(data, 0))
		excess(t, input, fixture)
	})
	t.Run("offset spans", func(t *testing.T) {
		schedule := CivilSchedule{Weekdays: 127, Clock: LocalWindow{AllDay: true}}
		input, fixture := civilFixture(span(0, 60), schedule)
		var shifts []fixtureTransition
		for i := 1; i < 32; i++ {
			shifts = append(shifts, fixtureTransition{instant(i), byte(i % 2)})
		}
		setZone(&fixture, fixtureTZif(0, 3600, shifts...))
		if n := normalizeFixture(t, input, fixture); len(n.Snapshot.Rules) != 33 {
			t.Fatal("offset span fixture did not reach 32 fragments")
		}
		shifts = append(shifts, fixtureTransition{instant(32), 0})
		setZone(&fixture, fixtureTZif(0, 3600, shifts...))
		excess(t, input, fixture)
	})
	t.Run("date horizon including overnight lookback", func(t *testing.T) {
		start := civilAt(2026, 1, 12, 23, 30)
		stay := Stay{start, start.Add(168 * time.Hour)}
		schedule := testSchedule(127, civilClock(22, 0), civilClock(6, 0))
		input, fixture := civilFixture(stay, schedule)
		shift := fixtureTransition{start.Add(24 * time.Hour), 1}
		// Synthetic date-line jumps exercise the envelope guard.
		setZone(&fixture, fixtureTZif(0, 24*3600, shift))
		normalizeFixture(t, input, fixture)
		setZone(&fixture, fixtureTZif(0, 48*3600, shift))
		excess(t, input, fixture)
	})
	t.Run("expanded rule limit", func(t *testing.T) {
		start := civilAt(2026, 1, 12, 5, 0)
		stay := Stay{start, start.Add(48 * time.Hour)}
		input, fixture := civilFixture(stay, testSchedule(127, civilClock(9, 0), civilClock(10, 0)))
		base := fixture.Absolute.Rules[0]
		base.SubjectTo = nil
		fixture.Absolute.Rules, fixture.Absolute.Restrictions = nil, nil
		fixture.Rules[0].Effect = Permission
		fixture.Rules = slices.Repeat(fixture.Rules, 128)
		if n := normalizeFixture(t, input, fixture); len(n.Snapshot.Rules) != 256 {
			t.Fatal("rule fixture did not reach 256 normalized records")
		}
		fixture.Absolute.Rules = []SyntheticRule{base}
		excess(t, input, fixture)
	})
	t.Run("expanded evidence reference limit", func(t *testing.T) {
		start := civilAt(2026, 1, 12, 5, 0)
		stay := Stay{start, start.Add(48 * time.Hour)}
		schedule := testSchedule(127, civilClock(9, 0), civilClock(10, 0))
		input, fixture := civilFixture(stay, schedule)
		coverageOnly(&fixture, schedule)
		fixture.Coverage[0].Evidence = slices.Repeat(fixture.Coverage[0].Evidence, 1023)
		input.Permits.Evidence = append(input.Permits.Evidence, "fixture-second-inventory")
		n := normalizeFixture(t, input, fixture)
		if len(n.Snapshot.Coverage) != 2 {
			t.Fatal("expected two expanded coverage windows")
		}
		input.Permits.Evidence = append(input.Permits.Evidence, "fixture-extra-inventory")
		excess(t, input, fixture)
	})
	t.Run("unique boundary limit after expansion", func(t *testing.T) {
		start := instant(0)
		stay := Stay{start, start.Add(1023 * time.Second)}
		schedule := testSchedule(127, civilClock(9, 0), civilClock(9, 0)+time.Second)
		input, fixture := civilFixture(stay, schedule)
		coverageOnly(&fixture, schedule)
		for i := 0; i < 1023; i += 2 {
			a := start.Add(time.Duration(i) * time.Second)
			fixture.Absolute.Coverage = append(fixture.Absolute.Coverage,
				premise(fixture.Absolute.Target, Stay{a, a.Add(time.Second)}, "fixture-gapped"))
		}
		normalizeFixture(t, input, fixture)
		fixture.Coverage[0].Schedule.Clock = LocalWindow{Start: civilClock(9, 0) + time.Second, End: civilClock(9, 0) + 1500*time.Millisecond}
		excess(t, input, fixture)
	})
}

func TestT57AbsolutePathRegression(t *testing.T) {
	input, snapshot := permitFixture()
	input.Permits.Facts[0].Validity.End = instant(60)
	addRestriction(&snapshot, "fixture-ns-ban", Prohibition, Stay{instant(40), instant(40).Add(time.Nanosecond)})
	snapshot.Coverage[0].Window.End = instant(70)
	direct := Evaluate(input, snapshot)
	assertResult(t, direct, Complete, Prohibited, PermitRequired, ApplicableRestriction, CoverageMissing)
	if wrapped := EvaluateCivil(input, CivilSnapshot{Absolute: snapshot}); !reflect.DeepEqual(wrapped, direct) {
		t.Fatal("civil adapter altered the absolute proof")
	}
	snapshot.Coverage[0].Window.Start = snapshot.Coverage[0].Window.End
	direct = Evaluate(input, snapshot)
	assertResult(t, direct, Failed, Unknown, SnapshotInvalid)
	if wrapped := EvaluateCivil(input, CivilSnapshot{Absolute: snapshot}); !reflect.DeepEqual(wrapped, direct) {
		t.Fatal("civil adapter altered absolute failure")
	}
}
