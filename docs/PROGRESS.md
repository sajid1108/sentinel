# Sentinel — progress and time log

Times are from git commit timestamps (IST). Every builder updates the row for its stage **before** committing.

**Project start:** 2026-09-16 19:17 (first commit)
**Last update:** 2026-09-18 04:25

## Completed

| Manual stage | Spec phase | What landed | Commits | Finished | Wall-clock span |
|---|---|---|---|---|---|
| 1 | 0 | Skeleton, pins, policy config, contracts, DDL, React shell | `01d2c77` | 09-16 19:17 | day 1 |
| 2 | 1 | Policy engine: costs, G1–G6, `decide()`, baselines | `53dffaa` `c811cee` `42569bc` | 09-16 20:00 | 43 min |
| 3 | 2 | Synthetic generator, labels, demo accounts, rings, hard negatives | `5208112` `530656e` | 09-17 19:49 | ~52 min |
| 4 | 3 | Feature builder, graph, point-in-time leakage suite | `58e977d` `7e1e525` | 09-17 20:15 | ~26 min |
| 5 | 4 | Models, calibration, evaluation, backtest, guardrail pricing | `1c2259c` `53158b2` `91a4837` | 09-18 01:59 | longest stage; 3 architect decision rounds |
| 6 | 5 | Explanations: reference vector, ablation attributions, evidence-based reason codes, prediction explanation | `c5ff8f7` | 09-18 04:25 | ~2h10m build, 0 review rounds so far |

**Elapsed since project start:** ~33 hours wall clock.
**Actual build time:** roughly 7–8 hours of agent work. The rest is review turnaround and gaps between sessions.

## Remaining

Estimates revised down from the original plan, since stages 1–5 ran faster than projected. "Build" is agent working time; review rounds are extra and depend on turnaround.

| Manual stage | Spec phase | Scope | Build estimate | Review rounds |
|---|---|---|---|---|
| 7 | 6 | DB, hash-chained audit, scoring service, demo DB seeding | 2–3 h | 1 |
| 8 | 7 | API: all routes, internal key, idempotency, override, public checkout | 2–3 h | 1 |
| 9 | 8 | Frontend order detail: scores, cost bars, graph, reasons, audit, override | 3–5 h | 1–2 |
| 10 | 9 | Frontend queue + simulate checkout | 1–1.5 h | 1 |
| 11 | 10 | Frontend overview: activity tiles, backtest panel, calibration | 1.5–2 h | 1 |
| — | — | **Cut line: stages 1–11 are the Definition of Done** | | |
| 12 | 11 | Backtest depth: sensitivity, cohort friction table (carries a TODO), R3 panel | 0.5–1 h | 0–1 |
| 13 | 12 | Hardening: demo reset, degraded mode, audit verify in UI, model card (carries a TODO) | 2–3 h | 1 |
| 14 | — | `docs/DEMO_SCRIPT.md`, two cold-start rehearsals, fallback video | 1–2 h | 0 |
| 15 | — | Pitch and submission | 1–2 h | 1 |

**To Definition of Done (stage 11):** ~9–15 h of build (stages 7–11).
**To full finish (stage 15):** ~14–23 h of build.

## Notes

- Compute is never the bottleneck: full pipeline regenerates in under 30 s; the full test suite is the slowest step at ~4–6 min.
- Stages 6→7→8 are a strict dependency chain; 6 is done, so stage 7 is now unblocked. Stage 9 against stage 12 is the first real split.
- Stage 5's estimate (1.5–2.5 h) held: ~2h10m, most of it spent on two catalog gaps the brief could not have known about (#28, #29) and on getting attribution latency from 84 ms to 16 ms.
- If time runs short, hold the cut line at stage 11 and shrink stage 13 to: demo reset, two rehearsals, fallback video.
