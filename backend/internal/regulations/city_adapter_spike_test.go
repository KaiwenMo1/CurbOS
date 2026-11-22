package regulations

import (
	"crypto/sha256"
	"slices"
	"testing"
	"time"
)

// This spike tests whether two synthetic cities can map reviewed fixture
// premises to the existing types through one path. The premises here are
// authored by the test. A source decoder cannot establish them on its own.
type syntheticCityProfile struct {
	target   SyntheticTarget
	zone     string
	tzif     []byte
	schedule CivilSchedule
}

func adaptSyntheticCity(stay Stay, city syntheticCityProfile) (EvaluationInput, CivilSnapshot) {
	const restriction RuleID = "fixture-restriction"
	evidence := func(kind string) EvidenceRef { return EvidenceRef(city.target.Jurisdiction + "/" + kind) }
	pin := TimezonePin{Name: city.zone, Version: "synthetic-v1", SHA256: sha256.Sum256(city.tzif)}
	return EvaluationInput{Stay: stay, Target: city.target}, CivilSnapshot{
		TimezoneBinding: &SyntheticTimezoneBinding{Jurisdiction: city.target.Jurisdiction, Pin: pin},
		Timezone:        &PinnedTimezone{Pin: pin, Data: city.tzif},
		Rules: []CivilRule{{
			CivilWindow: CivilWindow{city.target, city.schedule, []EvidenceRef{evidence("source-rule")}},
			ID:          restriction, Effect: Prohibition,
		}},
		Absolute: SyntheticSnapshot{
			Target: city.target,
			Rules: []SyntheticRule{{
				FixtureWindow: premise(city.target, stay, evidence("fixture-permission")),
				ID:            "fixture-base", Effect: Permission, SubjectTo: []RuleID{restriction},
			}},
			Coverage: []FixtureWindow{premise(city.target, stay, evidence("fixture-coverage"))},
			Restrictions: []RestrictionAssumption{{
				FixtureWindow: premise(city.target, stay, evidence("fixture-restriction-review")), Rule: restriction,
			}},
		},
	}
}

func TestSyntheticCityAdapterSpike(t *testing.T) {
	at := func(h, m int) time.Time { return civilAt(2026, time.November, 1, h, m) }
	stay := Stay{at(5, 15), at(6, 35)}
	east := syntheticCityProfile{
		target: SyntheticTarget{"fixture-curb", "fixture-geometry-v1", "fixture-orientation-v1", "synthetic-east", SideLeft},
		zone:   "America/New_York",
		tzif: fixtureTZif(-18000, -14400,
			fixtureTransition{civilAt(2026, time.March, 8, 7, 0), 1}, fixtureTransition{at(6, 0), 0}),
		schedule: testSchedule(1<<time.Sunday, civilClock(1, 20), civilClock(1, 30)),
	}
	west := syntheticCityProfile{
		target:   SyntheticTarget{"fixture-curb", "fixture-geometry-v1", "fixture-orientation-v1", "synthetic-west", SideRight},
		zone:     "Etc/GMT+8",
		tzif:     fixtureTZif(-28800, -28800),
		schedule: testSchedule(1<<time.Saturday, civilClock(21, 30), civilClock(22, 0)),
	}
	for _, tc := range []struct {
		city syntheticCityProfile
		want []intervalWant
	}{
		{east, []intervalWant{
			{Stay{at(5, 15), at(5, 20)}, Permitted}, {Stay{at(5, 20), at(5, 30)}, Prohibited},
			{Stay{at(5, 30), at(6, 20)}, Permitted}, {Stay{at(6, 20), at(6, 30)}, Prohibited},
			{Stay{at(6, 30), at(6, 35)}, Permitted},
		}},
		{west, []intervalWant{
			{Stay{at(5, 15), at(5, 30)}, Permitted}, {Stay{at(5, 30), at(6, 0)}, Prohibited},
			{Stay{at(6, 0), at(6, 35)}, Permitted},
		}},
	} {
		t.Run(tc.city.target.Jurisdiction, func(t *testing.T) {
			input, fixture := adaptSyntheticCity(stay, tc.city)
			got := EvaluateCivil(input, fixture)
			assertResult(t, got, Complete, Prohibited, ApplicableRestriction)
			assertIntervals(t, got, tc.want...)
			for _, p := range got.Intervals {
				t.Logf("[%s, %s) %s", p.Window.Start.Format(time.RFC3339), p.Window.End.Format(time.RFC3339), p.Legal)
				if p.Legal == Prohibited {
					ref := EvidenceRef(tc.city.target.Jurisdiction + "/source-rule")
					assertEvidence(t, p, ref, EvidenceRef(tc.city.target.Jurisdiction+"/fixture-restriction-review"))
					if !slices.ContainsFunc(p.RuleRefs, func(r RuleReference) bool {
						return r.OriginalID == "fixture-restriction" && slices.Contains(r.Evidence, ref)
					}) {
						t.Fatal("fragment lost the source rule or its evidence")
					}
				}
			}
		})
	}
	t.Run("unreviewed-calendar", func(t *testing.T) {
		west.schedule.CalendarRequired = true
		input, fixture := adaptSyntheticCity(stay, west)
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Complete, Unknown, CalendarUnresolved)
		assertIntervals(t, got, intervalWant{stay, Unknown})
		assertEvidence(t, got.Intervals[0], "synthetic-west/source-rule")
		t.Logf("%s %s %s", got.Status, got.Legal, CalendarUnresolved)
	})
	t.Run("cross-city-timezone-binding", func(t *testing.T) {
		input, fixture := adaptSyntheticCity(stay, west)
		_, other := adaptSyntheticCity(stay, east)
		fixture.TimezoneBinding, fixture.Timezone = other.TimezoneBinding, other.Timezone
		got := EvaluateCivil(input, fixture)
		assertResult(t, got, Failed, Unknown, SnapshotInvalid)
		if len(got.Intervals) != 0 {
			t.Fatal("cross-city binding returned partial intervals")
		}
		t.Logf("%s %s %s", got.Status, got.Legal, SnapshotInvalid)
	})
}
