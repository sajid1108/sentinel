# Builder session rules — read before anything else

**Project:** Sentinel — Return Abuse Detection with Cost-Weighted Decisioning (hackathon, Track 02: AI Risk Manager).
**Repo:** `C:\Users\Sajid\.gemini\antigravity\scratch\sentinel` (GitHub `sajid1108/sentinel`, branch `main`). Windows; `backend/.venv` (Python 3.12); frontend installs with `npm ci`; no make. Use absolute paths if your session starts in a different folder.

## Roles

- The **ARCHITECT** session (not you) owns `docs/ARCHITECTURE.md`, reviews each phase and writes your brief in `docs/briefs/`. Its instructions are authoritative and may amend the contract.
- You are a **BUILDER** session with no memory of earlier sessions. The repo is the shared memory.

## Before writing code

1. **Read exactly what the brief's "Read before writing code" line lists, and nothing else.** The architect chooses those sections for each phase. Read deviations by number: grep for `^| 27 |` in `docs/DEVIATIONS.md` rather than paging the whole file. Skip `october_master_architecture.md` unless the brief names it.
2. If, while working, a change reaches code or a contract that the listed sections don't cover, read the full relevant section of `docs/ARCHITECTURE.md` or the relevant deviation before changing it, and say so in the report. **Selective reading is allowed; condensing is not.** Never summarise a ground-truth file into another file.
3. **Correctness rules for any `frontend/` work, always part of the gate** (`DESIGN.md` is otherwise advisory until the post-MVP design pass):
   - money only from the server's `display` strings
   - no hard-coded thresholds, costs or versions
   - red only for BLOCK, confirmed abuse or a broken audit chain
   - the return and abuse scores never combined
4. Run `git status -sb` and `git log --oneline -5`. Work on `main` (cloud sessions work on their `claude/...` branch). Branch `phase-4-wip` is a checkpoint: never merge or delete it.
5. Fresh environment: run `scripts/setup_env.sh` once it exists (it is idempotent). Baseline: `pytest -m "not slow"` in `backend/`; if the brief touches the frontend, also `npm ci && npm run build` in `frontend/`.

## Rules

- The architecture is frozen except where a brief amends it. Record every deviation in `docs/DEVIATIONS.md`.
- New commits only. Never amend, rebase or force-push. **No Claude co-author trailer** in commit messages.
- Never hard-code probabilities, costs, thresholds or versions, and never special-case demo ids.
- Never loosen a bound, band or test to make something pass.
- Iterate with `pytest -m "not slow"` (and `npm test` for the frontend). Run the full suite, including slow tests, **once, before each commit**. Commit only if the gate passes. Stop at the gate.
- **New deviation rows are at most ~150 words.** State the decision and the reason; put measurements, trails and alternatives in the phase report and cite it (e.g. "measurements: phase-9 report §5"). Never edit an old row except to append a dated status line.
- Progress lines are one line each. Reports don't restate the brief.
- **Escalate** (stop, give measured numbers, propose the smallest fix, wait) if an instruction conflicts with the contract or an accepted deviation.
- Print the progress line the brief specifies at every checkpoint, with elapsed time taken from real timestamps, never estimates.
- Write the report to `docs/reports/phase-N.md`, update `docs/PROGRESS.md` and the README build status, commit, push, and stop. Do not start the next phase.
