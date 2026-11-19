# CurbOS Master Pack — v1.3 (Canonical Bundle)

**Updated:** 2026-11-18. **Latest change:** Added `docs/codex/CODEX_START_HERE.md` with repo setup, read-only onboarding and PR-01 launch instructions. **Purpose:** Preserve accepted architecture and M0 research, add ADR-028 and actionable M1 **planning**. **No production application code has been written in this pack.**

**Before first Codex run:** Follow `docs/codex/CODEX_START_HERE.md`. Put the extracted contents at repository root, commit the documentation baseline, then give Codex the read-only onboarding prompt.

## Read these in order
1. `docs/architecture/DECISION_REGISTER.md` — **all accepted ADR-001–028**; latest human-approved decisions win.
2. `AGENTS.md` — durable instructions and boundaries for Codex.
3. `docs/design/FINAL_ENGINEERING_REVIEW_v1.2.md` — current coding-readiness review.
4. `docs/milestones/M1_IMPLEMENTATION_SPEC.md` — exact M1 deliverables, out-of-scope, tests and PR gates.
5. `docs/codex/M1_FIRST_PR_TASKS.md` — first **five** incremental PR prompts; **one at a time**, no execution until human authorizes coding.
6. `docs/adr/ADR-028_VALIDATED_STAGING_ATOMIC_PUBLICATION.md` — accepted data publication model.
7. `docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md` — what's verified versus pending.
8. `docs/core/ARCHITECTURE_BASELINE_v1.0.md` — broader architecture and detailed contracts. `docs/core/CURBOS_HANDOFF_AND_M0_07_2026-11-18.md` preserves pre-028 context; the newer decision register appends ADR-028.

## Supersession / overlap rules
- **Authoritative current decisions:** `docs/architecture/DECISION_REGISTER.md` + `docs/adr/ADR-028_VALIDATED_STAGING_ATOMIC_PUBLICATION.md`; older files are retained because they hold details, not because their old proposal status remains current.
- `docs/design/DESIGN_FREEZE_AND_IMPLEMENTATION_READINESS.md` is a **historical v1.1 review**; its ADR-028 proposal is superseded by the accepted ADR and final review v1.2.
- Research snapshots in `docs/research/` preserve evolving findings, not verified counts. Westwood was provisionally prioritized before published DTLA CDS data were found; DTLA now leads **data validation**, not a finalized product-pilot decision.
- Tools under `tools/m0/` are audit prototypes. Synthetic `fixtures/` must never be used to claim official metrics.
- No duplicated old ZIPs are embedded in this archive. This is a full replacement master: download only **v1.3** for current work; save past bundles optionally as private backups.

## Current key gates
- **M1 foundation:** ready for a *user-directed* Codex PR-01, can run in parallel with M0 audits.
- **M0 measured coverage:** pending full Zones/Policies and LADOT meter/sensor row-level audits and 20 real block-face samples.
- **Verified parking recommendations:** NOT ready; separate M3 legality evidence gate required.

## To resume in another chat
Upload this ZIP, say: "Continue CurbOS from Master v1.3. Read README_START_HERE.md, decision register and AGENTS.md. Do not change ADRs without approval. Start with M1 PR-01 only when I authorize." All paths in this archive are relative to repo root; when coding begins, reconcile them with actual repository contents rather than blindly overwriting.
