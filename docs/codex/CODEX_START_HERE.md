# CurbOS — Codex Start Here (v1.3)

**Status:** Instructions and task prompts only. No production application code has been created. **Source of truth:** `docs/architecture/DECISION_REGISTER.md` (ADR-001–028), `AGENTS.md`, and `docs/milestones/M1_IMPLEMENTATION_SPEC.md`.

## 0. One canonical working directory

1. Create a GitHub repository named `curbos` (public or private). Clone it to your own machine or open it in an IDE/Codex environment with repository access.
2. Extract **the contents inside** `CurbOS_Master_v1.3/` directly into the repo root, so the root contains `AGENTS.md`, `docs/`, `tools/`, and `tracking/`. Do **not** nest a folder named `CurbOS_Master_v1.3` inside your code repo.
3. Do not copy earlier master ZIPs into the repository. Keep those privately as backups. Do not upload personal data, credentials, or unrestricted location history.
4. Inspect `git status`; commit the planning baseline first (`docs: import CurbOS design baseline`) before Codex changes code. Use `main` as a protected baseline if convenient, and create a working branch for every PR.
5. Check that Codex can see the repository workspace and that its instructions include `AGENTS.md`. The specific UI for selecting a repo depends on whether you use CLI, IDE, or cloud Codex. Don't assume it can see documents only uploaded to a ChatGPT conversation.

## 1. Source-reading hierarchy

**Read in this order for onboarding:**
- `README_START_HERE.md`
- `AGENTS.md`
- `docs/architecture/DECISION_REGISTER.md`
- `docs/milestones/M1_IMPLEMENTATION_SPEC.md`
- `docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md`
- `docs/codex/M1_FIRST_PR_TASKS.md`
- `docs/design/FINAL_ENGINEERING_REVIEW_v1.2.md`

For PR-specific implementation, read the exact relevant supporting core/ADR documents and current repository files. `docs/research/` contains findings and snapshots, not proof of current legal parking eligibility. When text conflicts, prefer the latest **accepted** ADR and explicitly flag contradictions rather than silently replacing decisions.

## 2. First prompt — READ ONLY

Paste this into Codex after it has opened the repo:

> You are the engineering implementation agent for CurbOS. **Do not edit files, run destructive commands, or implement anything in this onboarding task.** First inspect the repository tree and `git status`. Read `README_START_HERE.md`, `AGENTS.md`, `docs/architecture/DECISION_REGISTER.md`, `docs/milestones/M1_IMPLEMENTATION_SPEC.md`, `docs/milestones/M0_M1_ACCEPTANCE_AND_GATES.md`, `docs/codex/M1_FIRST_PR_TASKS.md`, and `docs/design/FINAL_ENGINEERING_REVIEW_v1.2.md`. Summarize (1) the product and system architecture, (2) approved technology stack, (3) non-negotiable data/legality/privacy rules, (4) verified vs pending M0 data, (5) M1 scope and its exclusions, (6) the five planned PRs, (7) ambiguities or contradictions you detected, and (8) the exact steps and commands you propose for PR-01. **Stop and wait for my approval. Do not start PR-01 yet.**

**Human approval gate:** Verify Codex understands `UNKNOWN != VACANT`, unverifiable rules never imply legal parking, synthetic data never masquerades as production, PostgreSQL is authoritative, and M1 does not implement occupancy or full search.

## 3. Second prompt — PR-01 ONLY

After reviewing onboarding, make sure `main` has a baseline commit and create/select a PR-01 branch, e.g. `m1/pr-01-foundation`. Paste:

> Proceed with **M1 PR-01 only**, following the **Default preamble** and **PR-01** section of `docs/codex/M1_FIRST_PR_TASKS.md`. Read all referenced specifications before modifying anything. Inspect current files and `git status`. Keep the smallest coherent Go + React/TypeScript foundation; preserve all documents and audit tools. Do not start PR-02 or implement PostGIS, Redis, WebSocket, routing, occupancy, legality, parking search, or fake parking pins. Add meaningful tests; run the build/check/test commands available in your execution environment, and distinguish genuinely executed checks from unverified claims. At the end, report the file diff, commands and results, known gaps, and a short Engineering Learning Note. Stop for my review.

If an environment/toolchain prerequisite is missing, report it rather than claiming successful verification. If Codex cannot create a branch in its environment, create the branch manually before authorizing edits. Never mix unrelated changes on `main`.

## 4. Human review and merge

After PR-01, obtain the code diff, test output, and build output (or connect the repository for review). Ask ChatGPT to evaluate them against `AGENTS.md` and the PR-01 exit criteria. Require corrections before merge. Only after PR-01 is reviewed/merged should PR-02 be started in a fresh branch. Repeat one PR at a time through PR-05. **Do not paste all five prompts at once.**

Review checklist:
- Did Codex change only the approved PR scope?
- Are all tests truly executed, and do they exercise the relevant behavior?
- Can a clean checkout follow README setup/build steps?
- Does the UI show no fabricated parking/legal/sensor facts?
- Are credentials omitted and sensitive location data absent from logs?
- Can you explain the core implementation decision and failure mode?

## 5. Parallel M0 audit — explicitly separate

M0 is a distinct data-feasibility track, not an implicit part of PR-01. `tools/m0/m0_08_cds_audit.py` and `tools/m0/m0_meter_audit.py` are research tools; synthetic fixtures are never official data. Until official Zones/Policies and meter/sensor records are successfully downloaded and audited, real join/coverage/freshness rates remain unverified. Store raw official data outside Git unless its terms/size clearly permit inclusion, record source URL, retrieval time, license, checksum and query parameters. Never infer `ALLOWED` from missing restrictions or `rate=0` alone. Pilot priority: DTLA for data validation; Westwood remains a possible subsequent product pilot, not a confirmed deployment area.

## 6. Keeping the project remembered and synchronized

The repository is the durable source of truth; ChatGPT conversation memory is not a substitute. After each approved PR update the appropriate milestone status, decision register **only for newly approved decisions**, and the running project handoff/status. Keep current design decisions and actual implementation status distinct. Future Master Pack updates should be exported from the repository, rather than blindly overwriting code with older ZIP files.

### Future-session restart prompt

> Continue CurbOS using this repository as the source of truth. Read `README_START_HERE.md`, `AGENTS.md`, `docs/architecture/DECISION_REGISTER.md`, `docs/codex/CODEX_START_HERE.md`, and the current milestone/PR files. Inspect `git status`, recent commits and PR progress before recommending any changes. Preserve accepted ADRs; do not implement out-of-scope work or assume unverified official data are validated.
