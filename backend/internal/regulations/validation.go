package regulations

import (
	"cmp"
	"slices"
	"time"
)

const (
	maxStay       = 168 * time.Hour
	maxRules      = 256
	maxWindows    = 1024
	maxBoundaries = 1024
	maxReferences = 2048
	maxEndpoints  = 2*maxWindows + 2
)

type workBudget struct {
	windows, rules, references int
}

func (b *workBudget) take(windows, rules, references int) bool {
	if windows > b.windows || rules > b.rules || references > b.references {
		return false
	}
	b.windows -= windows
	b.rules -= rules
	b.references -= references
	return true
}

// remainingBudget counts the original collections, including disjoint windows,
// duplicates and implicit whole-stay facts, before allocating sweep storage.
func remainingBudget(input EvaluationInput, snapshot SyntheticSnapshot) (workBudget, bool) {
	budget := workBudget{maxWindows, maxRules, maxReferences}
	for _, n := range [...]int{
		len(snapshot.Rules), len(snapshot.Coverage), len(snapshot.Restrictions),
		len(snapshot.Unresolved), len(input.Permits.Facts),
	} {
		if !budget.take(n, 0, 0) {
			return workBudget{}, false
		}
	}
	if !budget.take(0, len(snapshot.Rules), 0) {
		return workBudget{}, false
	}

	count := func(refs []EvidenceRef) bool {
		return budget.take(0, 0, len(refs))
	}
	for _, rule := range snapshot.Rules {
		if !count(rule.Evidence) {
			return workBudget{}, false
		}
	}
	for _, coverage := range snapshot.Coverage {
		if !count(coverage.Evidence) {
			return workBudget{}, false
		}
	}
	for _, assumption := range snapshot.Restrictions {
		if !count(assumption.Evidence) {
			return workBudget{}, false
		}
	}
	for _, fact := range snapshot.Unresolved {
		if !count(fact.Evidence) {
			return workBudget{}, false
		}
	}
	for _, permit := range input.Permits.Facts {
		if !count(permit.Evidence) {
			return workBudget{}, false
		}
	}
	ok := count(input.Permits.Evidence)
	return budget, ok
}

func preflight(input EvaluationInput, snapshot SyntheticSnapshot) (int, bool) {
	budget, ok := remainingBudget(input, snapshot)
	if !ok {
		return 0, false
	}
	return maxWindows - budget.windows, true
}

func (w Stay) utc() Stay {
	return Stay{Start: w.Start.UTC(), End: w.End.UTC()}
}

func (w Stay) valid() bool {
	return !w.Start.IsZero() && !w.End.IsZero() && w.Start.UTC().Before(w.End.UTC())
}

func (t SyntheticTarget) exact() bool {
	return t.Resource != "" && t.Geometry != "" && t.Orientation != "" &&
		t.Jurisdiction != "" && (t.Side == SideLeft || t.Side == SideRight)
}

func sameOrientedCurb(a, b SyntheticTarget) bool {
	a.Side, b.Side = SideUnknown, SideUnknown
	return a == b
}

func validRefs(refs []EvidenceRef, required bool) bool {
	return (!required || len(refs) != 0) && !slices.Contains(refs, "")
}

func (k PermitKey) exact() bool {
	return k.Class != "" && k.Scope != "" && k.Issuer != ""
}

func canonical[T ~string](values []T) []T {
	if len(values) == 0 {
		return nil
	}
	slices.Sort(values)
	return slices.Compact(values)
}

func validateSnapshot(snapshot SyntheticSnapshot, permits PermitInventory) (SyntheticSnapshot, bool) {
	target := snapshot.Target
	validTarget := func(t SyntheticTarget) bool {
		return t.exact() && sameOrientedCurb(t, target)
	}
	validWindow := func(f FixtureWindow) bool {
		return validTarget(f.Target) && f.Window.valid() && validRefs(f.Evidence, true)
	}
	if !target.exact() || permits.State > InventoryComplete ||
		!validRefs(permits.Evidence, permits.State == InventoryComplete) {
		return SyntheticSnapshot{}, false
	}
	for _, permit := range permits.Facts {
		// A partial key or a finite window narrows where an unknown permit
		// may apply. Those known facts need fixture evidence too.
		scoped := permit.Key != (PermitKey{}) || permit.Validity != nil
		if permit.State > PermitVerified || !validRefs(permit.Evidence, scoped) ||
			(permit.Validity != nil && !permit.Validity.valid()) ||
			(permit.State == PermitVerified && (!permit.Key.exact() || permit.Validity == nil)) {
			return SyntheticSnapshot{}, false
		}
	}

	rules := slices.Clone(snapshot.Rules)
	byID := make(map[RuleID]SyntheticRule, len(rules))
	for i := range rules {
		rule := &rules[i]
		if !validWindow(rule.FixtureWindow) || rule.ID == "" ||
			rule.Effect < Permission || rule.Effect > PermitOnly ||
			(rule.Effect == PermitOnly && !rule.Permit.exact()) ||
			(rule.Effect != PermitOnly && rule.Permit != (PermitKey{})) ||
			(rule.Effect != Permission && len(rule.SubjectTo) != 0) ||
			len(rule.SubjectTo) > len(rules) {
			return SyntheticSnapshot{}, false
		}
		rule.Window = rule.Window.utc()
		rule.Evidence = canonical(slices.Clone(rule.Evidence))
		rule.SubjectTo = canonical(slices.Clone(rule.SubjectTo))
		if prior, exists := byID[rule.ID]; exists &&
			(prior.Window != rule.Window || prior.Target != rule.Target ||
				prior.Effect != rule.Effect || prior.Permit != rule.Permit ||
				prior.origin != rule.origin || prior.violation != rule.violation ||
				!slices.Equal(prior.SubjectTo, rule.SubjectTo) || !slices.Equal(prior.Evidence, rule.Evidence)) {
			return SyntheticSnapshot{}, false
		}
		byID[rule.ID] = *rule
	}
	restrictionMatches := func(id RuleID, t SyntheticTarget) bool {
		rule, exists := byID[id]
		return exists && rule.Effect != Permission && rule.Target == t
	}
	for _, rule := range rules {
		for _, id := range rule.SubjectTo {
			if !restrictionMatches(id, rule.Target) {
				return SyntheticSnapshot{}, false
			}
		}
	}
	for _, window := range snapshot.Coverage {
		if !validWindow(window) {
			return SyntheticSnapshot{}, false
		}
	}
	for _, assumption := range snapshot.Restrictions {
		if !validWindow(assumption.FixtureWindow) || !restrictionMatches(assumption.Rule, assumption.Target) {
			return SyntheticSnapshot{}, false
		}
	}
	for _, fact := range snapshot.Unresolved {
		if !validTarget(fact.Target) || !validRefs(fact.Evidence, true) ||
			(fact.Window != nil && !fact.Window.valid()) || fact.Kind > PotentialOverride ||
			(fact.Rule != "" && (fact.Kind == PotentialRestriction || !restrictionMatches(fact.Rule, fact.Target))) {
			return SyntheticSnapshot{}, false
		}
	}
	slices.SortFunc(rules, func(a, b SyntheticRule) int { return cmp.Compare(a.ID, b.ID) })
	snapshot.Rules = rules
	return snapshot, true
}
