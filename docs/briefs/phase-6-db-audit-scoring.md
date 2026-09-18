# Phase 6 brief: Phase 5 follow-ups, then DB, audit and scoring service

*(The operator calls this "stage 5 fix and stage 6 build"; the operating manual calls it stage 7. Phase numbering here matches `docs/ARCHITECTURE.md` §12.)*

Issued by the Architect after reviewing `docs/reports/phase-5.md` and the rendered demo text.

Read before writing code: `docs/ARCHITECTURE.md` §3 (schema), §4 (contracts), §9.1 (G6 degraded mode), §10 (audit); `docs/DEVIATIONS.md` in full, especially #14 (degraded mode without scores), #27–#29.

Usage note: iterate with `pytest -m "not slow"`. Run the full suite only before each commit.

Two commits: Part 1 as `phase 5: follow-ups`, Part 2 as `phase 6: db, audit and scoring service`.

---

## Part 1 — Phase 5 follow-ups

Every item here is a sentence that would appear on the reviewer screen and is currently untrue, misleading or clumsy.

**1.1 Reason ordering.** Demo 2's top reason is `NEW_ACCOUNT_HIGH_VALUE` (WEAK, 94.29 pp) above the STRONG device and token evidence. Deviation #27 made reasons **evidence statements**, so order them as evidence:
- `reasons` sorted by `evidence_strength` (STRONG → MODERATE → WEAK), then `|attribution_pp|` descending, then catalog order.
- Do not hide attribution: every code still carries its `attribution_pp`, and `explain_order` additionally returns `attributions_by_magnitude`, the same codes sorted by `|attribution_pp|` only, for the Phase 8 "Model attribution" panel.
- Record in #27.

**1.2 `TEMPORAL_BURST` says accounts, counts orders.** Demo 2 renders "4 linked accounts placed orders" from `linked_orders_24h = 4`, which counts orders. New template: *"Linked accounts placed {n} orders in the last 24 hours."* Architect amendment to §6.5 wording; record in #27.

**1.3 Plurals.** "1 return or delivery claim(s)" reads badly on screen. Add simple count-aware rendering to the template engine: `{n}` followed by a `{noun:singular|plural}` form, or equivalent. Apply it to every template with a count. Demo 3 must render *"The account had 1 flagged return or delivery claim in the last 6 months."* Update the text-safety tests.

**1.4 Return-history percentage.** Demo 1 renders "returns often (52%)" from the **smoothed** rate (0.5172); the account's actual matured rate differs. Render from the raw matured counts instead: *"The customer returned {returns} of {matured} delivered orders. This affects return likelihood, not abuse risk."* The raw counts already exist in the policy-inputs row; pass them in as evidence values. Firing still uses the smoothed-rate predicate.

**1.5 Latency assertion.** Keep median < 20 ms and add p95 < 40 ms over at least 50 calls. Record the measured p95.

**1.6 Confirmed-link counts (#28).** Phase 6 may touch `features/` for this item only. Extend the builder to output two **evidence-only** values for the query order: `device_confirmed_peer_count` (distinct other accounts on this device whose `ABUSE_CONFIRMED` occurred before t0) and `device_most_recent_confirmation_days` (days from the most recent such confirmation to t0). These are not model features: assert they are absent from `ABUSE_FEATURES` and `RETURN_FEATURES`. Pass them to `GRAPH_DEVICE_CONFIRMED_LINK` so the §6.5 template renders with real values. Demo 2 must render *"This device was used by 3 accounts later confirmed for return abuse, most recently N days ago."* with the true N. Keep the counts-free fallback for when the values are missing. Close the #28 TODO.

Part 1 gate: full suite green, commit, push. Report the re-rendered text for all three demos in the Phase 6 report.

---

## Part 2 — Phase 6: DB, audit and scoring service

Out of scope: HTTP routes, OpenAPI, UI, graph layout (`GraphPayload`), `/metrics` assembly. Phase 7 builds those on top of the services here.

### A. Database

- `db/models.py` `create_database`, `delete_database` and `get_engine` already exist. Reuse them. Tables come only from `schema.sql`.
- Add the #14 schema changes if any are not yet applied (nullable `p_return`, `p_abuse`, `cost_optimal_action` guarded by the degraded-mode CHECK). Verify against `DEVIATIONS.md`.

### B. Seeding: `cli seed-db`

1. Delete and recreate `backend/data/sentinel.db`.
2. Load the as-of-`DEMO_CLOCK` world (generator `as_of_view`): accounts, identifiers, orders, order_lines, order_events with `occurred_at < DEMO_CLOCK`. Demo requests are **not** inserted; they arrive through scoring.
3. Insert `policy_versions` (v1.0 TOML text and its line-ending-normalised SHA-256) and `model_registry` rows from `artifacts/model_registry.json`.
4. Seed **exactly 250 `BACKTEST_REPLAY` decisions** from TEST orders:
   - Include every TEST order whose SENTINEL action is not ALLOW, then fill to 250 with ALLOW orders chosen by a seeded draw (seed 20260901).
   - If non-ALLOW orders alone exceed 250, take them by descending `p_abuse` and report the count.
   - Use the offline feature rows and policy inputs, the committed models, `explain_order`, and `decide()` with `decided_at = graph_state_as_of = t0`, matching the backtest exactly. Assert in a test that the seeded actions equal the backtest's SENTINEL actions for those orders.
   - Each seeded decision writes one `DECISION_CREATED` audit event with `occurred_at = t0`, in chronological order.
5. Determinism: seeded `decision_id` and `event_id` are `uuid5` values derived from the order id, so seeding twice produces byte-identical `decisions` and `audit_events` tables, including every `event_hash`. Live-scored decisions may use `uuid4`.
6. Target: `seed-db` completes in under 30 s.

`cli reset-demo`: calls `delete_database` (removing `-wal` and `-shm`), then `seed-db`. Refuses unless `DEMO_MODE` is true.

### C. Audit service: `audit/chain.py`, `audit/service.py`

- Implement §10 exactly: `AuditEventPayload` (with #14's optional `p_return`, `p_abuse`, `cost_optimal_action`), canonical JSON, SHA-256 chain from a 64-zero genesis.
- Round before hashing: money to 2 dp, probabilities to 6 dp.
- Write inside `BEGIN IMMEDIATE`: read the last `event_hash`, insert, commit.
- `verify_chain()` returns `(valid, events_checked, first_broken_seq)`.
- Event types: `DECISION_CREATED`, `OVERRIDE_APPLIED`, `APPEAL_OPENED`. Every event is self-contained per §10.1: override and appeal events repeat the decision's scores, costs, versions and graph summary.

### D. Scoring service: `api/services/scoring.py`

`ScoringService` is constructed once at startup:
- load both model bundles and the reference medians through the registry;
- replay the as-of-`DEMO_CLOCK` history into one `FeatureBuilder`;
- load the policy config.

**Frozen history (architect amendment to leakage control P14).** Live-scored orders are **not** added to the in-memory graph. Every score is computed against the same frozen as-of-`DEMO_CLOCK` history, so scoring is deterministic and **order-independent**: Demo 3 scores identically whether it is scored first or last. Record as a new deviation with this reason. Live orders are still written to the DB.

`score(request: ScoreOrderRequest, source) -> ScoreOrderResponse`:
1. Reject `placed_at > DEMO_CLOCK`.
2. **Idempotency:** if the order id already has a decision, return it with `idempotent_replay = True` and write no new audit event. If the same order id arrives with a different payload (canonical-JSON hash mismatch), raise a conflict error for Phase 7 to map to 409.
3. Insert the order, its lines, and any unseen identifiers (`source` `DEMO` or `LIVE`). Order value is derived from the lines, never from the client.
4. `features_for_request` at `t0 = placed_at`, predict both models, `explain_order`, then `decide()` with `decided_at = DEMO_CLOCK` and `graph_state_as_of` = the replay time.
5. Write the `decisions` row and one `DECISION_CREATED` audit event in **one transaction**. If the audit write fails, the decision must not persist.
6. `status` from `decision_status()`: MANUAL_REVIEW → `PENDING_REVIEW`, otherwise `AUTO_APPLIED`.

**Degraded mode (G6, #14).** If model loading, feature building or prediction raises: produce a degraded decision with `p_return = p_abuse = None`, `costs = []`, `cost_optimal_action = None`, the G6 fallback action (MANUAL_REVIEW if value ≥ ₹5,000, else ALLOW, never BLOCK), `degraded_mode = True`, and a recorded reason. Never crash the request. The trigger for tests is a fault-injection hook on the service, not a flag in production code paths.

### E. Review actions: `api/services/review.py`

- `apply_override(order_id, OverrideRequest, reviewer_id)`:
  - Stale `expected_current_action` → conflict error.
  - Update only `current_action`, `status = OVERRIDDEN` and `latest_audit_event_id`. The DB trigger protects everything else.
  - Write `OVERRIDE_APPLIED` with `previous_action`, `new_action`, `original_recommendation` and the `AuditOverride` block.
  - Overriding to BLOCK while G2 was not satisfied requires `reason_category = INDEPENDENT_EVIDENCE_OF_ABUSE`, otherwise raise a validation error. When allowed, record `guardrail_conflicts = ["G2"]` and return a warning.
  - Chained overrides work: a second override's `previous_action` is the first override's `new_action`.
- `open_appeal(order_id, AppealRequest, actor_id)`: writes `APPEAL_OPENED`, sets `status = APPEAL_OPEN`, and assigns a sequential reference `APL-2026-000001`.

### F. Tests

- **Schema:** fresh DB has all tables and triggers; `UPDATE`/`DELETE` on `audit_events` abort; updating protected `decisions` columns aborts while `current_action`, `status` and `latest_audit_event_id` update.
- **Chain:** verify passes on a seeded DB; editing one payload after dropping the triggers makes verify fail at exactly that `seq`; canonical JSON is stable under key reordering.
- **Seeding:** 250 decisions exactly; seeded actions match the backtest's SENTINEL actions; seeding twice gives identical `event_hash` sequences; no event with `occurred_at ≥ DEMO_CLOCK` in `order_events`; completes under 30 s.
- **Scoring:**
  - Demo 1/2/3 through `ScoringService.score()` produce ALLOW / BLOCK / MANUAL_REVIEW with the same p_abuse as `score-demos` (to 1e-9).
  - Order independence: score the three demos in all 6 permutations on fresh DBs; identical decisions every time.
  - Idempotency: second call returns the same `decision_id`, `idempotent_replay = True`, no new audit event; different payload under the same order id raises the conflict error.
  - Atomicity: forcing the audit insert to fail leaves no decision row.
  - `placed_at > DEMO_CLOCK` is rejected.
- **Degraded mode:** fault injection yields `degraded_mode = True`, null scores, empty costs, never BLOCK, correct value-based fallback, and a valid audit event.
- **Review:**
  - override writes a new event and preserves `recommended_action`
  - stale `expected_current_action` conflicts
  - BLOCK without corroboration requires `INDEPENDENT_EVIDENCE_OF_ABUSE` and records the G2 conflict
  - chained overrides
  - appeal reference is sequential and sets `APPEAL_OPEN`
  - the chain still verifies after all of the above
- **Windows:** `reset-demo` twice in a row succeeds (no file lock).
- **Purity:** `api/services` must not import `sentinel.data.generator`, `sentinel.data.archetypes` or `sentinel.data.labels` (the seeding CLI may).

### G. Progress reporting (required)

Print this at the start, after Part 1, after each Part 2 section A–F, and in the final report:

```
PROGRESS  phase 6 of 12  [#####-----]  6/11 stages to Definition of Done (55%)
          this phase: D. scoring service — 4 of 8 sections done  |  elapsed 1h12m
```

The overall bar counts completed phases (0–5 done = 6 of 11). Sections in this phase: Part 1, A, B, C, D, E, F, gate (8 total).

### H. Gate and report

- Full suite including slow before each of the two commits. Push after each.
- Write the report to `docs/reports/phase-6.md` and update your row in `docs/PROGRESS.md` before the Part 2 commit. Record the real commit hash in a follow-up commit if needed; never amend.
- Report contents:
  1. files changed
  2. test results and timings, including `seed-db` time and the measured p95 latency
  3. the re-rendered Part 1 text for all three demos
  4. seeded decision counts by action and by source
  5. the three demo `ScoreOrderResponse`s as JSON
  6. one `OVERRIDE_APPLIED` audit payload as JSON
  7. `verify_chain()` output
  8. deviations added or updated
  9. open questions
  10. `git status -sb` and `git log --oneline -5`
- Stop. Do not start Phase 7.
