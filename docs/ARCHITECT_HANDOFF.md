# Architect handoff — read this first

You are taking over as the **main architect** of Sentinel. The previous architect session designed the system, wrote `docs/ARCHITECTURE.md`, and reviewed every phase from 0 to 7. This file is everything you need to continue without that conversation.

**Repo:** `C:\Users\Sajid\.gemini\antigravity\scratch\sentinel` · GitHub `sajid1108/sentinel` · branch `main`.
**Written:** 2026-09-18, while Phase 8 was being built.

---

## 1. Your role and how the work flows

- **You (architect)** own `docs/ARCHITECTURE.md` (frozen; amend only through `docs/DEVIATIONS.md`), review each phase, and write the next brief. You do not write production code; you do verify claims by reading the repo and running probes yourself.
- **Builder sessions** each do one step: *fixes for the previous phase + build of the next phase*, then stop at the gate. They have no memory; the repo is the shared memory.
- **Briefs live in files**, so the operator (Sajid) only pastes one line:
  - `docs/briefs/BUILDER_HEADER.md`: standing rules for every builder session. Keep it current.
  - `docs/briefs/phase-N-*.md`: one brief per step. Part 1 = follow-ups on the previous phase; Part 2 = the new phase.
  - The operator starts a builder with: `Read docs/briefs/BUILDER_HEADER.md, then follow docs/briefs/phase-N-<name>.md. Repo: C:\Users\Sajid\.gemini\antigravity\scratch\sentinel`
- **Reports** come back in `docs/reports/phase-N.md`. The operator says "phase N done"; you read the report and the diff from the repo. Don't ask them to paste reports.
- **Cloud builder sessions** (started from the phone) work on a branch named `claude/...` and push it. You review the branch, then merge it into `main` locally and push.
- **Progress:** `docs/PROGRESS.md` holds a time log from commit timestamps. Builders update their row; briefs specify a progress line they print at checkpoints.
- **Commits: no Claude co-author trailer**, ever (the operator's standing preference). New commits only; never amend, rebase or force-push. Branch `phase-4-wip` is a checkpoint: never merge or delete it.
- The operator is sometimes on a phone. Keep instructions short, put long content in files, and avoid asking them to copy large blocks.

## 2. Where things stand

| Spec phase | What | State |
|---|---|---|
| 0–7 | skeleton, policy engine, synthetic world, features, models and evaluation, explanations, DB and audit and scoring service, API | **done on `main`**, reviewed, ~820 tests green |
| 8 | order detail page (+ Phase 7 follow-ups) | **in progress** in a cloud session on branch `claude/phase-8-order-detail-jj8aik`. Part 1 pushed as `fa43f4b`. Brief: `docs/briefs/phase-8-order-detail.md` |
| 9–10 | queue + simulate checkout; overview | not started |
| 11–12 | backtest depth; hardening | not started |
| — | demo script, rehearsals, video, pitch | not started |

`main` has three docs-only commits the Phase 8 branch lacks (`59daa4b` brief, `74a4b7f` DESIGN.md, `13c5e04` advisory rule). Merging the branch should not conflict, but check.

## 3. Operator's current direction: MVP first, design later

Finish a working end-to-end demo, then do a frontend design pass. The MVP is:

1. Order detail page (Phase 8, in progress).
2. Queue page with three "Simulate checkout" buttons (the demo presets from `GET /internal/demo/presets`, scored via `POST /internal/score-order`) → navigate to the new order's detail page.
3. Minimal Overview: the synthetic backtest table from `/metrics`, plus the synthetic-data notice.
4. A "Reset demo" control (`POST /internal/demo/reset`, `DEMO_MODE` only).

**Your next two actions:**
1. When the operator says "phase 8 done": review `docs/reports/phase-8.md`, the branch diff, the tests and any screenshots under `docs/reports/phase-8/`. Merge into `main` if it passes.
2. Write `docs/briefs/phase-9-mvp.md` covering MVP items 2–4 as Part 2, with the Phase 8 follow-ups as Part 1. Combining phases 9 and 10 saves a review round.

**Known Phase 8 follow-ups to include in Part 1 regardless of the review:**
- **Abuse meter colour bands.** The Phase 8 brief asked for the meter to turn amber at 50 % and red at 70 %. That hard-codes the G3 policy threshold into the frontend, and breaks a mandatory rule. Make the meter neutral; the action badge carries the verdict. This was the previous architect's own mistake.
- Anything that violates the four mandatory correctness rules in `BUILDER_HEADER.md`.

## 4. Design system status

`DESIGN.md` (repo root) is the product's design system: "ledger" direction, semantic colour tokens, IBM Plex Sans/Mono self-hosted, sections not cards, badges only for action/strength/guardrail, neutral synthetic notice, no gradients or glass. **It is advisory until the post-MVP design pass**, except the four correctness rules in `BUILDER_HEADER.md`, which are mandatory now.

The post-MVP design pass should:
- audit the built pages against the `DESIGN.md` §11 checklist, using avoid-ai-design in detect mode as a lens
- add the tokens and fonts (`@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`, exact pins)
- add `@playwright/test` journeys for the three demos, with screenshots at 1440 and 1280
- Rejected tools: 21st.dev MCP (network plus API key, generic components).

## 5. Results that must never be tuned away

These are honest findings, and the pitch must reflect them:

- **The tuned fixed-threshold baseline beats Sentinel on realized cost** (₹1,60,112 vs ₹1,95,313 per 1,000 orders). The gap is the price of the guardrails: they change 49 decisions and avoid 8 genuine blocks at about ₹9,211 each, **2.05× the policy's own modelled false-block cost**. Present it as a deliberate trade, not a win on cost.
- **Graph evidence is necessary but not alone.** Demo 2 scores 0.9507 with graph features and 0.0993 without, so the graph catches it. But the new-account feature alone moves it 94 points, because the model combines the two rather than adding them. Say: "Without the relationship evidence this order scores 10 % and would pass. The graph is what catches it; the new account makes it urgent." Never claim the graph works alone.
- **Demo 3 is reviewed because of cost, not the guardrail.** At p_abuse 0.6913, BLOCK costs ₹4,051.94 against MANUAL_REVIEW at ₹1,858.14. MANUAL_REVIEW is cost-optimal for 0.0930 < p < 0.8413.
- **Redundancy finding (#25, #27).** The confirmed-neighbour features are individually predictive but get zero splits in the full model, because correlated features identify the same rows. That is why reason codes are evidence statements that declare their own redundancy.
- **Fairness disparity.** Accounts under 30 days old carry 36.1 % friction against 4.8–5.9 % for older cohorts (block rate 0.74 %). Carried TODOs: show the cohort friction table in the backtest-depth phase, and state it plainly in the model card.
- **Headline metrics:** abuse TEST PR-AUC 0.814 with graph features vs 0.527 without; cold-start ring R3 recall 0.727 vs 0.143; hard-negative archetypes have a genuine block rate of 0.0.
- All data is synthetic, and every surface shows the exact synthetic-data notice from `ARCHITECTURE.md` §1.

## 6. Invariants the code already enforces (keep them enforced)

- Models output probabilities only; the policy engine decides. `p_return` is never an input to action selection (G1).
- Guardrails only remove actions; PREPAID_ONLY and MANUAL_REVIEW always stay feasible. BLOCK needs p_abuse ≥ 0.70 and two corroborating signals with a DEVICE, PAYMENT_TOKEN or ACCOUNT_CLAIMS anchor.
- Point-in-time features; frozen scoring history (#30) makes demo scoring order-independent.
- Append-only, hash-chained audit; overrides preserve the original recommendation.
- The public checkout returns outcome only; ALLOW and MANUAL_REVIEW bodies are identical.
- Demo bands: Demo 1 ALLOW, Demo 2 BLOCK (p ∈ [0.75, 1]), Demo 3 MANUAL_REVIEW (p ∈ [0.20, 0.84], ceiling below the 0.8413 crossover).

## 7. How the previous architect worked (keep doing this)

- **Verify, don't trust.** Read the diff, run the tests, and probe the data yourself before accepting a report. This caught a summarised architecture file, a leakage bug in G4, ring members that were visible at account level, unresolved-label bias, a calibration problem hidden by the ECE binning, and false sentences on the reviewer screen.
- **Correct your own mistakes openly.** Several bounds the architect set were wrong. They were changed with the reason recorded, never quietly loosened.
- **When a target is unreachable, test the property, not the proxy.** Decide with a rule the builder can follow without another round trip.
- **Read every rendered sentence.** It's what judges read.

## 8. Files to read, in order

1. This file.
2. `docs/ARCHITECTURE.md`, frozen, in full.
3. `docs/DEVIATIONS.md`: accepted changes #1–#34+, the carried-forward TODOs, and withdrawn review requests.
4. `docs/PROGRESS.md` and the latest `docs/reports/phase-*.md`.
5. `docs/briefs/BUILDER_HEADER.md` and `docs/briefs/phase-8-order-detail.md`.
6. `DESIGN.md`.
7. `october_master_architecture.md`: the operating manual from an abandoned multi-agent experiment (October). Its roles, rules and results summary are still accurate. Ignore its October-specific tooling sections.
