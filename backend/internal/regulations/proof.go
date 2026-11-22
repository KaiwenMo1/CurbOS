package regulations

import (
	"cmp"
	"slices"
)

type permitMatch uint8

const (
	permitUncertain permitMatch = iota
	permitMissing
	permitSatisfied
)

func matchPermit(key PermitKey, inventory PermitInventory, active []bool) permitMatch {
	uncertain := inventory.State != InventoryComplete
	for i, fact := range inventory.Facts {
		if !active[i] {
			continue
		}
		if fact.State == PermitVerified {
			if fact.Key == key {
				return permitSatisfied
			}
			continue
		}
		if (fact.Key.Class == "" || fact.Key.Class == key.Class) &&
			(fact.Key.Scope == "" || fact.Key.Scope == key.Scope) &&
			(fact.Key.Issuer == "" || fact.Key.Issuer == key.Issuer) {
			uncertain = true
		}
	}
	if uncertain {
		return permitUncertain
	}
	return permitMissing
}

func prove(window Stay, active activeWindows, snapshot SyntheticSnapshot, permits PermitInventory, permitRefs []EvidenceRef) IntervalResult {
	result := IntervalResult{Window: window, Legal: Unknown}
	addReason := func(code ReasonCode, id RuleID) {
		result.Reasons = append(result.Reasons, Reason{Code: code, Rule: id})
	}
	covered := false
	for i, coverage := range snapshot.Coverage {
		if active[coverageWindow][i] && coverage.Target == snapshot.Target {
			covered = true
			result.EvidenceRefs = append(result.EvidenceRefs, coverage.Evidence...)
		}
	}

	closed := make(map[RuleID][]EvidenceRef)
	for i, assumption := range snapshot.Restrictions {
		if active[assumptionWindow][i] && assumption.Target == snapshot.Target {
			closed[assumption.Rule] = append(closed[assumption.Rule], assumption.Evidence...)
		}
	}
	open := make(map[RuleID]bool)
	unresolved := false
	for i, fact := range snapshot.Unresolved {
		if active[unresolvedWindow][i] && fact.Target == snapshot.Target {
			unresolved = true
			if fact.Kind != PotentialRestriction {
				open[fact.Rule] = true
			}
			result.EvidenceRefs = append(result.EvidenceRefs, fact.Evidence...)
		}
	}

	var permissions, restrictions []int
	var lastRule RuleID
	for i, rule := range snapshot.Rules {
		if !active[ruleWindow][i] || rule.ID == lastRule {
			continue
		}
		// Validation sorted rules by ID and required repeated IDs to agree.
		// Their raw windows still count before evaluating one copy.
		lastRule = rule.ID
		result.RuleRefs = append(result.RuleRefs, RuleReference{ID: rule.ID, Evidence: rule.Evidence})
		result.EvidenceRefs = append(result.EvidenceRefs, rule.Evidence...)
		switch {
		case rule.Target != snapshot.Target:
			addReason(SideMismatch, rule.ID)
		case rule.Effect == Permission:
			permissions = append(permissions, i)
		default:
			restrictions = append(restrictions, i)
		}
	}

	blockedPermission := unresolved
	permitMatches := make(map[PermitKey]permitMatch)
	for _, index := range restrictions {
		rule := snapshot.Rules[index]
		restrictionReason := ApplicableRestriction
		if rule.Effect == PermitOnly {
			match, found := permitMatches[rule.Permit]
			if !found {
				if len(permitMatches) == 0 {
					result.EvidenceRefs = append(result.EvidenceRefs, permitRefs...)
				}
				match = matchPermit(rule.Permit, permits, active[permitWindow])
				permitMatches[rule.Permit] = match
			}
			if match == permitSatisfied {
				continue
			}
			blockedPermission = true
			if match == permitUncertain {
				addReason(PermitUnverified, rule.ID)
				continue
			}
			restrictionReason = PermitRequired
		}

		blockedPermission = true
		// An independently sufficient restriction needs its own premise.
		// Open overrides and competing permissions can defeat that proof.
		assumptions := closed[rule.ID]
		result.EvidenceRefs = append(result.EvidenceRefs, assumptions...)
		if len(assumptions) == 0 || open[""] || open[rule.ID] {
			addReason(CoverageMissing, rule.ID)
			continue
		}
		if slices.ContainsFunc(permissions, func(index int) bool {
			_, conditional := slices.BinarySearch(snapshot.Rules[index].SubjectTo, rule.ID)
			return !conditional
		}) {
			addReason(AuthorityConflict, rule.ID)
			continue
		}
		addReason(restrictionReason, rule.ID)
		result.Legal = Prohibited
	}

	if !covered || unresolved {
		addReason(CoverageMissing, "")
	}
	if result.Legal != Prohibited {
		if len(permissions) == 0 {
			addReason(PermissionMissing, "")
		} else if covered && !blockedPermission {
			addReason(ApplicablePermission, "")
			result.Legal = Permitted
		}
	}
	slices.SortFunc(result.Reasons, func(a, b Reason) int {
		if order := cmp.Compare(a.Code, b.Code); order != 0 {
			return order
		}
		return cmp.Compare(a.Rule, b.Rule)
	})
	result.Reasons = slices.Compact(result.Reasons)
	result.EvidenceRefs = canonical(result.EvidenceRefs)
	return result
}
