# Builder session rules — read before anything else

**Project:** Sentinel — Return Abuse Detection with Cost-Weighted Decisioning (hackathon, Track 02: AI Risk Manager).
**Repo:** `C:\Users\Sajid\.gemini\antigravity\scratch\sentinel` (GitHub `sajid1108/sentinel`, branch `main`). Windows; `backend/.venv` (Python 3.12); frontend installs with `npm ci`; no make. Use absolute paths if your session starts in a different folder.

## Roles

- The **ARCHITECT** session (not you) owns `docs/ARCHITECTURE.md`, reviews each phase and writes your brief in `docs/briefs/`. Its instructions are authoritative and may amend the contract.
- You are a **BUILDER** session with no memory of earlier sessions. The repo is the shared memory.

## Before writing code

1. Read `october_master_architecture.md`, then `docs/ARCHITECTURE.md` and `docs/DEVIATIONS.md` in full. Never summarise them into another file.
2. Read `docs/PROGRESS.md`, the most recent `docs/reports/phase-N.md`, and the README build status.
3. Run `git status -sb` and `git log --oneline -5`. Work on `main`. Branch `phase-4-wip` is a checkpoint: never merge or delete it.
4. Baseline: `pytest -m "not slow"` in `backend/`; if the brief touches the frontend, also `npm ci && npm run build` in `frontend/`.

## Rules

- The architecture is frozen except where a brief amends it. Record every deviation in `docs/DEVIATIONS.md`.
- New commits only. Never amend, rebase or force-push. **No Claude co-author trailer** in commit messages.
- Never hard-code probabilities, costs, thresholds or versions, and never special-case demo ids.
- Never loosen a bound, band or test to make something pass.
- Run the full suite, including slow tests, before any commit. Commit only if the gate passes. Stop at the gate.
- **Escalate** (stop, give measured numbers, propose the smallest fix, wait) if an instruction conflicts with the contract or an accepted deviation.
- Print the progress line the brief specifies at every checkpoint, with elapsed time taken from real timestamps, never estimates.
- Write the report to `docs/reports/phase-N.md`, update `docs/PROGRESS.md` and the README build status, commit, push, and stop. Do not start the next phase.
