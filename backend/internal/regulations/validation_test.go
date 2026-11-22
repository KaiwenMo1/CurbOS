package regulations

import (
	"fmt"
	"os/exec"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestStayValidation(t *testing.T) {
	local := time.FixedZone("fixture-offset", 3600)
	for _, tc := range []struct {
		name string
		stay Stay
	}{
		{"zero start", Stay{End: instant(60)}},
		{"zero end", Stay{Start: instant(0)}},
		{"equal", span(0, 0)},
		{"equal instants with different locations", Stay{instant(0).In(local), instant(0)}},
		{"reversed", span(60, 0)},
	} {
		t.Run("T35 "+tc.name, func(t *testing.T) {
			input, snapshot := syntheticFixture(span(0, 60))
			input.Stay = tc.stay
			assertResult(t, Evaluate(input, snapshot), InvalidInput, Unknown, InvalidStayTime)
		})
	}
	t.Run("T36 duration limit", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 168*60))
		result := Evaluate(input, snapshot)
		assertResult(t, result, Complete, Permitted, FullStayAuthorized)
		assertIntervals(t, result, want(0, 168*60, Permitted))
		input.Stay.End = input.Stay.End.Add(time.Nanosecond)
		assertResult(t, Evaluate(input, snapshot), InvalidInput, Unknown, StayLimitExceeded)
	})
}

func TestT47WorkBudgets(t *testing.T) {
	t.Run("rule limit", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		atLimit := snapshot.Rules[0]
		for i := 1; i < 256; i++ {
			rule := atLimit
			rule.ID = RuleID(fmt.Sprintf("fixture-%03d", i))
			snapshot.Rules = append(snapshot.Rules, rule)
		}
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Permitted, FullStayAuthorized)
		assertIntervals(t, got, want(0, 60, Permitted))
		if len(got.Intervals[0].RuleRefs) != 256 {
			t.Fatal("rule references were truncated at the limit")
		}
		atLimit.ID = "fixture-extra-rule"
		snapshot.Rules = append(snapshot.Rules, atLimit)
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)
	})
	t.Run("raw and endpoint limit with two unique boundaries", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		want := Evaluate(input, snapshot)
		snapshot.Coverage = slices.Repeat(snapshot.Coverage, 1023)
		windows, ok := preflight(input, snapshot)
		if !ok || windows != 1024 {
			t.Fatalf("preflight returned %d windows, %v", windows, ok)
		}
		events, ok := collectEvents(input.Stay, snapshot, input.Permits, windows)
		if !ok || len(events) != 2050 {
			t.Fatalf("collection produced %d endpoint entries, %v", len(events), ok)
		}
		for _, event := range events {
			if event.at != input.Stay.Start && event.at != input.Stay.End {
				t.Fatalf("unexpected boundary %s", event.at)
			}
		}
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Permitted, FullStayAuthorized)
		if !reflect.DeepEqual(got, want) {
			t.Fatal("duplicate windows changed the proof")
		}
		snapshot.Coverage = append(snapshot.Coverage, snapshot.Coverage[0])
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)
	})
	t.Run("all raw window kinds count before a decisive restriction", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		rule := addRestriction(&snapshot, "ban", Prohibition, input.Stay)
		snapshot.Rules = []SyntheticRule{*rule}
		snapshot.Coverage = slices.Repeat(snapshot.Coverage, 340)
		input.Permits.Facts = make([]PermitFact, 340) // Unknown permits with implicit whole-stay windows.
		outside := span(-60, -30)
		disjoint := UnresolvedFact{Target: snapshot.Target, Window: &outside, Evidence: []EvidenceRef{"fixture-disjoint"}}
		whole := UnresolvedFact{
			Target: snapshot.Target, Kind: PotentialRestriction, Evidence: []EvidenceRef{"fixture-possible-extra-ban"},
		}
		snapshot.Unresolved = slices.Repeat([]UnresolvedFact{disjoint, whole}, 171)
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
		assertIntervals(t, got, want(0, 60, Prohibited))
		for _, extra := range []UnresolvedFact{disjoint, whole} {
			excess := snapshot
			excess.Unresolved = append(slices.Clone(snapshot.Unresolved), extra)
			assertResult(t, Evaluate(input, excess), Failed, Unknown, EvaluationLimit)
		}
		input.Permits.Facts = append(input.Permits.Facts, PermitFact{})
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)
	})
	t.Run("unique boundary limit", func(t *testing.T) {
		stay := Stay{instant(0), instant(0).Add(1023 * time.Second)}
		input, snapshot := syntheticFixture(stay)
		snapshot.Coverage = nil
		for i := 0; i < 1023; i += 2 {
			start := stay.Start.Add(time.Duration(i) * time.Second)
			snapshot.Coverage = append(snapshot.Coverage, premise(snapshot.Target, Stay{start, start.Add(time.Second)}, "fixture-gapped"))
		}
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Unknown, CoverageMissing)
		assertPartition(t, got, stay)
		if len(got.Intervals) != 1023 {
			t.Fatalf("got %d intervals at the unique boundary limit", len(got.Intervals))
		}

		snapshot.Coverage = append(snapshot.Coverage, premise(snapshot.Target,
			Stay{stay.Start.Add(time.Second), stay.Start.Add(1500 * time.Millisecond)}, "fixture-one-extra-boundary"))
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)

		// The restriction adds no new boundaries and would decide the first
		// interval, but the complete event set still exceeds the budget.
		addRestriction(&snapshot, "early-ban", Prohibition, Stay{stay.Start, stay.Start.Add(time.Second)})
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)
	})
	t.Run("evidence reference limit", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		want := Evaluate(input, snapshot)
		// One coverage and one inventory reference are also counted.
		snapshot.Rules[0].Evidence = slices.Repeat(snapshot.Rules[0].Evidence, 2046)
		got := Evaluate(input, snapshot)
		assertResult(t, got, Complete, Permitted, FullStayAuthorized)
		if !reflect.DeepEqual(got, want) {
			t.Fatal("duplicate references changed the proof")
		}
		snapshot.Rules[0].Evidence = append(snapshot.Rules[0].Evidence, snapshot.Rules[0].Evidence[0])
		assertResult(t, Evaluate(input, snapshot), Failed, Unknown, EvaluationLimit)
	})
	t.Run("large raw windows rejected without sweep allocation", func(t *testing.T) {
		input, snapshot := syntheticFixture(span(0, 60))
		snapshot.Coverage = slices.Repeat(snapshot.Coverage, 1<<16)
		var result Result
		allocs := testing.AllocsPerRun(10, func() { result = Evaluate(input, snapshot) })
		assertResult(t, result, Failed, Unknown, EvaluationLimit)
		if allocs > 1 { // The returned failure reason slice is the only allocation.
			t.Fatalf("raw preflight rejection allocated %.2f times", allocs)
		}
	})
}

func TestT48CorruptionFailsClosed(t *testing.T) {
	for _, tc := range []struct {
		name   string
		mutate func(*EvaluationInput, *SyntheticSnapshot)
	}{
		{"zero endpoint", func(_ *EvaluationInput, s *SyntheticSnapshot) { s.Coverage[0].Window.Start = time.Time{} }},
		{"empty window", func(_ *EvaluationInput, s *SyntheticSnapshot) { s.Coverage[0].Window = span(30, 30) }},
		{"reversed window", func(_ *EvaluationInput, s *SyntheticSnapshot) { s.Coverage[0].Window = span(50, 40) }},
		{"later disjoint malformed window", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Unresolved = []UnresolvedFact{
				{Target: s.Target, Window: &Stay{instant(120), instant(100)}, Evidence: []EvidenceRef{"fixture-late"}},
			}
		}},
		{"missing evidence binding", func(_ *EvaluationInput, s *SyntheticSnapshot) { s.Rules[0].Evidence = nil }},
		{"wrong geometry in assumption", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Restrictions[0].Target.Geometry = "fixture-other-geometry"
		}},
		{"dangling restriction assumption", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			s.Restrictions[0].Rule = "fixture-missing-rule"
		}},
		{"conflicting duplicate rule", func(_ *EvaluationInput, s *SyntheticSnapshot) {
			rule := s.Rules[1]
			rule.Window = span(30, 50)
			s.Rules = append(s.Rules, rule)
		}},
		{"verified permit without validity", func(i *EvaluationInput, _ *SyntheticSnapshot) {
			i.Permits.Facts = []PermitFact{{
				State: PermitVerified, Key: PermitKey{Class: "fixture-class", Scope: "fixture-scope", Issuer: "fixture-issuer"},
				Evidence: []EvidenceRef{"fixture-permit"},
			}}
		}},
		{"unknown permit cannot be narrowed without evidence", func(i *EvaluationInput, _ *SyntheticSnapshot) {
			i.Permits.Facts = []PermitFact{{Validity: &Stay{instant(90), instant(120)}}}
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			input, snapshot := syntheticFixture(span(0, 60))
			addRestriction(&snapshot, "early-ban", Prohibition, span(0, 15))
			tc.mutate(&input, &snapshot)
			assertResult(t, Evaluate(input, snapshot), Failed, Unknown, SnapshotInvalid)
		})
	}
}

func TestT53SyntheticTrustBoundary(t *testing.T) {
	input, snapshot := syntheticFixture(span(0, 60))
	snapshot.Coverage = nil
	snapshot.Rules[0].Evidence = []EvidenceRef{"fixture-approved-true"}
	assertResult(t, Evaluate(input, snapshot), Complete, Unknown, CoverageMissing)

	const path = "github.com/KaiwenMo1/CurbOS/backend/internal/regulations"
	list := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("go", append([]string{"list"}, args...)...)
		cmd.Dir = "../.."
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("inspect Go package graph: %v\n%s", err, out)
		}
		return string(out)
	}
	if fields := strings.Fields(list("-deps", "./cmd/...")); slices.Contains(fields, path) {
		t.Fatal("a runtime command depends on the synthetic evaluator")
	}
	if fields := strings.Fields(list("-deps", "-f", "{{if not .Standard}}{{.ImportPath}}{{end}}", "./internal/regulations")); !slices.Equal(fields, []string{path}) {
		t.Fatalf("synthetic evaluator has nonstandard package dependencies: %v", fields)
	}
}
