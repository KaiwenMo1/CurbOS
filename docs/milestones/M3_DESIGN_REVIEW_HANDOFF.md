# CurbOS M3 design review handoff

**Status** Design review only. M3 coding requires explicit human authorization.

**Prepared** 2026-11-21 (America/New_York) at M2 baseline `646e2454c0c34655bad9962cd273c6a2860270b5`.

## Roadmap objective

The canonical roadmap assigns M3 the rules engine and legal eligibility. The regulations domain evaluates whether parking is permitted for a particular resource and the **entire requested stay**, given the applicable jurisdiction, local time, vehicle and permits. The implementation contract, real pilot geography and evidence sources still require design approval. Routing, search orchestration and ranking belong to M4. Occupancy, prediction and live distribution remain later concerns. An M3 eligibility result alone establishes no verified recommendation, physical fit, price, vacancy or availability. [Architecture baseline](../core/ARCHITECTURE_BASELINE_v1.0.md#9-release-milestones-plan-only) · [Roadmap handoff](../core/CURBOS_HANDOFF_AND_M0_07_2026-11-18.md#e-milestone-plan) · [Decision register](../architecture/DECISION_REGISTER.md)

## Dependencies and evidence boundary

- **M2 provenance and identity.** Use a versioned source and rule evidence lineage, exact resource or curb side, geometry revision and explicit scope. Respect ADR-022 identity and ADR-028 validated staging and atomic versioning. DS11 structural validity and same-release reference resolution establish source coherence. They establish no legal authorization for a stay.
- **Authority and coverage.** Identify the governing jurisdictions and authoritative ordinances, posted signs, permit boundaries, effective restrictions and temporary orders for the proposed pilot. Record custody, issuing authority, citation, retrieval/effective time, applicability, reviewer decision and source rights for each evidence item. Establish side-specific coverage and the independence and authority of reviewers. M0's 20-block-face legal evidence gate remains open.
- **Inputs for complete-stay evaluation.** Require an explicit arrival and departure or duration, resource/side and geometry version, jurisdiction and authoritative timezone, vehicle class, and permit type, applicability and validity. Use candidate-specific arrival when supplied by future search. Represent an incomplete or ambiguous input explicitly. Define interval edges, overnight/week rollover, holidays, seasonal rules and daylight-saving gaps and repeated local times.
- **Rule interactions.** Evaluate every portion of the stay against recurring schedules, absolute exceptions, effective dates, maximum stay, vehicle/permit conditions, temporary orders and posted changes. Establish authority and precedence with review. For uncertain or conflicting rules without approved resolution, retain evidence and return `UNKNOWN`. Absence of a restriction record, `rate=0`, and `undesignated` cannot establish eligibility or zero cost.
- **Public boundary.** M2 remains `REAL_SOURCE_ACCEPTANCE_BLOCKED` and `REAL_PUBLICATION_NO_GO`. Synthetic work can be considered with explicit later authorization. Real evaluation evidence needs separate approval for bounded private use, and public claims require separate evidence and serving approval. Discovery must stay clearly distinguished under ADR-006, ADR-007, ADR-013, ADR-024 and ADR-026. [M0/M1 gates](M0_M1_ACCEPTANCE_AND_GATES.md) · [M2 acceptance and blocker register](M2_ACCEPTANCE_REPORT.md#blocker-register) · [ADR-028](../adr/ADR-028_VALIDATED_STAGING_ATOMIC_PUBLICATION.md)

## Design questions requiring human approval

| Decision | Review evidence or choice required |
|---|---|
| Pilot jurisdiction, resources and claims | Select a bounded pilot and supported resource/vehicle/permit cases. Decide whether the first slice is synthetic-only. Specify evidence needed for later private real-source testing and for each affirmative claim. |
| Authoritative evidence and completeness threshold | Identify authoritative sources, required sign/order/permit evidence, capture dates, freshness and withdrawal rules, reviewer authority, independent field evidence, and approved exclusions. Decide when the absence of any evidence forces `UNKNOWN`. |
| Rule normalization and precedence | Approve rule types and typed applicability, source-to-rule mappings, conflict precedence by strength and effective time, reason codes, and treatment of unsupported rules. Define whether hard proof of a restriction is sufficient for a prohibited result when remaining evidence is incomplete. |
| Time and requested-stay semantics | Approve boundary inclusivity, timezone authority, daylight-saving disambiguation, day/week/holiday interpretation, overnight schedules, maximum-stay and re-parking semantics, and partial overlap behavior. |
| Vehicle and permits | Define minimal input attributes, permit class versus actual validity and boundary, privacy handling, applicable exemptions and behavior for unknown or unsupported inputs. |
| Versioning and internal/public API boundary | Define the evidence, release, resource and rule versions consumed and returned, snapshot/rollback semantics, an internal contract or REST boundary under ADR-027, and typed results/reasons for stale, conflicting and missing evidence. Separate completed evaluation from a positive parking conclusion. |
| Validation and review gate | Approve deterministic synthetic cases and an independent private field/sign audit plan. Decide who accepts the evidence, how to record disagreements and gaps, and which rollout and rollback triggers apply before any real output. |
| First implementation authorization | Review the approved design, contracts, evidence boundaries and sequential small PR plan. Explicitly authorize the first implementation slice or flag any proposed ADR amendment for separate review. |

## Proposed design acceptance scenarios

- A complete synthetic stay covered by authoritative fixture rules yields a traceable eligibility outcome. A stay crossing into sweeping, permit-only time, an emergency restriction or a maximum-stay violation must account for that segment.
- Overnight stays, time boundaries, holidays, and both daylight-saving transitions have expected results tied to local jurisdiction time. An unresolved ambiguity produces `UNKNOWN`.
- Wrong-side evidence, unknown permit applicability, missing or stale temporary restrictions, unsupported rule forms and unresolved contradictions cannot yield an affirmative result. Test reason codes and exact evidence linkage.
- Replacing or revoking a rule or geometry version preserves the earlier evaluation's audit basis. New evaluations consume a coherent eligible version. Failure leaves the previous coherent state available where it is still authorized.
- An independent reviewer can reproduce any real evaluation from the exact approved evidence, requested stay and applicability inputs. Any public claim requires separately recorded authorization. Existing Discovery, read-only assessment and synthetic isolation gates remain in force.

The next engineering action is a human design review of these decisions, with an explicit choice of the first scope and evidence threshold. The M2 real-source work proceeds only under its separate evidence and authorization gates. [Project state](../../tracking/PROJECT_STATE.md)
