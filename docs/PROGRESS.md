# Sentinel — progress and time log

Times are from git commit timestamps (IST). Every builder updates the row for its stage **before** committing.

**Project start:** 2026-09-16 19:17 (first commit)
**Last update:** 2026-09-18 (phase 8 gate)

## Completed

| Manual stage | Spec phase | What landed | Commits | Finished | Wall-clock span |
|---|---|---|---|---|---|
| 1 | 0 | Skeleton, pins, policy config, contracts, DDL, React shell | `01d2c77` | 09-16 19:17 | day 1 |
| 2 | 1 | Policy engine: costs, G1–G6, `decide()`, baselines | `53dffaa` `c811cee` `42569bc` | 09-16 20:00 | 43 min |
| 3 | 2 | Synthetic generator, labels, demo accounts, rings, hard negatives | `5208112` `530656e` | 09-17 19:49 | ~52 min |
| 4 | 3 | Feature builder, graph, point-in-time leakage suite | `58e977d` `7e1e525` | 09-17 20:15 | ~26 min |
| 5 | 4 | Models, calibration, evaluation, backtest, guardrail pricing | `1c2259c` `53158b2` `91a4837` | 09-18 01:59 | longest stage; 3 architect decision rounds |
| 6 | 5 | Explanations: reference vector, ablation attributions, evidence-based reason codes, prediction explanation | `c5ff8f7` | 09-18 04:25 | ~2h10m build |
| 6 (follow-ups) + 7 | 5 + 6 | Phase 5 follow-ups (evidence ordering, plurals, raw return counts, device confirmation counts, latency p95); SQLite seeding (250 backtest-replay decisions), hash-chained audit, `ScoringService` (frozen history, idempotent, G6 degraded), `ReviewService` (override, appeal), `seed-db` / `reset-demo` | `7fb75f0` `d4881da` | 09-18 08:48 | ~37 min build, 1 architect review round (Phase 5) |
| 7 (follow-ups) + 8 | 6 + 7 | Phase 6 follow-ups (point-in-time discounted links and GraphPayload stored per decision, demo reviewer clock, threadpoolctl declared); API: all internal routes, public checkout with probe logging, metrics, demo presets/reset, deterministic graph view, OpenAPI export and generated `types.ts` | `3dfbf20` `d76f2c1` | 09-18 | session 08:52 → gate; ~1h active build plus a ~1h30m idle gap between turns |
| 8 (follow-ups) + 9 | 7 + 8 | Phase 7 follow-ups (the reviewer graph now draws every account whose evidence is counted beside it, at any hop; `GET /internal/policy`); order detail page: two separate score cards, expected-cost bars with hatched infeasible actions, relationship graph, evidence vs model attribution, audit timeline with chain verification, baselines, override and appeal dialogs, assumptions panel; vitest suite (105) against payloads recorded from the real backend | `fa43f4b` `556ae6a` | 09-18 | ~4h35m session; ~2h15m active build |

**Elapsed since project start:** ~42 hours wall clock.
**Actual build time:** roughly 10–11 hours of agent work. The rest is review turnaround and gaps between sessions.

## Remaining

Estimates revised down from the original plan, since stages 1–5 ran faster than projected. "Build" is agent working time; review rounds are extra and depend on turnaround.

| Manual stage | Spec phase | Scope | Build estimate | Review rounds |
|---|---|---|---|---|
| 10 | 9 | Frontend queue + simulate checkout | 1–1.5 h | 1 |
| 11 | 10 | Frontend overview: activity tiles, backtest panel, calibration | 1.5–2 h | 1 |
| — | — | **Cut line: stages 1–11 are the Definition of Done** | | |
| 12 | 11 | Backtest depth: sensitivity, cohort friction table (carries a TODO), R3 panel | 0.5–1 h | 0–1 |
| 13 | 12 | Hardening: demo reset, degraded mode, audit verify in UI, model card (carries a TODO) | 2–3 h | 1 |
| 14 | — | `docs/DEMO_SCRIPT.md`, two cold-start rehearsals, fallback video | 1–2 h | 0 |
| 15 | — | Pitch and submission | 1–2 h | 1 |

**To Definition of Done (stage 11):** ~2.5–3.5 h of build (stages 10–11).
**To full finish (stage 15):** ~7–12 h of build.

## Notes

- Compute is never the bottleneck: full pipeline regenerates in under 30 s; the full test suite is the slowest step at ~4–6 min.
- Stages 6→7→8→9 are a strict dependency chain; 9 (order detail) is done, so stage 10 (queue) is unblocked. Stage 10 against stage 12 is the first real split.
- Stage 7's estimate (2–3 h) came in well under: ~37 min including the Phase 5 follow-ups, because Phases 3–5 had already built the pieces the scoring service composes. `seed-db` takes ~7 s; the full suite is now ~3.5 min (740 tests).
- Stage 5's estimate (1.5–2.5 h) held: ~2h10m, most of it spent on two catalog gaps the brief could not have known about (#28, #29) and on getting attribution latency from 84 ms to 16 ms.
- If time runs short, hold the cut line at stage 11 and shrink stage 13 to: demo reset, two rehearsals, fallback video.
- Stage 8's estimate (2–3 h) held at the low end: the API composes the Phase 6 services; the new work was the graph view, the read side and the test suite (67 API tests). The full suite is now ~4–5 min (~820 tests); score-order p95 over HTTP is ~35 ms against a 300 ms budget.
- Stage 9's estimate (3–5 h) held at the top of the range in wall clock and came in under it in build time: the page composes what Phases 5–8 already produced, and the work that took the longest was not React but honesty plumbing — reading the BLOCK band out of `/internal/policy` instead of typing 0.70, and making the no-hard-coding scan strict enough to catch a planted threshold without flagging a border width. Three real defects were found only by opening a browser (unhatched bars, a graph that did not fit, a dialog that unmounted itself on success), which is the argument for keeping §F in every frontend brief.
