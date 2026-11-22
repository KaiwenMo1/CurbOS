package regulations

import (
	"reflect"
	"slices"
	"testing"
	"time"
)

func instant(minute int) time.Time {
	return time.Date(2026, time.January, 12, 14, 0, 0, 0, time.UTC).Add(time.Duration(minute) * time.Minute)
}

func span(start, end int) Stay {
	return Stay{Start: instant(start), End: instant(end)}
}

func premise(target SyntheticTarget, window Stay, evidence EvidenceRef) FixtureWindow {
	return FixtureWindow{Target: target, Window: window, Evidence: []EvidenceRef{evidence}}
}

func syntheticFixture(stay Stay) (EvaluationInput, SyntheticSnapshot) {
	target := SyntheticTarget{
		Resource: "fixture-curb", Geometry: "fixture-geometry-v1", Orientation: "fixture-road-v1",
		Jurisdiction: "fixture-jurisdiction", Side: SideLeft,
	}
	input := EvaluationInput{
		Stay: stay, Target: target,
		Permits: PermitInventory{State: InventoryComplete, Evidence: []EvidenceRef{"fixture-inventory"}},
	}
	snapshot := SyntheticSnapshot{
		Target: target,
		Rules: []SyntheticRule{{
			FixtureWindow: premise(target, stay, "fixture-permission"), ID: "base", Effect: Permission,
		}},
		Coverage: []FixtureWindow{premise(target, stay, "fixture-complete-coverage")},
	}
	return input, snapshot
}

func addRestriction(snapshot *SyntheticSnapshot, id RuleID, effect RuleEffect, window Stay) *SyntheticRule {
	base := &snapshot.Rules[0]
	base.SubjectTo = append(base.SubjectTo, id)
	snapshot.Rules = append(snapshot.Rules, SyntheticRule{
		FixtureWindow: premise(snapshot.Target, window, EvidenceRef("fixture-rule-"+id)),
		ID:            id, Effect: effect,
	})
	snapshot.Restrictions = append(snapshot.Restrictions, RestrictionAssumption{
		FixtureWindow: premise(snapshot.Target, window, EvidenceRef("fixture-assumption-"+id)), Rule: id,
	})
	return &snapshot.Rules[len(snapshot.Rules)-1]
}

func permitFixture() (EvaluationInput, SyntheticSnapshot) {
	input, snapshot := syntheticFixture(span(30, 90))
	rule := addRestriction(&snapshot, "permit-only", PermitOnly, span(0, 180))
	rule.Permit = PermitKey{Class: "fixture-resident", Scope: "fixture-zone", Issuer: "fixture-issuer"}
	validity := span(0, 120)
	input.Permits.Facts = []PermitFact{{
		Key: rule.Permit, State: PermitVerified, Validity: &validity, Evidence: []EvidenceRef{"fixture-permit"},
	}}
	return input, snapshot
}

type intervalWant struct {
	window Stay
	legal  LegalOutcome
}

func want(start, end int, legal LegalOutcome) intervalWant {
	return intervalWant{window: span(start, end), legal: legal}
}

func assertResult(t *testing.T, result Result, status EvaluationStatus, legal LegalOutcome, reasons ...ReasonCode) {
	t.Helper()
	if result.Status != status || result.Legal != legal {
		t.Fatalf("got %s / %s (%v), want %s / %s", result.Status, result.Legal, result.Reasons, status, legal)
	}
	for _, reason := range reasons {
		if !slices.Contains(result.Reasons, reason) {
			t.Errorf("reasons %v missing %s", result.Reasons, reason)
		}
	}
	if status != Complete && (len(result.Intervals) != 0 || !slices.Equal(result.Reasons, reasons)) {
		t.Fatalf("failure returned more than the expected reason: %#v", result)
	}
	if result.Cost != NotAssessed || result.Fit != NotAssessed || result.Occupancy != NotAssessed || result.Arrival != NotAssessed {
		t.Errorf("nonlegal dimensions were assessed: %#v", result)
	}
}

func assertPartition(t *testing.T, result Result, stay Stay) {
	t.Helper()
	start := stay.Start.UTC()
	for _, i := range result.Intervals {
		if i.Window.Start != start || !i.Window.End.After(i.Window.Start) ||
			i.Window.End.Location() != time.UTC || len(i.Reasons) == 0 {
			t.Fatalf("invalid interval following %s: %#v", start, i)
		}
		start = i.Window.End
	}
	if start != stay.End.UTC() {
		t.Fatalf("partition ends at %s, want %s", start, stay.End.UTC())
	}
}

func assertIntervals(t *testing.T, result Result, expected ...intervalWant) {
	t.Helper()
	if len(result.Intervals) != len(expected) {
		t.Fatalf("got %d intervals, want %d: %#v", len(result.Intervals), len(expected), result.Intervals)
	}
	for i, want := range expected {
		got := result.Intervals[i]
		if got.Window != want.window || got.Legal != want.legal {
			t.Errorf("interval %d got %s %v, want %s %v", i, got.Legal, got.Window, want.legal, want.window)
		}
	}
}

func assertEvidence(t *testing.T, interval IntervalResult, refs ...EvidenceRef) {
	t.Helper()
	for _, ref := range refs {
		if !slices.Contains(interval.EvidenceRefs, ref) {
			t.Errorf("evidence %v missing %q", interval.EvidenceRefs, ref)
		}
	}
}

func TestEligibilityMatrix(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*EvaluationInput, *SyntheticSnapshot)
		legal  LegalOutcome
		reason ReasonCode
		wants  []intervalWant
	}{
		{"T01 complete permission", func(*EvaluationInput, *SyntheticSnapshot) {}, Permitted, FullStayAuthorized,
			[]intervalWant{want(0, 60, Permitted)}},
		{"T02 partial restriction", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(20, 40))
		}, Prohibited, ApplicableRestriction, []intervalWant{want(0, 20, Permitted), want(20, 40, Prohibited), want(40, 60, Permitted)}},
		{"T07 opposite side", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			rule := premise(s.Target, span(20, 40), "fixture-other-side")
			rule.Target.Side = SideRight
			s.Rules = append(s.Rules, SyntheticRule{FixtureWindow: rule, ID: "right-ban", Effect: Prohibition})
			s.Coverage = nil
		}, Unknown, SideMismatch, []intervalWant{want(0, 20, Unknown), want(20, 40, Unknown), want(40, 60, Unknown)}},
		{"T12 partial coverage", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Coverage[0].Window.End = instant(40)
		}, Unknown, CoverageMissing, []intervalWant{want(0, 40, Permitted), want(40, 60, Unknown)}},
		{"T13 decisive restriction and unknown tail", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(20, 40))
			s.Coverage[0].Window.End = instant(40)
		}, Prohibited, CoverageMissing, []intervalWant{want(0, 20, Permitted), want(20, 40, Prohibited), want(40, 60, Unknown)}},
		{"T14 missing restriction premise", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(20, 40))
			s.Restrictions = nil
		}, Unknown, CoverageMissing, []intervalWant{want(0, 20, Permitted), want(20, 40, Unknown), want(40, 60, Permitted)}},
		{"T18 unknown oriented side", func(i *EvaluationInput, _ *SyntheticSnapshot) {
			i.Target.Side = SideUnknown
		}, Unknown, TargetUnresolved, []intervalWant{want(0, 60, Unknown)}},
		{"T18 mismatched geometry", func(i *EvaluationInput, _ *SyntheticSnapshot) {
			i.Target.Geometry = "fixture-other-geometry"
		}, Unknown, TargetUnresolved, []intervalWant{want(0, 60, Unknown)}},
		{"T34 end at ban start", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(60, 120))
		}, Permitted, FullStayAuthorized, []intervalWant{want(0, 60, Permitted)}},
		{"T34 start at ban end", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(-60, 0))
		}, Permitted, FullStayAuthorized, []intervalWant{want(0, 60, Permitted)}},
		{"T48 empty coverage", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Coverage = nil
		}, Unknown, CoverageMissing, []intervalWant{want(0, 60, Unknown)}},
		{"T48 disjoint coverage", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Coverage[0].Window = span(60, 120)
		}, Unknown, CoverageMissing, []intervalWant{want(0, 60, Unknown)}},
		{"open override defeats otherwise decisive restriction", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(0, 60))
			s.Unresolved = []UnresolvedFact{{
				Target: s.Target, Kind: PotentialOverride, Rule: "ban", Evidence: []EvidenceRef{"fixture-open-override"},
			}}
		}, Unknown, CoverageMissing, []intervalWant{want(0, 60, Unknown)}},
		{"unconditional competing permission is unresolved", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(0, 60))
			rule := s.Rules[0]
			rule.ID, rule.SubjectTo = "competing-permission", nil
			s.Rules = append(s.Rules, rule)
		}, Unknown, AuthorityConflict, []intervalWant{want(0, 60, Unknown)}},
		{"a potentially restricting fact blocks permission", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Unresolved = []UnresolvedFact{{
				Target: s.Target, Kind: PotentialRestriction, Evidence: []EvidenceRef{"fixture-possible-ban"},
			}}
		}, Unknown, CoverageMissing, []intervalWant{want(0, 60, Unknown)}},
		{"absence of a permission does not prove a ban", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Rules = nil
		}, Unknown, PermissionMissing, []intervalWant{want(0, 60, Unknown)}},
		{"independent restriction survives unrelated unknowns", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			addRestriction(s, "ban", Prohibition, span(0, 60))
			s.Unresolved = []UnresolvedFact{{
				Target: s.Target, Kind: PotentialRestriction, Evidence: []EvidenceRef{"fixture-possible-second-ban"},
			}}
		}, Prohibited, ApplicableRestriction, []intervalWant{want(0, 60, Prohibited)}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			input, snapshot := syntheticFixture(span(0, 60))
			tc.mutate(&input, &snapshot)
			got := Evaluate(input, snapshot)
			assertResult(t, got, Complete, tc.legal, tc.reason) // T20 covers all three legal outcomes.
			assertPartition(t, got, input.Stay)
			assertIntervals(t, got, tc.wants...)
			if tc.legal != Permitted && slices.Contains(got.Reasons, FullStayAuthorized) {
				t.Fatal("full-stay permission leaked into an incomplete proof")
			}
		})
	}
}

func TestIntervalProofReferences(t *testing.T) {
	input, snapshot := syntheticFixture(span(0, 60))
	addRestriction(&snapshot, "ban", Prohibition, span(20, 40))
	snapshot.Coverage[0].Window.End = instant(40)
	got := Evaluate(input, snapshot)
	assertResult(t, got, Complete, Prohibited, ApplicableRestriction, CoverageMissing)
	assertIntervals(t, got, want(0, 20, Permitted), want(20, 40, Prohibited), want(40, 60, Unknown))

	first, ban, tail := got.Intervals[0], got.Intervals[1], got.Intervals[2]
	assertEvidence(t, first, "fixture-permission", "fixture-complete-coverage")
	assertEvidence(t, ban, "fixture-rule-ban", "fixture-assumption-ban")
	if len(ban.RuleRefs) != 2 || ban.RuleRefs[0].ID != "ban" ||
		!slices.Equal(ban.RuleRefs[0].Evidence, []EvidenceRef{"fixture-rule-ban"}) {
		t.Fatalf("missing rule-to-evidence link: %#v", ban.RuleRefs)
	}
	if !slices.Equal(tail.EvidenceRefs, []EvidenceRef{"fixture-permission"}) ||
		!slices.Equal(tail.Reasons, []Reason{{Code: CoverageMissing}}) {
		t.Fatalf("a proof carried across its end: %#v", tail)
	}
}

func TestPermitMatrix(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*PermitInventory, *SyntheticSnapshot)
		legal  LegalOutcome
		reason ReasonCode
		wants  []intervalWant
	}{
		{"T03 matching permit", func(*PermitInventory, *SyntheticSnapshot) {}, Permitted, FullStayAuthorized,
			[]intervalWant{want(30, 90, Permitted)}},
		{"T04 permit expires during stay", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].Validity.End = instant(60)
		}, Prohibited, PermitRequired, []intervalWant{want(30, 60, Permitted), want(60, 90, Prohibited)}},
		{"T05 applicability unknown", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].Key.Scope = ""
			p.Facts[0].State = PermitUnknown
		}, Unknown, PermitUnverified, []intervalWant{want(30, 90, Unknown)}},
		{"T05 validity unknown", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].State, p.Facts[0].Validity = PermitUnknown, nil
		}, Unknown, PermitUnverified, []intervalWant{want(30, 90, Unknown)}},
		{"T05 empty unassessed inventory", func(p *PermitInventory, _ *SyntheticSnapshot) {
			*p = PermitInventory{}
		}, Unknown, PermitUnverified, []intervalWant{want(30, 90, Unknown)}},
		{"explicit empty complete inventory", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts = nil
		}, Prohibited, PermitRequired, []intervalWant{want(30, 90, Prohibited)}},
		{"T06 wrong class", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].Key.Class = "different-class"
		}, Prohibited, PermitRequired, []intervalWant{want(30, 90, Prohibited)}},
		{"T06 wrong scope", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].Key.Scope = "different-scope"
		}, Prohibited, PermitRequired, []intervalWant{want(30, 90, Prohibited)}},
		{"T06 wrong issuer", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.Facts[0].Key.Issuer = "different-issuer"
		}, Prohibited, PermitRequired, []intervalWant{want(30, 90, Prohibited)}},
		{"matched permit satisfies incomplete inventory", func(p *PermitInventory, _ *SyntheticSnapshot) {
			p.State, p.Evidence = InventoryUnknown, nil
		}, Permitted, FullStayAuthorized, []intervalWant{want(30, 90, Permitted)}},
		{"permit alone cannot prove permission", func(_ *PermitInventory, s *SyntheticSnapshot) {
			s.Rules = s.Rules[1:]
		}, Unknown, PermissionMissing, []intervalWant{want(30, 90, Unknown)}},
		{"absence still needs restriction premise", func(p *PermitInventory, s *SyntheticSnapshot) {
			p.Facts, s.Restrictions = nil, nil
		}, Unknown, CoverageMissing, []intervalWant{want(30, 90, Unknown)}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			input, snapshot := permitFixture()
			tc.mutate(&input.Permits, &snapshot)
			got := Evaluate(input, snapshot)
			assertResult(t, got, Complete, tc.legal, tc.reason)
			assertPartition(t, got, input.Stay)
			assertIntervals(t, got, tc.wants...)
			for _, interval := range got.Intervals {
				assertEvidence(t, interval, "fixture-rule-permit-only")
				if interval.Legal == Prohibited {
					assertEvidence(t, interval, "fixture-inventory")
				}
			}
		})
	}
}

func TestPermitEvidenceUsesActiveMatchingFacts(t *testing.T) {
	input, snapshot := permitFixture()
	input.Permits.Facts[0].Validity.End = instant(60)
	matchingKey := input.Permits.Facts[0].Key
	wrongScope := matchingKey
	wrongScope.Scope = "fixture-other-zone"
	inactiveWindow, activeWindow := span(100, 120), input.Stay
	input.Permits.Facts = append(input.Permits.Facts,
		PermitFact{Key: matchingKey, State: PermitVerified, Validity: &inactiveWindow, Evidence: []EvidenceRef{"fixture-inactive-permit"}},
		PermitFact{Key: wrongScope, State: PermitVerified, Validity: &activeWindow, Evidence: []EvidenceRef{"fixture-wrong-scope"}},
		PermitFact{Key: matchingKey, State: PermitVerified, Validity: input.Permits.Facts[0].Validity, Evidence: []EvidenceRef{"fixture-second-match"}},
		PermitFact{Key: matchingKey, State: PermitUnknown, Validity: input.Permits.Facts[0].Validity, Evidence: []EvidenceRef{"fixture-unknown-alternative"}},
	)

	got := Evaluate(input, snapshot)
	assertResult(t, got, Complete, Prohibited, PermitRequired)
	assertIntervals(t, got, want(30, 60, Permitted), want(60, 90, Prohibited))
	for i, want := range [][]EvidenceRef{
		{"fixture-complete-coverage", "fixture-permission", "fixture-permit", "fixture-rule-permit-only", "fixture-second-match"},
		{"fixture-assumption-permit-only", "fixture-complete-coverage", "fixture-inventory", "fixture-permission", "fixture-rule-permit-only"},
	} {
		if !slices.Equal(got.Intervals[i].EvidenceRefs, want) {
			t.Errorf("interval %d evidence = %v, want %v", i, got.Intervals[i].EvidenceRefs, want)
		}
	}

	slices.Reverse(input.Permits.Facts)
	if reordered := Evaluate(input, snapshot); !reflect.DeepEqual(got, reordered) {
		t.Fatal("permit order changed the outcome or evidence")
	}
}

func TestPermitEvidenceExplainsUncertainty(t *testing.T) {
	for _, state := range []PermitInventoryState{InventoryComplete, InventoryUnknown} {
		input, snapshot := permitFixture()
		input.Permits.State = state
		candidate := &input.Permits.Facts[0]
		candidate.State, candidate.Validity = PermitUnknown, nil
		candidate.Key.Scope = ""
		unrelated := *candidate
		unrelated.Key.Class = "fixture-other-class"
		unrelated.Evidence = []EvidenceRef{"fixture-unrelated-unknown"}
		input.Permits.Facts = append(input.Permits.Facts, unrelated)

		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Unknown, PermitUnverified)
		assertIntervals(t, got, want(30, 90, Unknown))
		want := []EvidenceRef{"fixture-complete-coverage", "fixture-permission", "fixture-permit", "fixture-rule-permit-only"}
		if state == InventoryUnknown {
			want = slices.Insert(want, 1, "fixture-inventory")
		}
		if !slices.Equal(got.Intervals[0].EvidenceRefs, want) {
			t.Errorf("inventory state %d evidence = %v, want %v", state, got.Intervals[0].EvidenceRefs, want)
		}
	}
}

func TestExactEvents(t *testing.T) {
	t.Run("T30 equivalent UTC instants", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		rule := addRestriction(&snapshot, "ban", Prohibition, span(25, 35))
		got := Evaluate(input, snapshot)
		local := time.FixedZone("fixture-offset", -5*60*60)
		input.Stay.Start = input.Stay.Start.In(local)
		input.Stay.End = input.Stay.End.In(local)
		rule.Window.Start, rule.Window.End = rule.Window.Start.In(local), rule.Window.End.In(local)
		converted := Evaluate(input, snapshot)
		assertResult(t, converted, Complete, Prohibited, ApplicableRestriction)
		assertIntervals(t, converted, want(0, 25, Permitted), want(25, 35, Prohibited), want(35, 60, Permitted))
		if !reflect.DeepEqual(got, converted) {
			t.Fatal("equivalent instants produced different results")
		}
	})
	for _, duration := range []time.Duration{time.Second, time.Nanosecond} {
		t.Run("T45 "+duration.String(), func(t *testing.T) {
			stay := span(0, 1)
			input, snapshot := syntheticFixture(stay)
			start := stay.Start.Add(29 * time.Second)
			ban := Stay{Start: start, End: start.Add(duration)}
			addRestriction(&snapshot, "short-ban", Prohibition, ban)
			got := Evaluate(input, snapshot)
			assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
			assertPartition(t, got, stay)
			assertIntervals(t, got,
				intervalWant{Stay{stay.Start, ban.Start}, Permitted},
				intervalWant{ban, Prohibited},
				intervalWant{Stay{ban.End, stay.End}, Permitted},
			)
			assertEvidence(t, got.Intervals[1], "fixture-rule-short-ban", "fixture-assumption-short-ban")
		})
	}
	t.Run("T46 coincident starts and ends", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 30))
		snapshot.Rules[0].Window = span(0, 10)
		addRestriction(&snapshot, "ban", Prohibition, span(10, 20))
		snapshot.Rules = append(snapshot.Rules, SyntheticRule{
			FixtureWindow: premise(snapshot.Target, span(20, 30), "fixture-second-permission"),
			ID:            "second-permission", Effect: Permission,
		})
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
		assertPartition(t, got, input.Stay)
		assertIntervals(t, got, want(0, 10, Permitted), want(10, 20, Prohibited), want(20, 30, Permitted))
		assertEvidence(t, got.Intervals[2], "fixture-second-permission")
		if slices.Contains(got.Intervals[2].EvidenceRefs, "fixture-rule-ban") {
			t.Fatal("ended restriction carried into the next interval")
		}
	})
}

func TestT44DeterminismAndProvenance(t *testing.T) {
	input, snapshot := syntheticFixture(span(0, 60))
	addRestriction(&snapshot, "z-restriction", Prohibition, span(0, 20))
	addRestriction(&snapshot, "a-restriction", Prohibition, span(10, 30))
	snapshot.Coverage[0].Window.End = instant(40)
	snapshot.Rules[0].Evidence = []EvidenceRef{"fixture-z", "fixture-a"}
	want := Evaluate(input, snapshot)
	assertResult(t, want, Complete, Prohibited, ApplicableRestriction, CoverageMissing)

	slices.Reverse(snapshot.Rules)
	slices.Reverse(snapshot.Restrictions)
	base := &snapshot.Rules[len(snapshot.Rules)-1]
	slices.Reverse(base.SubjectTo)
	base.Evidence = []EvidenceRef{"fixture-z", "fixture-z", "fixture-a"}
	snapshot.Rules = append(snapshot.Rules, *base)
	snapshot.Restrictions = append(snapshot.Restrictions, snapshot.Restrictions[0])
	got := Evaluate(input, snapshot)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("reordered/duplicated inputs changed result\ngot %#v\nwant %#v", got, want)
	}
	if !slices.Equal(base.Evidence, []EvidenceRef{"fixture-z", "fixture-z", "fixture-a"}) ||
		!slices.Equal(base.SubjectTo, []RuleID{"a-restriction", "z-restriction"}) {
		t.Fatal("evaluation mutated fixture inputs")
	}
	overlap := got.Intervals[1]
	assertEvidence(t, overlap, "fixture-assumption-a-restriction", "fixture-assumption-z-restriction")
	if len(overlap.Reasons) != 2 || overlap.Reasons[0].Rule != "a-restriction" || overlap.Reasons[1].Rule != "z-restriction" {
		t.Fatalf("restriction reasons are not canonical: %v", overlap.Reasons)
	}
	if len(overlap.RuleRefs) != 3 || overlap.RuleRefs[0].ID != "a-restriction" ||
		!slices.Equal(overlap.RuleRefs[1].Evidence, []EvidenceRef{"fixture-a", "fixture-z"}) {
		t.Fatalf("rule references are not canonical: %#v", overlap.RuleRefs)
	}
}
